"""Run the Elite Insights CLI on a single log and return the generated JSON path."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

BASE_CONF = Path(__file__).with_name("ei_wvw.conf")


class EIError(RuntimeError):
    pass


def _to_windows(p: Path) -> str:
    return subprocess.check_output(["wslpath", "-w", str(p)], text=True).strip()


def _from_windows(p: str) -> Path:
    return Path(subprocess.check_output(["wslpath", "-u", p], text=True).strip())


class EIRunner:
    def __init__(self, exe: Path, out_dir: Path | None = None, timeout_s: float = 600):
        self.exe = exe
        self.out_dir = out_dir or (paths.data_dir() / "ei")
        self.timeout_s = timeout_s
        self.via_wsl = paths.is_wsl() and exe.suffix.lower() == ".exe"

    def available(self) -> bool:
        return self.exe.exists()

    def _arg(self, p: Path) -> str:
        return _to_windows(p) if self.via_wsl else str(p)

    def _conf(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        conf = self.out_dir / "ei_run.conf"
        text = BASE_CONF.read_text(encoding="utf-8")
        text += f"\nOutLocation={self._arg(self.out_dir.resolve())}\n"
        if not conf.exists() or conf.read_text(encoding="utf-8") != text:
            conf.write_text(text, encoding="utf-8")
        return conf

    def parse(self, log_file: Path) -> Path:
        if not self.available():
            raise EIError(f"Elite Insights not found at {self.exe}. Run scripts/setup_tools.py.")
        cmd = [str(self.exe), "-c", self._arg(self._conf()), self._arg(log_file)]
        if self.exe.suffix.lower() == ".dll":
            cmd.insert(0, "dotnet")
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
            )
        log.info("EI parse %s", log_file.name)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_s, **kwargs,
            )
        except subprocess.TimeoutExpired as e:
            raise EIError(f"Elite Insights timed out after {self.timeout_s:.0f}s") from e
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        result = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Processed - "):
                try:
                    result = json.loads(line[len("Processed - "):])
                except json.JSONDecodeError:
                    continue
        if not result:
            tail = " | ".join(out.strip().splitlines()[-3:])
            raise EIError(f"Elite Insights produced no result (exit {proc.returncode}): {tail}")
        if not result.get("parsed"):
            raise EIError(f"Elite Insights could not parse the log: {result.get('status')}")
        files = [f for f in result.get("generatedFiles") or [] if f.endswith((".json", ".gz"))]
        if not files:
            raise EIError("Elite Insights did not generate JSON output")
        path = _from_windows(files[0]) if self.via_wsl else Path(files[0])
        if not path.exists():
            raise EIError(f"Generated JSON missing: {path}")
        return path
