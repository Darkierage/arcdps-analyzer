"""Optional local LLM debrief via a llama-server subprocess.

The LLM only rewrites the static analyzer's ranked findings into a short debrief. It runs on the
CPU with few threads at idle priority, starts on demand and is killed when idle, so it doesn't
compete with the game.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .. import tools
from ..config import ConfigStore
from ..events import EventBus
from . import prompts

log = logging.getLogger(__name__)

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def unverified_numbers(text: str, source: str) -> list[str]:
    """Numbers in the LLM output that don't appear in the input (small counts excluded)."""
    allowed: set[str] = set()
    for n in _NUM.findall(source):
        v = n.replace(",", ".")
        allowed.add(v)
        if "." in v:  # rounded / truncated forms of decimals are fine ("171.4" -> "171")
            f = float(v)
            allowed |= {str(int(f)), str(round(f)), f"{f:.1f}"}
    bad = []
    for n in _NUM.findall(text):
        v = n.replace(",", ".")
        if v in allowed or (v.isdigit() and int(v) <= 10):
            continue
        bad.append(n)
    return sorted(set(bad))


class LlmService:
    def __init__(self, config: ConfigStore, bus: EventBus):
        self.config = config
        self.bus = bus
        self._proc: subprocess.Popen | None = None
        self._port: int | None = None
        self._lock = threading.Lock()
        self._last_used = 0.0
        self.busy = False
        self.setup_state: dict[str, Any] = {"running": False, "error": None, "progress": None}
        self._stop = threading.Event()
        self._closed = False  # app is exiting: never start llama-server again
        threading.Thread(target=self._idle_loop, name="llm-idle", daemon=True).start()

    # ---- status / setup --------------------------------------------------------------------
    def server_path(self) -> Path | None:
        s = self.config.settings.llm
        if s.server_path:
            p = Path(s.server_path)
            return p if p.exists() else None
        return tools.llama_server_path()

    def model_file(self) -> Path:
        return tools.model_path(self.config.settings.llm.model_file)

    def status(self) -> dict[str, Any]:
        s = self.config.settings.llm
        return {
            "enabled": s.enabled,
            "serverInstalled": self.server_path() is not None,
            "modelInstalled": self.model_file().exists(),
            "model": s.model_file,
            "running": self._proc is not None and self._proc.poll() is None,
            "busy": self.busy,
            "setup": self.setup_state,
            "models": list(tools.MODELS),
        }

    def _emit(self) -> None:
        self.bus.publish({"type": "llm", "llm": self.status()})

    def setup(self) -> None:
        """Download llama-server and the configured model in the background."""
        if self.setup_state["running"]:
            return

        def work() -> None:
            self.setup_state = {"running": True, "error": None, "progress": None,
                                "step": "llama-server"}
            self._emit()
            try:
                if self.server_path() is None:
                    tools.setup_llama()
                self.setup_state["step"] = "model"
                last = [0.0]

                def prog(done: int, total: int) -> None:
                    self.setup_state["progress"] = round(100 * done / total, 1) if total else None
                    if time.time() - last[0] > 1:
                        last[0] = time.time()
                        self._emit()

                tools.download_model(self.config.settings.llm.model_file, prog)
                self.setup_state = {"running": False, "error": None, "progress": 100}
            except Exception as e:  # surfaced in the UI
                log.exception("LLM setup failed")
                self.setup_state = {"running": False, "error": str(e), "progress": None}
            self._emit()

        threading.Thread(target=work, name="llm-setup", daemon=True).start()

    # ---- server lifecycle -----------------------------------------------------------------
    def _start(self) -> None:
        if self._closed:
            raise RuntimeError("WvW Analyzer is closing")
        s = self.config.settings.llm
        server = self.server_path()
        model = self.model_file()
        if server is None:
            raise RuntimeError("llama-server is not installed (Settings > Local LLM > Install)")
        if not model.exists():
            raise RuntimeError(f"Model {model.name} is not downloaded")
        self._port = _free_port()
        cmd = [str(server), "-m", str(model), "--host", "127.0.0.1", "--port", str(self._port),
               "-t", str(s.threads), "-ngl", str(s.gpu_layers), "-c", str(s.ctx_size),
               "--no-webui"]
        kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["preexec_fn"] = lambda: os.nice(19)
        log.info("starting llama-server: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, **kwargs)
        deadline = time.time() + 180
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"llama-server exited with code {self._proc.returncode}")
            try:
                if httpx.get(f"http://127.0.0.1:{self._port}/health", timeout=2).status_code \
                        == 200:
                    self._emit()
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.shutdown()
        raise RuntimeError("llama-server did not become ready in time")

    def shutdown(self, final: bool = False) -> None:
        """Stop llama-server. ``final`` (app exit) also keeps it from being started again."""
        if final:
            self._closed = True
            self._stop.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
            self._emit()

    def _idle_loop(self) -> None:
        while not self._stop.wait(15):
            timeout = self.config.settings.llm.idle_timeout_s
            if self._proc and not self.busy and time.time() - self._last_used > timeout:
                with self._lock:
                    log.info("llama-server idle, unloading")
                    self.shutdown()

    # ---- generation -----------------------------------------------------------------------
    def debrief(self, summary: dict[str, Any], notes: dict[str, Any]) -> dict[str, Any]:
        s = self.config.settings.llm
        variant = s.prompt if s.prompt in prompts.VARIANTS else prompts.DEFAULT
        msgs, prompt = prompts.messages(variant, summary, notes)
        with self._lock:
            self.busy = True
            self._emit()
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._start()
                r = httpx.post(
                    f"http://127.0.0.1:{self._port}/v1/chat/completions",
                    json={"messages": msgs,
                          "max_tokens": s.max_tokens, "temperature": s.temperature,
                          "chat_template_kwargs": {"enable_thinking": False}},
                    timeout=600,
                )
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"] or ""
            finally:
                self.busy = False
                self._last_used = time.time()
                self._emit()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        text = prompts.finalize(variant, summary, text, notes)
        return {"text": text, "unverified": unverified_numbers(text, prompt)}
