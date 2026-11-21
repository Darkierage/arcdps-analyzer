"""Crash and error capture, and the diagnostics report users can send when something breaks.

Everything stays on this PC: errors go to the log file and a few small files next to the
database, and the user copies the report and sends it themselves (no upload service).

Files in the data folder:
- `logs/wvw_analyzer-<start>-<pid>.log`: one app log per run (set up in `main.py`), so the log
  of a run that crashed is still there after the restart. Old ones are pruned at startup.
- `crashes.json`: crash records; the UI shows them until the user dismisses them.
- `running-<pid>.json`: exists while that app process runs. Still there on the next start, with
  the process gone and no PC shutdown since, means that run did not end normally.
- `crash.log`: native crash dumps (faulthandler) from analysis workers, and from the main
  process off Windows.
- `diagnostics.txt`: the last report built.
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from . import __version__

log = logging.getLogger(__name__)

LOG_FILE = "wvw_analyzer.log"  # before 0.5.3: one rotating log for every run
LOG_DIR = "logs"
LOG_PREFIX = "wvw_analyzer-"
RUN_LOG_BYTES = 5_000_000  # one run's log rolls over once, so it stays under ~10 MB
LOG_KEEP_DAYS = 14
LOG_KEEP_RUNS = 30
LOG_KEEP_BYTES = 100_000_000
LOG_KEEP_MIN = 3  # the newest runs are kept whatever their age or size
CRASH_FILE = "crashes.json"
RUN_PREFIX = "running-"
FAULT_FILE = "crash.log"
REPORT_FILE = "diagnostics.txt"
MAX_RECORDS = 20
MAX_FAULT_BYTES = 1_000_000
LOG_LINES = 250  # per run in the report
# Processes whose Windows crash/hang reports belong in the report.
OUR_PROCESSES = ("wvwanalyzer", "llama-server", "guildwars2eliteinsights")

_lock = threading.Lock()
_fault_file: TextIO | None = None  # kept open: faulthandler writes to it when the process dies
_run_log: Path | None = None  # this process's run log (set by new_run_log)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _summary(exc: BaseException | None) -> str:
    if exc is None:
        return "unknown error"
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= 300 else text[:297] + "..."


# ---- crash records -----------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def record_crash(data_dir: Path, kind: str, message: str) -> None:
    """Remember a crash for the UI banner and the report. kind: crash | error | exit."""
    with _lock:
        path = data_dir / CRASH_FILE
        records = _read_json(path)
        if not isinstance(records, list):
            records = []
        records.append({"at": _now(), "kind": kind, "message": message,
                        "version": __version__, "seen": False})
        try:
            _write_json(path, records[-MAX_RECORDS:])
        except OSError:
            log.warning("could not write %s", path, exc_info=True)


def crash_records(data_dir: Path) -> list[dict[str, Any]]:
    records = _read_json(data_dir / CRASH_FILE)
    return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []


def pending_crashes(data_dir: Path) -> list[dict[str, Any]]:
    """Crash records the user hasn't dismissed yet (newest last)."""
    return [{k: r.get(k) for k in ("at", "kind", "message", "version")}
            for r in crash_records(data_dir) if not r.get("seen")]


def dismiss_crashes(data_dir: Path) -> None:
    with _lock:
        records = crash_records(data_dir)
        if any(not r.get("seen") for r in records):
            for r in records:
                r["seen"] = True
            try:
                _write_json(data_dir / CRASH_FILE, records)
            except OSError:
                log.warning("could not update %s", CRASH_FILE, exc_info=True)


# ---- hooks -------------------------------------------------------------------------------

def install(data_dir: Path, native: bool = True) -> None:
    """Log uncaught exceptions (the packaged app has no console) and record them as crashes.

    native: also dump native crashes into crash.log (off Windows, see below)."""
    previous = sys.excepthook

    def excepthook(exc_type, exc, tb) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            log.critical("uncaught error", exc_info=(exc_type, exc, tb))
            record_crash(data_dir, "crash", f"WvW Analyzer crashed: {_summary(exc)}")
        previous(exc_type, exc, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        log.critical("uncaught error in thread %s", name,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        record_crash(data_dir, "error",
                     f"A background task ({name}) stopped: {_summary(args.exc_value)}")

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    if native:
        enable_native_dumps(data_dir)


def enable_native_dumps(data_dir: Path) -> None:
    """faulthandler for this process, except on Windows: there pywebview runs .NET
    (pythonnet) in this process. faulthandler sees Windows exceptions before anything handles
    them, and .NET raises and handles some routinely (access violations for null references,
    for example); each would be dumped as a "Windows fatal exception", so it would mostly
    produce false alarms. (CPython already skips the CLR's own exception code, 0xE0434352.)"""
    if sys.platform != "win32":
        enable_faulthandler(data_dir / FAULT_FILE, header=f"WvW Analyzer {__version__}")


def enable_faulthandler(path: Path, header: str | None = None) -> None:
    """Dump the Python stacks into `path` if this process dies from a native crash."""
    global _fault_file
    try:
        _trim(path)
        f = open(path, "a", encoding="utf-8")  # noqa: SIM115 - stays open for the process
        if header:
            f.write(f"--- {_now()} {header} started (pid {os.getpid()})\n")
            f.flush()
        faulthandler.enable(f, all_threads=True)
        _fault_file = f
    except OSError:
        log.warning("could not enable crash dumps in %s", path, exc_info=True)


def _trim(path: Path) -> None:
    """Keep the end of an old crash log once it gets big."""
    try:
        if path.stat().st_size > MAX_FAULT_BYTES:
            data = path.read_bytes()[-MAX_FAULT_BYTES // 4:]
            path.write_bytes(data[data.find(b"\n") + 1:])
    except OSError:
        pass


def worker_init(fault_path: str, parent_pid: int | None = None) -> None:
    """Initializer of the analysis worker processes (no pythonnet there)."""
    enable_faulthandler(Path(fault_path))
    if parent_pid:
        threading.Thread(target=exit_with_parent, args=(parent_pid,), name="parent-watch",
                         daemon=True).start()


def exit_with_parent(parent_pid: int, poll_s: float = 5.0) -> None:
    """End this worker once the app is gone. A worker whose app was killed (Task Manager,
    "close the program" on a hung window) otherwise stays running on Windows."""
    import psutil

    try:
        parent = psutil.Process(parent_pid)
    except psutil.Error:
        os._exit(1)
    while True:
        time.sleep(poll_s)
        if not parent.is_running():  # also false if the pid was reused by another process
            os._exit(1)


def note_worker_crash(fault_path: Path, what: str) -> None:
    """Label the dump a dead worker left (faulthandler writes no time or context)."""
    try:
        with open(fault_path, "a", encoding="utf-8") as f:
            f.write(f"--- {_now()} the analysis worker for {what} died\n")
    except OSError:
        pass


# ---- per-run logs ------------------------------------------------------------------------

def new_run_log(data_dir: Path, now: datetime | None = None) -> Path:
    """Path for this run's log file; prunes old run logs first."""
    global _run_log
    log_dir = data_dir / LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    prune_logs(log_dir)
    _run_log = log_dir / f"{LOG_PREFIX}{(now or datetime.now()):%Y%m%d-%H%M%S}-{os.getpid()}.log"
    return _run_log


def _log_groups(data_dir: Path) -> list[tuple[Path, list[Path]]]:
    """(log file, all its files incl. rolled-over parts) per run, most recently written first.
    Includes the single `wvw_analyzer.log` of versions before per-run logs. Ordered by last
    write, not by name: the name's start time says nothing about when a run ended, and the
    clock can go back (daylight saving)."""
    log_dir = data_dir / LOG_DIR
    mains = sorted(log_dir.glob(f"{LOG_PREFIX}*.log")) if log_dir.is_dir() else []
    groups = [(m, [m, *log_dir.glob(m.name + ".*")]) for m in mains]
    legacy = data_dir / LOG_FILE
    if legacy.exists():
        groups.append((legacy, [legacy, *data_dir.glob(LOG_FILE + ".*")]))

    def last_write(group: tuple[Path, list[Path]]) -> float:
        times = []
        for f in group[1]:
            try:
                times.append(f.stat().st_mtime)
            except OSError:
                pass
        return max(times, default=0.0)

    return sorted(groups, key=lambda g: (last_write(g), g[0].name), reverse=True)


def run_logs(data_dir: Path) -> list[Path]:
    """Run logs (and the pre-0.5.3 log), most recently written first."""
    return [main for main, _ in _log_groups(data_dir)]


def prune_logs(log_dir: Path, now: float | None = None) -> None:
    """Delete run logs older than LOG_KEEP_DAYS, beyond LOG_KEEP_RUNS runs or LOG_KEEP_BYTES
    in total (oldest first). The newest LOG_KEEP_MIN runs always stay."""
    now = now if now is not None else time.time()
    total = 0
    for i, (_, files) in enumerate(_log_groups(log_dir.parent)):
        try:
            size = sum(f.stat().st_size for f in files)
            age_days = (now - max(f.stat().st_mtime for f in files)) / 86400
        except OSError:
            continue
        if i >= LOG_KEEP_MIN and (i >= LOG_KEEP_RUNS or age_days > LOG_KEEP_DAYS
                                  or total + size > LOG_KEEP_BYTES):
            for f in files:
                try:
                    f.unlink()
                except OSError:
                    pass  # still open somewhere: next start
        else:
            total += size


# ---- run markers -------------------------------------------------------------------------

def boot_time() -> float | None:
    """When this PC was last started (epoch seconds), or None if unknown. On Windows with
    Fast Startup (the default) a shutdown doesn't reset this, see windows_shutdown_between."""
    try:
        if sys.platform == "win32":
            import ctypes

            tick = ctypes.windll.kernel32.GetTickCount64
            tick.restype = ctypes.c_uint64
            return time.time() - tick() / 1000
        with open("/proc/uptime", encoding="ascii") as f:
            return time.time() - float(f.read().split()[0])
    except (OSError, ValueError, AttributeError):
        return None


# System-log events that mean Windows shut down or restarted: a shutdown/restart started by a
# user or program, the event log stopping (clean shutdown), an unexpected shutdown, the kernel
# shutting down (also logged for Fast Startup), and a reboot without a clean shutdown.
SHUTDOWN_QUERY = (
    "*[System[((Provider[@Name='User32'] and EventID=1074)"
    " or (Provider[@Name='EventLog'] and (EventID=6006 or EventID=6008))"
    " or (Provider[@Name='Microsoft-Windows-Kernel-General'] and EventID=13)"
    " or (Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=41))"
    " and TimeCreated[@SystemTime>='{since}' and @SystemTime<='{until}']]]")


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def windows_shutdown_between(start: float, end: float) -> bool | None:
    """Did Windows shut down or restart between `start` and `end` (epoch seconds)?
    None off Windows or if the event log can't be read."""
    if sys.platform != "win32":
        return None
    try:
        query = SHUTDOWN_QUERY.format(since=_utc(start), until=_utc(end))
        res = subprocess.run(["wevtutil", "qe", "System", f"/q:{query}", "/c:1", "/f:text"],
                             capture_output=True, text=True, timeout=15,
                             errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    return "Event[" in res.stdout


def _still_running(prev: dict[str, Any]) -> bool:
    """Is the process that wrote this marker still alive (same pid AND creation time)?
    This process's own pid counts as not running: begin_run runs before this process writes
    its marker, so such a marker is an old run whose pid was reused."""
    import psutil

    try:
        pid, started = int(prev.get("pid") or 0), float(prev.get("startedAt") or 0)
        if not pid or pid == os.getpid():
            return False
        created = psutil.Process(pid).create_time()
    except (ValueError, TypeError, psutil.Error):
        return False
    return created <= started + 1 and started - created < 600


HEARTBEAT_S = 120  # how often a running app updates its marker's lastSeen
SHUTDOWN_GRACE_S = 2 * HEARTBEAT_S + 60  # a shutdown this soon after lastSeen ended the run
_marker_lock = threading.Lock()
_run_ended = threading.Event()


def _ended_by_os(last_seen: float, boot: float | None,
                 shutdown_between: Callable[[float, float], bool | None]) -> bool:
    """Did a PC shutdown/restart end the run last seen alive at `last_seen`? Only a shutdown
    right after that counts: one hours later doesn't explain why the app had stopped."""
    by_event_log = shutdown_between(last_seen, last_seen + SHUTDOWN_GRACE_S)
    if by_event_log is not None:
        return by_event_log
    # Off Windows (or no event log): the PC was started after the run was last seen.
    return boot is not None and last_seen < boot


def begin_run(data_dir: Path, boot: float | None = None,
              shutdown_between: Callable[[float, float], bool | None] | None = None) -> None:
    """Check how earlier runs ended, then mark this one as running."""
    boot = boot if boot is not None else boot_time()
    shutdown_between = shutdown_between or windows_shutdown_between
    for marker in sorted(data_dir.glob(f"{RUN_PREFIX}*.json")):
        prev = _read_json(marker)
        if isinstance(prev, dict) and _still_running(prev):
            # Probably a hung instance whose API didn't answer the port check.
            log.warning("WvW Analyzer pid %s (started %s) is still running", prev.get("pid"),
                        prev.get("startedAt"))
            continue
        if isinstance(prev, dict):
            started = float(prev.get("startedAt") or 0)
            last_seen = float(prev.get("lastSeen") or started)
            when = (datetime.fromtimestamp(started).isoformat(timespec="minutes")
                    if started else "?")
            if _ended_by_os(last_seen, boot, shutdown_between):
                log.info("previous run (started %s) ended with a PC shutdown or restart", when)
            else:
                seen = datetime.fromtimestamp(last_seen).isoformat(timespec="minutes")
                log.warning("previous run (version %s, started %s, last seen %s) did not close "
                            "normally", prev.get("version"), when, seen)
                record_crash(data_dir, "exit", "WvW Analyzer closed unexpectedly last time "
                                               f"(started {when.replace('T', ' ')}).")
        try:
            marker.unlink()
        except OSError:
            pass
    _run_ended.clear()
    _write_marker(data_dir, time.time())


def _write_marker(data_dir: Path, started: float) -> None:
    marker = data_dir / f"{RUN_PREFIX}{os.getpid()}.json"
    with _marker_lock:
        if _run_ended.is_set():
            return  # end_run already removed it: don't bring it back
        try:
            _write_json(marker, {"pid": os.getpid(), "version": __version__,
                                 "startedAt": started, "lastSeen": time.time()})
        except OSError:
            log.warning("could not write %s", marker, exc_info=True)


def start_heartbeat(data_dir: Path, interval_s: float = HEARTBEAT_S) -> threading.Thread:
    """Update this run's lastSeen until end_run. A hung app (no GIL for this thread) stops
    updating it too, so a later shutdown can't hide the hang."""
    marker = data_dir / f"{RUN_PREFIX}{os.getpid()}.json"
    prev = _read_json(marker)
    started = float(prev.get("startedAt")) if isinstance(prev, dict) else time.time()

    def beat() -> None:
        while not _run_ended.wait(interval_s):
            _write_marker(data_dir, started)

    thread = threading.Thread(target=beat, name="run-heartbeat", daemon=True)
    thread.start()
    return thread


def end_run(data_dir: Path) -> None:
    with _marker_lock:
        _run_ended.set()  # stops the heartbeat before the marker goes
        try:
            (data_dir / f"{RUN_PREFIX}{os.getpid()}.json").unlink(missing_ok=True)
        except OSError:
            pass


# ---- report ------------------------------------------------------------------------------

# GW2 account names: letters (any language) and digits, then a dot and four digits.
ACCOUNT_RE = re.compile(r"(?<![\w.])[^\W\d_]\w{2,26}\.\d{4}(?![\w.])")


def redact(text: str, homes: list[str] | None = None, user: str | None = None,
           names: Iterable[str] = ()) -> str:
    """Remove the user folder, the Windows user name, the given player names (accounts and
    characters stored in the database) and anything shaped like a GW2 account (Name.1234)."""
    if homes is None:
        homes = [str(Path.home()), os.environ.get("USERPROFILE", "")]
    if user is None:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    for home in sorted({h.rstrip("\\/") for h in homes if h}, key=len, reverse=True):
        if len(home) > 3:
            for form in {home, home.replace("\\", "/")}:
                text = re.sub(re.escape(form), "%USERPROFILE%", text, flags=re.IGNORECASE)
    # Stored names before the user name: a character name that contains the user name would
    # otherwise no longer match and stay half visible.
    for name in sorted({n.strip() for n in names if n and len(n.strip()) >= 3}, key=len,
                       reverse=True):
        if name in text:  # cheap check first: thousands of names, few of them in the text
            mark = "<account>" if re.search(r"\.\d{4}$", name) else "<player>"
            text = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w])", mark, text)
    text = ACCOUNT_RE.sub("<account>", text)
    if len(user) >= 3:
        text = re.sub(rf"(?<![^\W_]){re.escape(user)}(?![^\W_])", "<user>", text,
                      flags=re.IGNORECASE)
    return text


def _tail_lines(path: Path, lines: int, max_bytes: int = 400_000) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(data.splitlines()[-lines:])


def windows_error_events(days: int = 30, limit: int = 5) -> list[str]:
    """Windows Error Reporting / .NET Runtime / hang events for our processes."""
    if sys.platform != "win32":
        return []
    query = ("*[System[(EventID=1000 or EventID=1002 or EventID=1026) and "
             f"TimeCreated[timediff(@SystemTime) <= {days * 86_400_000}]]]")
    try:
        res = subprocess.run(["wevtutil", "qe", "Application", f"/q:{query}", "/c:300",
                              "/rd:true", "/f:text"], capture_output=True, text=True,
                             timeout=20, errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"(could not read the Windows event log: {e})"]
    blocks = re.split(r"(?m)^Event\[\d+\]:?\s*$", res.stdout)
    ours = [b.strip() for b in blocks if any(p in b.lower() for p in OUR_PROCESSES)]
    return [b if len(b) <= 2500 else b[:2500] + "\n..." for b in ours[:limit]]


def _fence(text: str) -> str:
    return "```\n" + (text.strip() or "(empty)") + "\n```"


def build_report(state: Any, user_agent: str | None = None) -> str:
    """The text a user pastes into a chat message (or attaches as diagnostics.txt)."""
    from . import addon_install
    from .analysis import ANALYZER_VERSION

    data_dir: Path = state.data_dir
    s = state.config.settings
    out: list[str] = [f"WvW Analyzer diagnostics ({_now().replace('T', ' ')})", ""]

    def section(title: str, body: str) -> None:
        out.extend([f"## {title}", body, ""])

    frozen = "installed app" if getattr(sys, "frozen", False) else "from source"
    system = [f"Version: {__version__} (analyzer {ANALYZER_VERSION}, {frozen})",
              f"OS: {platform.platform()}",
              f"Python: {platform.python_version()}"]
    if user_agent:
        system.append(f"Window: {user_agent[:300]}")
    section("System", "\n".join(system))

    setup: list[str] = []
    log_dir = s.resolved_log_dir()
    setup.append(f"arcdps log folder: {'found' if log_dir and log_dir.is_dir() else 'NOT FOUND'}"
                 f" ({log_dir or 'not set'})")
    try:
        runner = state.processor.runner()
        if not runner.available():
            raise FileNotFoundError("NOT INSTALLED")
        ei = runner.self_test()
        setup.append(f"Elite Insights {ei.get('version')}: "
                     f"{'ok' if ei.get('ok') else 'NOT OK'}, .NET {ei.get('runtime') or '-'}"
                     + (f" - {ei['error']}" if ei.get("error") else ""))
    except FileNotFoundError:
        setup.append("Elite Insights: NOT INSTALLED")
    except Exception as e:  # the report must not fail because one check did
        setup.append(f"Elite Insights: check failed ({_summary(e)})")
    try:
        addon = addon_install.status(s.gw2_dir)
        setup.append(f"Guild Wars 2 folder: {'found' if addon.get('gw2Dir') else 'not found'};"
                     f" Nexus: {'yes' if addon.get('nexus') else 'no'}; overlay addon: "
                     + ("not installed" if not addon.get("installed") else
                        "up to date" if addon.get("upToDate") else "outdated"))
    except Exception as e:
        setup.append(f"Overlay addon: check failed ({_summary(e)})")
    llm = state.llm.status()
    setup.append(f"LLM debrief: {'on' if llm.get('enabled') else 'off'}"
                 f" (server {'yes' if llm.get('serverInstalled') else 'no'},"
                 f" model {'yes' if llm.get('modelInstalled') else 'no'},"
                 f" {'running' if llm.get('running') else 'not running'})"
                 + (f" - setup error: {llm['setup']['error']}"
                    if (llm.get("setup") or {}).get("error") else ""))
    setup.append(f"Fight mode for new fights: {s.fight_mode};"
                 f" auto record: {'on' if s.recording.auto_record else 'off'}")
    section("Setup", "\n".join(setup))

    rows = state.db.fights(include_skipped=True, limit=100_000)
    counts = Counter(r["status"] for r in rows)
    fights = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"
    failed = [r for r in rows if r["status"] == "failed"][:10]
    body = f"By status: {fights}"
    if failed:
        body += "\n\nLatest failed:\n" + "\n".join(
            f"- {r.get('log_name') or '?'} ({r.get('updated_at') or '?'}): {r.get('error')}"
            for r in failed)
    section("Fights", body)

    records = crash_records(data_dir)
    section("Crashes and unexpected exits", "\n".join(
        f"- {r.get('at')} v{r.get('version')}: {r.get('message')}" for r in records[-10:])
        or "none recorded")

    events = windows_error_events()
    if events:
        section("Windows error reports (last 30 days)", "\n\n".join(_fence(e) for e in events))

    fault = _tail_lines(data_dir / FAULT_FILE, 150, max_bytes=20_000)
    if "Fatal Python error" in fault or "fatal exception" in fault.lower() or "died" in fault:
        section("Native crash dumps (end of crash.log)", _fence(fault))

    logs = run_logs(data_dir)
    current = _run_log if _run_log in logs else None
    others = [p for p in logs if p != current]
    shown = ([("Log of this run", current), ("Log of the previous run", others[0])]
             if current and others else [("Log of this run", current)] if current
             else list(zip(("Latest log", "Log before that"), others, strict=False)))
    for title, path in shown:
        section(f"{title} ({path.name}, last {LOG_LINES} lines)",
                _fence(_tail_lines(path, LOG_LINES)))
    if not shown:
        section("Log", "(no log file)")
    older = [p for p in logs if p not in {path for _, path in shown}]
    if older:
        section("Older logs (ask for one if needed)", "\n".join(
            f"- {p.name} ({p.stat().st_size // 1024} KB)" for p in older[:10]))
    try:
        names = state.db.player_names()
    except Exception:  # the report must still go out without this
        log.warning("could not read player names for redaction", exc_info=True)
        names = set()
    return redact("\n".join(out).rstrip() + "\n", names=names)


def save_report(data_dir: Path, text: str) -> Path:
    path = data_dir / REPORT_FILE
    path.write_text(text, encoding="utf-8")
    return path


def open_folder(path: Path) -> bool:
    """Show a folder in the file manager; False if that isn't possible here."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if shutil.which(opener):
            subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
    except OSError:
        log.warning("could not open %s", path, exc_info=True)
    return False
