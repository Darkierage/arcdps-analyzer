import json
import os
import subprocess
import sys
import threading
import time
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factory import zerg
from wvw_analyzer import diagnostics
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.ingest.processor import run_in_worker
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database


def make_client(tmp_path: Path) -> tuple[TestClient, AppState]:
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    return TestClient(create_app(state)), state


@pytest.fixture
def hooks():
    """install() replaces process-wide hooks; put them back after the test."""
    saved = sys.excepthook, threading.excepthook
    yield
    sys.excepthook, threading.excepthook = saved


def test_hooks_log_and_record_uncaught_errors(tmp_path: Path, hooks, caplog):
    diagnostics.install(tmp_path, native=False)

    def boom():
        raise ValueError("bad thing")

    t = threading.Thread(target=boom, name="auto-debrief")
    t.start()
    t.join()
    try:
        raise KeyError("main")
    except KeyError:
        sys.excepthook(*sys.exc_info())

    assert "uncaught error in thread auto-debrief" in caplog.text
    kinds = [(r["kind"], r["message"]) for r in diagnostics.pending_crashes(tmp_path)]
    assert kinds[0] == ("error", "A background task (auto-debrief) stopped: ValueError: bad thing")
    assert kinds[1][0] == "crash" and "KeyError" in kinds[1][1]

    diagnostics.dismiss_crashes(tmp_path)
    assert diagnostics.pending_crashes(tmp_path) == []
    assert len(diagnostics.crash_records(tmp_path)) == 2  # kept for the report


def test_crash_records_are_capped(tmp_path: Path):
    for i in range(diagnostics.MAX_RECORDS + 5):
        diagnostics.record_crash(tmp_path, "error", f"e{i}")
    records = diagnostics.crash_records(tmp_path)
    assert len(records) == diagnostics.MAX_RECORDS and records[-1]["message"] == "e24"


def _marker(data_dir: Path, pid: int, started: float, last_seen: float | None = None) -> Path:
    path = data_dir / f"{diagnostics.RUN_PREFIX}{pid}.json"
    data = {"pid": pid, "version": "0.5.2", "startedAt": started}
    if last_seen is not None:
        data["lastSeen"] = last_seen
    path.write_text(json.dumps(data))
    return path


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_unclean_exit_detected_but_not_after_a_shutdown(tmp_path: Path):
    hour_ago = time.time() - 3600
    unknown = lambda start, end: None  # noqa: E731 - no event log (off Windows)
    diagnostics.begin_run(tmp_path, boot=0, shutdown_between=unknown)
    diagnostics.end_run(tmp_path)
    diagnostics.begin_run(tmp_path, boot=0, shutdown_between=unknown)  # clean exit before
    diagnostics.end_run(tmp_path)
    assert diagnostics.pending_crashes(tmp_path) == []

    # A marker left by a process that is gone, and the PC has been up since before it.
    _marker(tmp_path, _dead_pid(), hour_ago)
    diagnostics.begin_run(tmp_path, boot=hour_ago - 60, shutdown_between=unknown)
    diagnostics.end_run(tmp_path)
    (crash,) = diagnostics.pending_crashes(tmp_path)
    assert crash["kind"] == "exit" and "closed unexpectedly" in crash["message"]

    # No event log: the PC was started after the run was last seen.
    _marker(tmp_path, _dead_pid(), hour_ago, last_seen=hour_ago + 600)
    diagnostics.begin_run(tmp_path, boot=time.time() - 60, shutdown_between=unknown)
    diagnostics.end_run(tmp_path)
    assert len(diagnostics.pending_crashes(tmp_path)) == 1
    assert not list(tmp_path.glob("running-*.json"))


def test_only_a_shutdown_right_after_the_last_heartbeat_ends_a_run(tmp_path: Path):
    """Windows with Fast Startup: the boot time says nothing, the event log decides."""
    asked = []
    last_seen = time.time() - 5 * 3600

    def shutdown_between(start, end):
        asked.append((start, end))
        return answer

    answer = True  # Windows logged a shutdown within minutes of the last heartbeat
    _marker(tmp_path, _dead_pid(), last_seen - 3600, last_seen=last_seen)
    diagnostics.begin_run(tmp_path, boot=0, shutdown_between=shutdown_between)
    diagnostics.end_run(tmp_path)
    assert diagnostics.pending_crashes(tmp_path) == []
    assert asked == [(last_seen, last_seen + diagnostics.SHUTDOWN_GRACE_S)]

    # The app died (or hung) in the evening; the PC was shut down hours later: no shutdown in
    # the window after its last heartbeat, so it's reported, whatever the boot time says.
    answer = False
    _marker(tmp_path, _dead_pid(), last_seen - 3600, last_seen=last_seen)
    diagnostics.begin_run(tmp_path, boot=time.time() - 60, shutdown_between=shutdown_between)
    diagnostics.end_run(tmp_path)
    assert len(diagnostics.pending_crashes(tmp_path)) == 1


def test_heartbeat_updates_the_marker_and_stops_at_end_run(tmp_path: Path):
    diagnostics.begin_run(tmp_path, boot=0, shutdown_between=lambda s, e: None)
    marker = tmp_path / f"running-{os.getpid()}.json"
    first = json.loads(marker.read_text())
    thread = diagnostics.start_heartbeat(tmp_path, interval_s=0.05)
    time.sleep(0.3)
    later = json.loads(marker.read_text())
    assert later["startedAt"] == first["startedAt"] and later["lastSeen"] > first["lastSeen"]
    diagnostics.end_run(tmp_path)
    thread.join(timeout=2)
    time.sleep(0.15)
    assert not thread.is_alive() and not marker.exists()  # not written back after end_run


def test_an_old_marker_with_our_reused_pid_is_still_checked(tmp_path: Path):
    _marker(tmp_path, os.getpid(), time.time() - 3600)
    diagnostics.begin_run(tmp_path, boot=0, shutdown_between=lambda s, e: False)
    diagnostics.end_run(tmp_path)
    assert len(diagnostics.pending_crashes(tmp_path)) == 1


def test_a_live_instance_is_not_reported(tmp_path: Path):
    """A hung instance doesn't answer the port check, so a new one starts next to it."""
    import psutil

    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        marker = _marker(tmp_path, other.pid, psutil.Process(other.pid).create_time() + 0.5)
        diagnostics.begin_run(tmp_path, boot=0, shutdown_between=lambda s, e: False)
        diagnostics.end_run(tmp_path)
        assert diagnostics.pending_crashes(tmp_path) == [] and marker.exists()
    finally:
        other.kill()
        other.wait()
    # Same pid number, but a process created long after the marker: pid reused, not alive.
    marker.write_text(json.dumps({"pid": os.getppid(), "startedAt": 1.0}))
    diagnostics.begin_run(tmp_path, boot=0, shutdown_between=lambda s, e: False)
    diagnostics.end_run(tmp_path)
    assert len(diagnostics.pending_crashes(tmp_path)) == 1 and not marker.exists()


def test_windows_shutdown_query(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=out[0], stdout=out[1])

    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setattr(diagnostics.subprocess, "run", fake_run)
    start = datetime(2026, 11, 21, 18, 51, 7, tzinfo=UTC).timestamp()
    out = (0, "Event[0]:\n  Log Name: System\n  Event ID: 13\n")
    assert diagnostics.windows_shutdown_between(start, start + 300) is True
    assert calls[0][:3] == ["wevtutil", "qe", "System"]
    assert ("TimeCreated[@SystemTime>='2026-11-21T18:51:07.000Z' and "
            "@SystemTime<='2026-11-21T18:56:07.000Z']") in calls[0][3]
    assert "EventID=1074" in calls[0][3] and "EventID=13" in calls[0][3]
    out = (0, "")
    assert diagnostics.windows_shutdown_between(start, start + 300) is False
    out = (15, "access denied")
    assert diagnostics.windows_shutdown_between(start, start + 300) is None


def test_redact():
    text = ("C:\\Users\\Bob\\AppData\\Local\\WvWAnalyzer\\x.log c:/users/bob/Documents "
            "user bob logged; Some.1234 joined; version 0.5.2; net10.0.1234; bobby stays")
    out = diagnostics.redact(text, homes=["C:\\Users\\Bob"], user="Bob")
    assert "%USERPROFILE%\\AppData\\Local" in out and "%USERPROFILE%/Documents" in out
    assert "user <user> logged" in out and "<account> joined" in out
    assert "0.5.2" in out and "net10.0.1234" in out and "bobby stays" in out
    assert "Bob" not in out.replace("bobby", "")


def test_redact_stored_player_names():
    names = {"Some Name.1234", "Two Word Char", "Bob", "Al"}
    text = ("fight failed for Some Name.1234 (Two Word Char); Bob joined; Bobby too; "
            "Al is short; Other.5678 left")
    out = diagnostics.redact(text, homes=[], user="", names=names)
    assert out == ("fight failed for <account> (<player>); <player> joined; Bobby too; "
                   "Al is short; <account> left")


def test_redact_player_names_before_the_user_name():
    out = diagnostics.redact("Bob The Builder downed; Bob's PC; Zoë.1234 joined",
                             homes=[], user="Bob", names={"Bob The Builder"})
    assert out == "<player> downed; <user>'s PC; <account> joined"


def test_player_names_from_stored_fights(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    fid = db.add_fight("/x/a.zevtc", None, 0)
    a = analyze_ei(zerg(10), "a", Settings())
    db.save_analysis(fid, a.summary, a.stats, a.notes)
    names = db.player_names()
    players = a.stats["players"]
    assert {players[0]["account"], players[0]["name"]} <= names
    assert all(isinstance(n, str) and n for n in names)


def test_report_and_endpoints(tmp_path: Path, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr(diagnostics, "open_folder", lambda p: opened.append(p) or True)
    client, state = make_client(tmp_path)
    (tmp_path / diagnostics.LOG_FILE).write_text(
        "".join(f"line {i}\n" for i in range(400)) + "ERROR boom\n", encoding="utf-8")
    sid = state.db.create_session("Raid", "recording")
    fid = state.db.add_fight("/x/20261121-200000.zevtc", sid, 0)
    state.db.set_status(fid, "failed", "EI exited with code 1")
    diagnostics.record_crash(tmp_path, "exit", "WvW Analyzer closed unexpectedly last time.")

    with client:
        status = client.get("/api/status").json()
        assert status["crashes"][0]["kind"] == "exit"
        r = client.post("/api/diagnostics", json={"userAgent": "Mozilla/5.0 Edg/131"}).json()
        text = r["text"]
        assert "Elite Insights: NOT INSTALLED" in text  # no expected version shown
        for part in ("## System", "Edg/131", "## Setup", "Elite Insights", "failed 1",
                     "20261121-200000.zevtc", "EI exited with code 1", "closed unexpectedly",
                     "ERROR boom", "line 399"):
            assert part in text, part
        assert "line 100\n" not in text  # only the end of the log
        assert Path(r["path"]) == tmp_path / diagnostics.REPORT_FILE
        assert Path(r["path"]).read_text(encoding="utf-8") == text

        assert client.post("/api/diagnostics/open-folder").json()["opened"] is True
        assert opened == [tmp_path]
        client.post("/api/diagnostics/dismiss")
        assert client.get("/api/status").json()["crashes"] == []

        # The same local-only rules as every other state-changing request.
        bad = {"origin": "https://evil.example"}
        assert client.post("/api/diagnostics", headers=bad).status_code == 403
        assert client.post("/api/client-error", json={}, headers=bad).status_code == 403


def test_client_errors_are_truncated_and_capped(tmp_path: Path, caplog):
    client, _ = make_client(tmp_path)
    with client:
        r = client.post("/api/client-error", json={"message": "x" * 5000, "stack": "at f()",
                                                   "url": "http://127.0.0.1/fights/1"})
        assert r.json()["ok"] is True
        assert "frontend error at http://127.0.0.1/fights/1: " + "x" * 2000 + "\nat f()" \
            in caplog.text
        assert "x" * 2001 not in caplog.text
        for _ in range(60):
            client.post("/api/client-error", json={"message": "again"})
        assert caplog.text.count("again") == 49
        assert "further frontend errors" in caplog.text


def _die(*_args):
    os._exit(3)


def test_worker_crash_is_reported_readably(tmp_path: Path):
    fault = tmp_path / diagnostics.FAULT_FILE
    with pytest.raises(RuntimeError, match="analysis process crashed"):
        run_in_worker(_die, (), fault, "a.json")
    assert "the analysis worker for a.json died" in fault.read_text(encoding="utf-8")


def _run_log(data_dir: Path, start: str, text: str, age_days: float = 0) -> Path:
    path = data_dir / diagnostics.LOG_DIR / f"{diagnostics.LOG_PREFIX}{start}-1.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))
    return path


def test_each_run_gets_its_own_log_and_old_ones_are_pruned(tmp_path: Path, monkeypatch):
    log_dir = tmp_path / diagnostics.LOG_DIR
    for day in range(1, 8):  # runs 21, 18, 15, 12, 9, 6 and 3 days ago
        age = (8 - day) * 3
        p = _run_log(tmp_path, f"202611{day:02d}-200000", "x", age_days=age)
        if day == 1:
            rolled = Path(str(p) + ".1")
            rolled.write_text("rolled over", encoding="utf-8")
            os.utime(rolled, (time.time() - age * 86400,) * 2)
    path = diagnostics.new_run_log(tmp_path, now=datetime(2026, 11, 21, 19, 0, 0))
    assert path.parent == log_dir and path.name.startswith("wvw_analyzer-20261121-190000-")
    names = sorted(p.name for p in log_dir.iterdir())
    # Days 1-3 are older than 14 days (with the rolled-over part); the rest stay.
    assert names == [f"wvw_analyzer-202611{d:02d}-200000-1.log" for d in range(4, 8)]

    # Runs beyond the count limit go too, oldest first, but the newest few always stay.
    monkeypatch.setattr(diagnostics, "LOG_KEEP_RUNS", 3)
    diagnostics.prune_logs(log_dir)
    assert [p.name[13:21] for p in diagnostics.run_logs(tmp_path)] == [
        "20261107", "20261106", "20261105"]
    monkeypatch.setattr(diagnostics, "LOG_KEEP_BYTES", 0)
    diagnostics.prune_logs(log_dir, now=time.time() + 100 * 86400)
    assert len(diagnostics.run_logs(tmp_path)) == diagnostics.LOG_KEEP_MIN


def test_report_has_the_previous_runs_log(tmp_path: Path, monkeypatch):
    client, state = make_client(tmp_path)
    _run_log(tmp_path, "20261120-190000", "old run\n", age_days=1)
    _run_log(tmp_path, "20261121-180000", "crashed run: analyzing fight 7\n", age_days=0.1)
    current = _run_log(tmp_path, "20261121-190000", "this run\n")
    # A launch that only showed the running app used to add a newer log; and the clock may
    # have gone back, so the newest name isn't the newest run.
    _run_log(tmp_path, "20261121-230000", "clock was ahead\n", age_days=2)
    monkeypatch.setattr(diagnostics, "_run_log", current)
    with client:
        text = client.post("/api/diagnostics").json()["text"]
    assert "## Log of this run (wvw_analyzer-20261121-190000-1.log" in text
    assert "## Log of the previous run (wvw_analyzer-20261121-180000-1.log" in text
    assert "crashed run: analyzing fight 7" in text
    assert "- wvw_analyzer-20261120-190000-1.log" in text and "old run" not in text


def test_report_includes_the_log_from_before_the_upgrade(tmp_path: Path, monkeypatch):
    client, _ = make_client(tmp_path)
    legacy = tmp_path / diagnostics.LOG_FILE
    legacy.write_text("0.5.2 run that crashed\n", encoding="utf-8")
    t = time.time() - 600
    os.utime(legacy, (t, t))
    current = _run_log(tmp_path, "20261121-190000", "first run of the new version\n")
    monkeypatch.setattr(diagnostics, "_run_log", current)
    with client:
        text = client.post("/api/diagnostics").json()["text"]
    assert "## Log of the previous run (wvw_analyzer.log" in text
    assert "0.5.2 run that crashed" in text


def test_second_launch_writes_no_run_log(tmp_path: Path, monkeypatch, hooks):
    from wvw_analyzer import main, paths

    monkeypatch.setenv("WVW_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    monkeypatch.setattr(main, "choose_port", lambda host, port: (port, True))
    monkeypatch.setattr(main, "_open_window", lambda url: True)
    try:
        main.main(["--port", "8799"])
    finally:
        paths.data_dir.cache_clear()
    assert main._file_log is None
    assert not list((tmp_path / diagnostics.LOG_DIR).glob("*.log"))
    assert not list(tmp_path.glob("running-*.json"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal")
def test_sigterm_still_removes_the_run_marker(tmp_path: Path):
    import signal
    import socket
    import urllib.request

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    (tmp_path / "config.yaml").write_text(
        f"onboarded: true\nlog_dir: {tmp_path / 'logs-in'}\ngw2_dir: {tmp_path / 'gw2'}\n")
    env = {**os.environ, "WVW_DATA_DIR": str(tmp_path)}
    app = subprocess.Popen([sys.executable, "-m", "wvw_analyzer.main", "--no-window",
                            "--port", str(port)], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        assert list(tmp_path.glob("running-*.json"))
        app.send_signal(signal.SIGTERM)
        app.wait(timeout=20)
    finally:
        if app.poll() is None:
            app.kill()
    assert not list(tmp_path.glob("running-*.json"))
    assert len(list((tmp_path / diagnostics.LOG_DIR).glob("*.log"))) == 1
