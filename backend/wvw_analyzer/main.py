"""Application entry point: API server + native window (pywebview) or browser."""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler

import uvicorn

from . import paths
from .api.app import create_app
from .config import ConfigStore
from .state import AppState


def _setup_logging(verbose: bool) -> None:
    handlers: list[logging.Handler] = [
        RotatingFileHandler(paths.data_dir() / "wvw_analyzer.log", maxBytes=2_000_000,
                            backupCount=2, encoding="utf-8"),
    ]
    if sys.stdout is not None:  # windowed builds have no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("asyncio").addFilter(_ProactorNoise())


class _ProactorNoise(logging.Filter):
    """Windows' proactor loop logs harmless WinError 10022 when a socket closes; drop it."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "_call_connection_lost" not in record.getMessage()


def _port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def _is_our_app(host: str, port: int) -> bool:
    """Is the program on this port a running WvW Analyzer?"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/status", timeout=1.5) as r:
            data = json.loads(r.read())
        return isinstance(data, dict) and "recording" in data and "version" in data
    except (OSError, ValueError):
        return False


def choose_port(host: str, preferred: int, span: int = 20) -> tuple[int, bool]:
    """(port, already_running): reuse a running instance, or the first free port from preferred."""
    if _port_free(host, preferred):
        return preferred, False
    if _is_our_app(host, preferred):
        return preferred, True
    for port in range(preferred + 1, preferred + span + 1):
        if _port_free(host, port):
            return port, False
    raise RuntimeError(f"No free port between {preferred} and {preferred + span}")


class WindowApi:
    """Functions the page can call in the desktop window (window.pywebview.api.*)."""

    def __init__(self) -> None:
        self.window = None

    def pick_folder(self) -> str | None:
        import webview

        if self.window is None:
            return None
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None


def _open_window(url: str, api: WindowApi | None = None) -> bool:
    """Show the app in a native window; False if pywebview isn't available."""
    try:
        import webview  # pywebview
    except ImportError:
        return False
    api = api or WindowApi()
    api.window = webview.create_window("WvW Analyzer", url, width=1440, height=920,
                                       min_size=(1000, 650), background_color="#0b0f17",
                                       js_api=api)
    webview.start()
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wvw-analyzer")
    parser.add_argument("--no-window", action="store_true", help="don't open a window")
    parser.add_argument("--browser", action="store_true", help="open in the default browser")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    log = logging.getLogger("wvw_analyzer")

    config_store = ConfigStore()
    host = config_store.settings.host
    try:
        port, running = choose_port(host, args.port or config_store.settings.port)
    except RuntimeError as e:
        log.error("%s", e)
        return
    url = f"http://{host}:{port}"
    if running:  # second launch: show the instance that is already running
        log.info("WvW Analyzer is already running at %s", url)
        if not args.no_window and not _open_window(url):
            webbrowser.open(url)
        return

    state = AppState(config_store)
    server = uvicorn.Server(uvicorn.Config(create_app(state), host=host, port=port,
                                           log_level="warning", log_config=None))
    if args.no_window or args.browser:
        if args.browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        log.info("WvW Analyzer running at %s", url)
        server.run()
        return

    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    log.info("WvW Analyzer running at %s", url)
    if not _open_window(url):
        log.info("pywebview not available - opening %s in the browser", url)
        webbrowser.open(url)
        thread.join()
        return
    server.should_exit = True
    thread.join(timeout=10)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
