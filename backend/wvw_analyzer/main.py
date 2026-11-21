"""Application entry point: API server + native window (pywebview) or browser."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler

import uvicorn

from . import diagnostics, paths
from .api.app import create_app
from .config import ConfigStore
from .state import AppState

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_file_log: logging.Handler | None = None


def _setup_logging(verbose: bool) -> None:
    """Console only: the run log file is added once this launch is known to run the app."""
    handlers: list[logging.Handler] = [logging.NullHandler()]
    if sys.stdout is not None:  # windowed builds have no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format=LOG_FORMAT)
    logging.getLogger("asyncio").addFilter(_ProactorNoise())


def _add_run_log() -> None:
    """One log file per run, so the log of a run that crashed survives the restart. A launch
    that only shows the already running app gets none: it would push the crashed run's log
    out of the diagnostics report."""
    global _file_log
    if _file_log is None:
        _file_log = RotatingFileHandler(diagnostics.new_run_log(paths.data_dir()),
                                        maxBytes=diagnostics.RUN_LOG_BYTES, backupCount=1,
                                        encoding="utf-8")
        _file_log.setFormatter(logging.Formatter(LOG_FORMAT))
        logging.getLogger().addHandler(_file_log)


def _exit_on_sigterm(signum: int, frame: object) -> None:
    # uvicorn re-raises a SIGTERM it caught once it has shut down; the default action would
    # kill the process before `finally` removes the run marker (a false "crash" next start).
    raise SystemExit(0)


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
        return isinstance(data, dict) and (data.get("app") == "wvw-analyzer" or (
            "recording" in data and "version" in data))  # before 0.5.0: no "app" field
    except (OSError, ValueError):
        return False


def choose_port(host: str, preferred: int, span: int = 20) -> tuple[int, bool]:
    """(port, already_running): reuse a running instance, or the first free port from preferred.

    A running instance may sit on a later port: it took the first free one when its preferred
    port was busy. So each busy port up to the first free one is checked for it (two instances
    would share one database and both record). Probing a free port is slow on Windows (a
    refused connect takes ~2 s), so the walk stops at the first free port."""
    for port in range(preferred, preferred + span + 1):
        if _port_free(host, port):
            return port, False
        if _is_our_app(host, port):
            return port, True
    raise RuntimeError(f"No free port between {preferred} and {preferred + span}")


class WindowApi:
    """Functions the page can call in the desktop window (window.pywebview.api.*).

    Only methods may be public here. On every page load pywebview walks each public attribute
    of this object, recursively, to find callable functions. A public `window` attribute made
    it walk the whole WinForms/WebView2 object tree from a background thread; the packaged app
    then deadlocked a few seconds after start (window "Not Responding", API and analysis
    stopped). Attributes starting with "_" are skipped.
    """

    def __init__(self) -> None:
        self._window = None

    def pick_folder(self) -> str | None:
        import webview

        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None


def _open_window(url: str, api: WindowApi | None = None) -> bool:
    """Show the app in a native window; False if pywebview isn't available."""
    try:
        import webview  # pywebview
    except ImportError:
        return False
    api = api or WindowApi()
    api._window = webview.create_window("WvW Analyzer", url, width=1440, height=920,
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
    data_dir = paths.data_dir()
    diagnostics.install(data_dir, native=False)
    log = logging.getLogger("wvw_analyzer")

    try:
        config_store = ConfigStore()
        host = config_store.settings.host
        port, running = choose_port(host, args.port or config_store.settings.port)
    except RuntimeError as e:  # no free port
        _add_run_log()
        log.error("%s", e)
        return
    except BaseException:
        _add_run_log()  # the uncaught-error hook then logs it into the file
        raise
    url = f"http://{host}:{port}"
    if running:  # second launch: show the instance that is already running
        log.info("WvW Analyzer is already running at %s", url)
        if not args.no_window and not _open_window(url):
            webbrowser.open(url)
        return

    _add_run_log()
    diagnostics.enable_native_dumps(data_dir)
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    diagnostics.begin_run(data_dir)
    diagnostics.start_heartbeat(data_dir)
    try:
        _serve(args, config_store, host, port, url)
    finally:
        diagnostics.end_run(data_dir)


def _serve(args: argparse.Namespace, config_store: ConfigStore, host: str, port: int,
           url: str) -> None:
    log = logging.getLogger("wvw_analyzer")
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
    # Window closed: the run ended normally. Say so before the slower cleanup below; at a
    # Windows shutdown the process may be ended before that finishes.
    diagnostics.end_run(paths.data_dir())
    # Stop llama-server first: a debrief still being written would otherwise
    # hold up the server's shutdown past the join below, and the process would exit without
    # the shutdown step, leaving llama-server running.
    state.llm.shutdown(final=True)
    server.should_exit = True
    thread.join(timeout=10)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
