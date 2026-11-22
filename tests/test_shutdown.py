"""The app exits promptly with a page connected to the live-events WebSocket.

The /ws handler used to wait only for the next event, so it never noticed its socket closing.
uvicorn waits for every connection at shutdown (with no time limit then), so after SIGTERM the
`--no-window` app closed its port and then never exited, and closing the window waited the full
10 s join and skipped the lifespan shutdown. The bounds below stay under main.SHUTDOWN_TIMEOUT_S:
that safety net alone would also end the wait, only later.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from websockets.sync.client import connect

from wvw_analyzer import main, paths
from wvw_analyzer.config import ConfigStore
from wvw_analyzer.state import AppState

QUICK_EXIT_S = 3.0
assert QUICK_EXIT_S < main.SHUTDOWN_TIMEOUT_S


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_config(data_dir: Path) -> None:
    (data_dir / "config.yaml").write_text(
        f"onboarded: true\nlog_dir: {data_dir / 'logs-in'}\ngw2_dir: {data_dir / 'gw2'}\n")


def _wait_until_up(port: int) -> None:
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1)
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("the app did not start")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal")
@pytest.mark.parametrize("page", ["open", "closed before the signal"])
def test_sigterm_exits_with_a_page_on_the_websocket(tmp_path: Path, page: str):
    port = _free_port()
    _write_config(tmp_path)
    env = {**os.environ, "WVW_DATA_DIR": str(tmp_path)}
    app = subprocess.Popen([sys.executable, "-m", "wvw_analyzer.main", "--no-window",
                            "--port", str(port)], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        _wait_until_up(port)
        with connect(f"ws://127.0.0.1:{port}/ws") as ws:
            assert '"hello"' in ws.recv(timeout=5)
            if page != "open":
                ws.close()  # a tab closed earlier, with no event since
                time.sleep(0.3)
            app.send_signal(signal.SIGTERM)
            try:
                app.wait(timeout=QUICK_EXIT_S)
            except subprocess.TimeoutExpired:
                raise AssertionError(f"still running {QUICK_EXIT_S} s after SIGTERM") from None
    finally:
        if app.poll() is None:
            app.kill()
            app.wait()
    assert not list(tmp_path.glob("running-*.json"))


def test_window_close_stops_the_app_with_a_page_connected(tmp_path: Path, monkeypatch):
    """The windowed path: the window (with its page on /ws) closes, then the server stops. Its
    lifespan shutdown (processor, recorder, LLM) must run, not be cut off by the join timeout."""
    _write_config(tmp_path)
    monkeypatch.setenv("WVW_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    stops: list[float] = []
    real_stop = AppState.stop
    monkeypatch.setattr(AppState, "stop", lambda self: (stops.append(time.monotonic()),
                                                        real_stop(self)))

    def window(url: str) -> bool:  # the page connects, then the window is closed
        with connect(url.replace("http", "ws", 1) + "/ws") as ws:
            assert '"hello"' in ws.recv(timeout=5)
        return True

    monkeypatch.setattr(main, "_open_window", window)
    port = _free_port()
    args = argparse.Namespace(no_window=False, browser=False)
    try:
        t0 = time.monotonic()
        main._serve(args, ConfigStore(), "127.0.0.1", port, f"http://127.0.0.1:{port}")
        took = time.monotonic() - t0
    finally:
        paths.data_dir.cache_clear()
    assert stops, "the server's lifespan shutdown did not run"
    assert took < QUICK_EXIT_S + 1  # + the start-up wait for the server
