"""The optional OBS connection, against a fake OBS WebSocket v5 server (plan 18, phase 4)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from websockets.sync.server import serve

from wvw_analyzer.config import ConfigStore
from wvw_analyzer.events import EventBus
from wvw_analyzer.obs import (
    ObsConnection,
    ObsService,
    auth_string,
    check_connection,
    gb_per_hour,
)
from wvw_analyzer.store.db import Database


class FakeObs:
    """Enough of OBS WebSocket v5 for the app: auth, record requests and record events."""

    def __init__(self, record_dir: Path, password: str = "secret", port: int = 0):
        self.password = password
        self.record_dir = record_dir
        self.active = False
        self.paused = False
        self.started_at = 0.0
        self.fail_start = False
        self.status_extra: dict[str, Any] = {}  # e.g. outputDuration / outputBytes (plan 19)
        self.file_size = 1  # bytes in each finished file (sparse)
        self.requests: list[str] = []
        self.conns: list[Any] = []
        self._lock = threading.Lock()
        self._n = 0
        self.server = serve(self._handler, "127.0.0.1", port)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

    def _send(self, ws: Any, msg: dict) -> None:
        with self._lock:
            ws.send(json.dumps(msg))

    def emit(self, event_type: str, data: dict) -> None:
        for ws in list(self.conns):
            try:
                self._send(ws, {"op": 5, "d": {"eventType": event_type, "eventIntent": 64,
                                               "eventData": data}})
            except Exception:
                pass

    def _handler(self, ws: Any) -> None:
        hello: dict[str, Any] = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"salt": "pepper", "challenge": "abc"}
        self._send(ws, {"op": 0, "d": hello})
        ident = json.loads(ws.recv())["d"]
        if self.password and ident.get("authentication") != auth_string(self.password, "pepper",
                                                                         "abc"):
            ws.close(4009, "Authentication failed.")
            return
        assert ident["eventSubscriptions"] == 1 << 6
        self._send(ws, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
        self.conns.append(ws)
        try:
            for raw in ws:
                d = json.loads(raw)["d"]
                self._request(ws, d)
        except Exception:
            pass
        finally:
            self.conns.remove(ws)

    def _reply(self, ws: Any, d: dict, data: dict | None = None, ok: bool = True,
               comment: str | None = None) -> None:
        status: dict[str, Any] = {"result": ok, "code": 100 if ok else 500}
        if comment:
            status["comment"] = comment
        self._send(ws, {"op": 7, "d": {"requestType": d["requestType"],
                                       "requestId": d["requestId"],
                                       "requestStatus": status, "responseData": data or {}}})

    def _request(self, ws: Any, d: dict) -> None:
        t = d["requestType"]
        self.requests.append(t)
        if t == "GetVersion":
            self._reply(ws, d, {"obsVersion": "31.0.0"})
        elif t == "GetRecordDirectory":
            self._reply(ws, d, {"recordDirectory": str(self.record_dir)})
        elif t == "GetRecordStatus":
            dur = int((time.time() - self.started_at) * 1000) if self.active else 0
            self._reply(ws, d, {"outputActive": self.active, "outputPaused": self.paused,
                                "outputDuration": dur, "outputBytes": dur * 1000,
                                **(self.status_extra if self.active else {})})
        elif t == "StartRecord":
            if self.fail_start:
                self._reply(ws, d, ok=False, comment="Not enough disk space")
                return
            self._reply(ws, d)
            self.start()
        elif t == "StopRecord":
            path = self.stop()
            self._reply(ws, d, {"outputPath": path})
        else:
            self._reply(ws, d, ok=False, comment="unknown")

    # What happens in OBS (also the user's own clicks there).
    def start(self) -> None:
        self.active, self.paused, self.started_at = True, False, time.time()
        self.emit("RecordStateChanged", {"outputActive": True,
                                         "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED",
                                         "outputPath": None})

    def stop(self) -> str:
        self._n += 1
        path = self.record_dir / f"rec{self._n}.mkv"
        with path.open("wb") as f:
            f.truncate(self.file_size)
        self.active = False
        self.emit("RecordStateChanged", {"outputActive": False,
                                         "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPED",
                                         "outputPath": str(path)})
        return str(path)

    def pause(self, on: bool) -> None:
        self.paused = on
        self.emit("RecordStateChanged", {"outputActive": True, "outputPath": None,
                                         "outputState": "OBS_WEBSOCKET_OUTPUT_"
                                                        + ("PAUSED" if on else "RESUMED")})

    def split(self, new_path: Path) -> None:
        new_path.write_bytes(b"x")
        self.emit("RecordFileChanged", {"newOutputPath": str(new_path)})


def wait(cond: Any, timeout: float = 5.0) -> Any:
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("timed out")


@pytest.fixture
def obs(tmp_path: Path):
    rec = tmp_path / "rec"
    rec.mkdir()
    fake = FakeObs(rec)
    yield fake
    fake.close()


def _service(tmp_path: Path, fake: FakeObs, recording: bool = False, password: str = "secret",
             **obs: Any) -> tuple[ObsService, Database, SimpleNamespace]:
    config = ConfigStore(tmp_path / "config.yaml")
    config.update({"obs": {"enabled": True, "port": fake.port, "password": password, **obs}})
    db = Database(tmp_path / "t.db")
    recorder = SimpleNamespace(recording=recording)
    return ObsService(config, db, EventBus(), recorder), db, recorder


def test_test_connection(obs: FakeObs):
    assert check_connection(obs.port, "secret") == {"ok": True, "version": "31.0.0", "error": None}
    bad = check_connection(obs.port, "wrong")
    assert not bad["ok"] and "password" in bad["error"]
    assert "asks for a password" in check_connection(obs.port, "")["error"]
    obs.close()
    assert not check_connection(obs.port, "secret")["ok"]


def test_app_recording_starts_and_stops_obs_and_links_the_file(tmp_path: Path, obs: FakeObs):
    svc, db, recorder = _service(tmp_path, obs)
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        recorder.recording = True
        before = int(time.time() * 1000)
        svc.on_recording(True)
        row = wait(lambda: next(iter(db.videos()), None))
        assert obs.active and row["started_by_app"] and row["sync_source"] == "obs"
        assert row["path"] is None and row["end_ms"] is None
        assert before - 1000 <= row["start_ms"] <= int(time.time() * 1000)

        obs.pause(True)
        time.sleep(0.15)
        obs.pause(False)
        wait(lambda: db.video(row["id"])["pauses"])
        p = db.video(row["id"])["pauses"][0]
        assert 100 <= p[1] - p[0] <= 1000

        recorder.recording = False
        svc.on_recording(False)
        done = wait(lambda: (v := db.video(row["id"])) and v["path"] and v)
        assert "StopRecord" in obs.requests and not obs.active
        assert done["path"].endswith("rec1.mkv") and done["end_ms"] >= done["start_ms"]
        assert svc.status()["recording"] is False
    finally:
        svc.stop()


def test_a_recording_started_in_obs_is_linked_but_never_stopped(tmp_path: Path, obs: FakeObs):
    svc, db, recorder = _service(tmp_path, obs)
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        obs.start()  # the user clicks Start Recording in OBS
        row = wait(lambda: next(iter(db.videos()), None))
        assert not row["started_by_app"]
        recorder.recording = True
        svc.on_recording(True)  # OBS already records: used as it is
        recorder.recording = False
        svc.on_recording(False)
        time.sleep(0.3)
        assert "StartRecord" not in obs.requests and "StopRecord" not in obs.requests
        assert obs.active
    finally:
        svc.stop()


def test_split_files_and_obs_connecting_while_the_app_records(tmp_path: Path, obs: FakeObs):
    svc, db, recorder = _service(tmp_path, obs, recording=True)
    svc.start()  # the app already records: OBS starts as soon as it is connected
    try:
        first = wait(lambda: next(iter(db.videos()), None))
        assert "StartRecord" in obs.requests and first["started_by_app"]
        obs.split(obs.record_dir / "part2.mkv")
        second = wait(lambda: len(db.videos()) == 2 and db.videos()[1])
        assert second["path"].endswith("part2.mkv") and second["started_by_app"]
        assert db.video(first["id"])["end_ms"] == second["start_ms"]
    finally:
        svc.stop()


def test_leftover_recording_from_a_previous_run(tmp_path: Path, obs: FakeObs):
    svc, db, recorder = _service(tmp_path, obs)
    obs.active, obs.started_at = True, time.time() - 60
    vid_id = db.add_video(path=None, label="OBS", start_ms=int(obs.started_at * 1000),
                          end_ms=None, sync_source="obs", started_by_app=True, pauses=[])
    svc.start()
    try:
        wait(lambda: svc.status()["leftover"])
        assert db.video(vid_id)["end_ms"] is None  # still the file being written
        assert svc.leftover("keep")["leftover"] is False
        assert not db.video(vid_id)["started_by_app"] and obs.active
        svc.on_recording(False)  # kept: the app no longer stops it
        time.sleep(0.3)
        assert "StopRecord" not in obs.requests
    finally:
        svc.stop()


def test_leftover_stop(tmp_path: Path, obs: FakeObs):
    svc, db, _ = _service(tmp_path, obs)
    obs.active, obs.started_at = True, time.time() - 30
    db.add_video(path=None, label="OBS", start_ms=int(obs.started_at * 1000), end_ms=None,
                 sync_source="obs", started_by_app=True, pauses=[])
    svc.start()
    try:
        wait(lambda: svc.status()["leftover"])
        svc.leftover("stop")
        wait(lambda: not obs.active)
        wait(lambda: db.videos()[0]["path"])
    finally:
        svc.stop()


def test_obs_problems_never_raise(tmp_path: Path, obs: FakeObs):
    svc, db, recorder = _service(tmp_path, obs, password="wrong")
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "auth")
        svc.on_recording(True)  # not connected: nothing to do, nothing raised
    finally:
        svc.stop()

    obs.fail_start = True
    svc, db, recorder = _service(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
                                 obs)
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        svc.on_recording(True)
        wait(lambda: svc.status()["error"])
        assert "disk space" in svc.status()["error"] and db.videos() == []
    finally:
        svc.stop()


def test_auto_link_off_ignores_recordings_the_app_did_not_start(tmp_path: Path, obs: FakeObs):
    svc, db, _ = _service(tmp_path, obs, auto_link=False)
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        obs.start()
        time.sleep(0.3)
        assert db.videos() == []
    finally:
        svc.stop()


def test_disabled_does_not_connect(tmp_path: Path, obs: FakeObs):
    svc, db, _ = _service(tmp_path, obs, enabled=False)
    svc.start()
    try:
        time.sleep(0.3)
        assert svc.status()["state"] == "off" and obs.conns == []
    finally:
        svc.stop()


def test_a_recording_by_hand_after_obs_restarts_is_not_written_into_the_old_row(
        tmp_path: Path, obs: FakeObs):
    """Review U1: the row the app tracked must be forgotten when the connection drops."""
    svc, db, recorder = _service(tmp_path, obs, auto_link=False)
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        recorder.recording = True
        svc.on_recording(True)
        x = wait(lambda: next(iter(db.videos()), None))
        # OBS crashes and comes back idle; the app's recording stopped meanwhile.
        obs.active = False
        for ws in list(obs.conns):
            ws.close()
        wait(lambda: svc.status()["state"] != "connected")
        recorder.recording = False
        svc.on_recording(False)
        wait(lambda: svc.status()["state"] == "connected", 10)
        time.sleep(0.3)
        obs.start()  # by hand in OBS, auto-link off: not linked at all
        time.sleep(0.3)
        path = obs.stop()
        time.sleep(0.4)
        rows = db.videos()
        assert [r["id"] for r in rows] == [x["id"]]
        assert rows[0]["path"] != path and rows[0]["start_ms"] == x["start_ms"]
    finally:
        svc.stop()


def test_paths_from_obs_are_stored_like_every_other_path(tmp_path: Path, obs: FakeObs):
    """Review U2: OBS's own spelling of a path (forward slashes on Windows) must match the
    file found in a folder or linked by hand, or it shows up twice."""
    svc, db, _ = _service(tmp_path, obs, recording=True)
    svc.start()
    try:
        first = wait(lambda: next(iter(db.videos()), None))
        odd = obs.record_dir / ".." / obs.record_dir.name / "part2.mkv"
        obs.split(odd)
        second = wait(lambda: len(db.videos()) == 2 and db.videos()[1])
        assert second["path"] == str((obs.record_dir / "part2.mkv").resolve())
        assert db.video_by_path(str((obs.record_dir / "part2.mkv").resolve()))
        assert first["id"] != second["id"]
    finally:
        svc.stop()


def test_the_connection_thread_survives_a_failing_reader(tmp_path: Path, obs: FakeObs,
                                                       monkeypatch):
    """Review U4: an error in the reader (e.g. close() racing it) must not kill the
    connection thread; it reconnects."""
    real = ObsConnection.run
    calls = {"n": 0}

    def flaky(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AttributeError("'NoneType' object has no attribute 'recv'")
        return real(self)

    monkeypatch.setattr(ObsConnection, "run", flaky)
    svc, _, _ = _service(tmp_path, obs)
    svc.start()
    try:
        wait(lambda: calls["n"] >= 2, 10)
        wait(lambda: svc.status()["state"] == "connected")
    finally:
        svc.stop()


def test_reader_returns_when_closed_before_it_runs():
    conn = ObsConnection(1, "")
    conn.close()
    conn.run()  # no socket: returns instead of raising
    assert conn.closed


# ---- recording size (plan 19) ----------------------------------------------------------------

def test_gb_per_hour():
    assert gb_per_hour(4.5e9, 3_600_000) == pytest.approx(4.5)
    assert gb_per_hour(1e9, 120_000) == pytest.approx(30.0)
    assert gb_per_hour(1e9, 59_999) is None  # too short to count
    assert gb_per_hour(0, 600_000) is None and gb_per_hour(None, None) is None
    assert gb_per_hour("x", 600_000) is None


def test_live_rate_and_warning(tmp_path: Path, obs: FakeObs):
    svc, db, recorder = _service(tmp_path, obs)
    svc.rate_poll_s = 0.05
    published: list[dict] = []
    orig = svc.bus.publish
    svc.bus.publish = lambda ev: (published.append(ev), orig(ev))  # type: ignore[method-assign]
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        assert svc.status()["rate"] is None and not svc.status()["rateWarning"]
        obs.status_extra = {"outputDuration": 30_000, "outputBytes": 10**9}
        recorder.recording = True
        svc.on_recording(True)
        wait(lambda: svc.status()["recording"])
        time.sleep(0.3)
        assert svc.status()["rate"] is None  # under a minute: no rate yet

        # 20 GB per hour: 10 minutes, 3.333 GB.
        obs.status_extra = {"outputDuration": 600_000, "outputBytes": 3_333_333_333}
        st = wait(lambda: (s := svc.status())["rate"] and s)
        assert st["rate"] == {"gbPerHour": 20.0, "live": True, "seconds": 600}
        assert st["rateWarning"] and st["warnGbPerHour"] == 10
        assert st["sizeGuideUrl"].endswith("#keep-obs-recordings-small")
        assert any(e["obs"]["rate"] for e in published if e.get("type") == "obs")
        n = len(published)
        time.sleep(0.3)  # the same rate again: nothing new to publish
        assert len(published) == n

        svc.config.update({"obs": {"warn_gb_per_hour": 0}})
        assert not svc.status()["rateWarning"]  # 0: never
        svc.config.update({"obs": {"warn_gb_per_hour": 25}})
        assert not svc.status()["rateWarning"]
        svc.config.update({"obs": {"warn_gb_per_hour": 10}})

        # Stopped: OBS's own last sample stays, not the 1-byte file over the row's span.
        recorder.recording = False
        svc.on_recording(False)
        st = wait(lambda: (s := svc.status())["rate"] and not s["rate"]["live"] and s)
        assert st["rate"]["gbPerHour"] == 20.0 and st["rateWarning"]
    finally:
        svc.stop()


def test_recording_started_in_obs_is_measured_without_auto_link(tmp_path: Path, obs: FakeObs):
    svc, db, _ = _service(tmp_path, obs, auto_link=False)
    svc.rate_poll_s = 0.05
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        obs.status_extra = {"outputDuration": 3_600_000, "outputBytes": 4_500_000_000}
        obs.start()
        st = wait(lambda: (s := svc.status())["rate"] and s)
        assert st["rate"]["gbPerHour"] == 4.5 and not st["rateWarning"]
        assert db.videos() == []  # measured, not linked
    finally:
        svc.stop()
        obs.active = False


def test_last_recordings_file_gives_the_rate_when_idle(tmp_path: Path, obs: FakeObs):
    svc, db, _ = _service(tmp_path, obs)
    old = obs.record_dir / "old.mkv"
    old.write_bytes(b"x")
    new = obs.record_dir / "new.mkv"
    with new.open("wb") as f:
        f.truncate(750_000_000)  # sparse: 0.75 GB
    db.add_video(path=str(old), label="OBS", start_ms=0, end_ms=3_600_000, sync_source="obs",
                 approximate=False, started_by_app=True, pauses=[])
    # 15 minutes with a 5 minute pause: 10 minutes recorded, so 4.5 GB per hour (3.0 if the
    # pause were counted).
    db.add_video(path=str(new), label="OBS", start_ms=10_000_000, end_ms=10_900_000,
                 sync_source="obs", approximate=False, started_by_app=True,
                 pauses=[[10_100_000, 10_400_000]])
    # A newer OBS row whose file is gone, and one too short to measure: the next one counts.
    db.add_video(path=str(obs.record_dir / "deleted.mkv"), label="OBS", start_ms=11_000_000,
                 end_ms=12_000_000, sync_source="obs", approximate=False, started_by_app=True,
                 pauses=[])
    short = obs.record_dir / "short.mkv"
    with short.open("wb") as f:
        f.truncate(10**8)
    db.add_video(path=str(short), label="OBS", start_ms=12_000_000, end_ms=12_030_000,
                 sync_source="obs", approximate=False, started_by_app=True, pauses=[])
    # A newer approximate OBS row: its span may be off, so it doesn't count.
    approx = obs.record_dir / "approx.mkv"
    with approx.open("wb") as f:
        f.truncate(10**9)  # 60 GB per hour if it counted
    db.add_video(path=str(approx), label="OBS", start_ms=15_000_000,
                 end_ms=15_060_000, sync_source="obs", approximate=True, started_by_app=True,
                 pauses=[])
    # A newer hand-linked video is not an OBS recording: it doesn't count.
    mine = tmp_path / "mine.mp4"
    mine.write_bytes(b"x" * 10)
    db.add_video(path=str(mine), label="Me", start_ms=20_000_000, end_ms=30_000_000,
                 sync_source="manual", approximate=False, started_by_app=False, pauses=[])
    svc.start()
    try:
        st = wait(lambda: (s := svc.status())["rate"] and s)
        assert st["rate"] == {"gbPerHour": 4.5, "live": False, "seconds": 600}
    finally:
        svc.stop()


def test_finished_file_gives_the_rate_on_stop(tmp_path: Path, obs: FakeObs):
    svc, db, recorder = _service(tmp_path, obs)
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        recorder.recording = True
        svc.on_recording(True)
        row = wait(lambda: next(iter(db.videos()), None))
        # Pretend it ran 20 minutes: move its start back, and make OBS's file 1.5 GB.
        db.update_video(row["id"], start_ms=row["start_ms"] - 1_200_000)
        obs.file_size = 1_500_000_000
        recorder.recording = False
        svc.on_recording(False)
        st = wait(lambda: (s := svc.status())["rate"] and s)
        assert not st["rate"]["live"] and st["rate"]["gbPerHour"] == pytest.approx(4.5, abs=0.1)
    finally:
        svc.stop()


def test_rate_after_reconnect_and_after_a_short_recording(tmp_path: Path, obs: FakeObs):
    """Review F1 and F2: a rate is only ever shown for the recording it was measured on."""
    svc, db, recorder = _service(tmp_path, obs)
    svc.rate_poll_s = 0.05
    svc.start()
    try:
        wait(lambda: svc.status()["state"] == "connected")
        obs.status_extra = {"outputDuration": 600_000, "outputBytes": 3_333_333_333}
        obs.start()  # recording A, started in OBS: 20 GB per hour
        wait(lambda: (r := svc.status()["rate"]) and r["live"])

        # F1: the connection drops; OBS comes back writing recording B (30 s so far).
        obs.status_extra = {"outputDuration": 30_000, "outputBytes": 10**9}
        conn = svc._conn
        assert conn is not None
        conn.close()
        wait(lambda: svc._conn is not None and svc._conn is not conn
             and svc.status()["state"] == "connected" and svc.status()["recording"])
        time.sleep(0.3)
        st = svc.status()
        assert st["rate"] == {"gbPerHour": 20.0, "live": False, "seconds": 600}  # A's, as last
        # The chip shows a warning only for a live rate (ObsStatus.svelte: `big`).

        # F2: B stops before it could be measured (its 1-byte file is no rate either): no rate,
        # rather than A's 20 GB per hour shown as the last recording's.
        obs.stop()
        wait(lambda: not svc.status()["recording"])
        wait(lambda: svc.status()["rate"] is None)

        # A measured recording after that shows again.
        obs.status_extra = {"outputDuration": 3_600_000, "outputBytes": 4_500_000_000}
        obs.start()
        wait(lambda: (r := svc.status()["rate"]) and r["live"] and r["gbPerHour"] == 4.5)
        obs.stop()
        st = wait(lambda: (s := svc.status())["rate"] and not s["rate"]["live"] and s)
        assert st["rate"]["gbPerHour"] == 4.5
    finally:
        svc.stop()
        obs.active = False
