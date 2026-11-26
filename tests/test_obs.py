"""The optional OBS connection, against a fake OBS WebSocket v5 server (plan 17, phase 4)."""

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
from wvw_analyzer.obs import ObsConnection, ObsService, auth_string, check_connection
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
                                "outputDuration": dur})
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
        path.write_bytes(b"x")
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
