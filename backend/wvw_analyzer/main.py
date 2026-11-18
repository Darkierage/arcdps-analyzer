"""Application entry point: API server + native window (pywebview) or browser."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler

import uvicorn

from . import paths
from .api.app import create_app
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wvw-analyzer")
    parser.add_argument("--no-window", action="store_true", help="don't open a window")
    parser.add_argument("--browser", action="store_true", help="open in the default browser")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    log = logging.getLogger("wvw_analyzer")

    state = AppState()
    settings = state.config.settings
    host, port = settings.host, args.port or settings.port
    if not _port_free(host, port):
        log.error("Port %s is in use - is WvW Analyzer already running?", port)
        url = f"http://{host}:{port}"
        if not args.no_window:
            webbrowser.open(url)
        return

    config = uvicorn.Config(create_app(state), host=host, port=port, log_level="warning",
                            log_config=None)
    server = uvicorn.Server(config)
    url = f"http://{host}:{port}"

    if args.no_window or args.browser:
        if args.browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        log.info("WvW Analyzer running at %s", url)
        server.run()
        return

    try:
        import webview  # pywebview
    except ImportError:
        log.info("pywebview not available - opening %s in the browser", url)
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        server.run()
        return

    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    webview.create_window("WvW Analyzer", url, width=1440, height=920, min_size=(1000, 650),
                          background_color="#0b0f17")
    webview.start()
    server.should_exit = True
    thread.join(timeout=10)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
