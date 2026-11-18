"""Regression tests for the code-review fixes (settings reset, imports, security, versioning)."""

import io
import struct
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from factory import zerg
from wvw_analyzer.analysis import ANALYZER_VERSION, analysis_job, analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.events import EventBus
from wvw_analyzer.ingest.recorder import Recorder
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database


def _log(species: int) -> bytes:
    raw = b"EVTC20261117\x00" + struct.pack("<H", species) + b"\x00" * 65
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("log.evtc", raw)
    return buf.getvalue()


class FakeProcessor:
    def __init__(self):
        self.queued: list[int] = []

    def enqueue(self, fight_id: int, reparse: bool = False, cancellable: bool = False) -> None:
        self.queued.append(fight_id)


def test_detector_overrides_can_be_reset(tmp_path: Path):
    cfg = ConfigStore(tmp_path / "config.yaml")
    cfg.update({"detectors": {"stab_gap_deaths": {"enabled": False, "min_downs": 9}}})
    cfg.update({"llm": {"threads": 3}})  # unrelated save keeps the override
    assert cfg.settings.detectors["stab_gap_deaths"]["enabled"] is False
    cfg.update({"detectors": {}})  # what the UI sends after re-enable + reset
    assert cfg.settings.detectors == {}


def test_manual_stop_suppresses_auto_record(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    cfg = ConfigStore(tmp_path / "config.yaml")
    cfg.update({"log_dir": str(logs)})
    rec = Recorder(Database(tmp_path / "t.db"), cfg, EventBus(), FakeProcessor())  # type: ignore[arg-type]
    rec._game_running = True
    rec.start(auto=True)
    rec.stop()  # user presses Stop while the game is running
    assert rec._auto_suppressed is True
    rec.start(auto=True)
    rec.stop(manual=False)  # the watcher stopping it on game exit is not a manual stop
    assert rec._auto_suppressed is True  # still suppressed until the watcher sees the game gone


def test_date_range_import_skips_pve_and_previews(tmp_path: Path):
    root = tmp_path / "arcdps.cbtlogs"
    (root / "WvW (1)").mkdir(parents=True)
    (root / "Vale Guardian (15438)").mkdir()
    for i in range(3):
        (root / "WvW (1)" / f"20261117-20000{i}.zevtc").write_bytes(_log(1))
    (root / "Vale Guardian (15438)" / "20261117-190000.zevtc").write_bytes(_log(15438))
    cfg = ConfigStore(tmp_path / "config.yaml")
    cfg.update({"log_dir": str(root)})
    db = Database(tmp_path / "t.db")
    proc = FakeProcessor()
    rec = Recorder(db, cfg, EventBus(), proc)  # type: ignore[arg-type]
    preview = rec.preview_import()
    assert (preview["new"], preview["notWvw"], preview["days"]) == (3, 1, 1)
    assert db.fights() == []  # preview changes nothing
    result = rec.import_logs()
    assert (result["added"], result["notWvw"]) == (3, 1) and len(proc.queued) == 3
    again = rec.preview_import()
    assert (again["new"], again["alreadyKnown"]) == (0, 3)


def test_stale_fights_and_debrief_scope(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    a = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "a", Settings())
    rec_sid = db.create_session("Raid", "recording")
    imp_sid = db.create_session("Import", "import")
    f_rec = db.add_fight("/x/a.zevtc", rec_sid, 0)
    f_imp = db.add_fight("/x/b.zevtc", imp_sid, 0)
    db.save_analysis(f_rec, a.summary, a.stats, a.notes)
    old = {**a.summary, "analyzerVersion": ANALYZER_VERSION - 1}
    db.save_analysis(f_imp, old, a.stats, a.notes)
    assert db.stale_fight_ids(ANALYZER_VERSION) == [f_imp]
    assert db.fights_needing_debrief() == [f_rec]  # imported history is not auto-debriefed
    db.save_debrief(f_rec, "done")
    assert db.fights_needing_debrief() == []


def test_analysis_job_returns_plain_data(tmp_path: Path):
    import gzip
    import json

    path = tmp_path / "x_detailed_wvw.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(zerg(10, downs_at=[30, 30.5, 31, 31.5]), fh)
    out = analysis_job(str(path), Settings().model_dump(mode="json"))
    assert out["kind"] == "done" and out["notes"]["issues"]
    small = tmp_path / "y_detailed_wvw.json.gz"
    with gzip.open(small, "wt", encoding="utf-8") as fh:
        json.dump(zerg(2, enemies=1), fh)
    assert analysis_job(str(small), Settings().model_dump(mode="json"))["kind"] == "skipped"


def test_api_rejects_foreign_hosts_and_origins(tmp_path: Path):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    with TestClient(create_app(state)) as client:
        assert client.get("/api/status").status_code == 200
        assert client.get("/api/status", headers={"host": "evil.example.com"}).status_code == 403
        assert client.post("/api/queue/cancel",
                           headers={"origin": "https://example.com"}).status_code == 403
        assert client.post("/api/queue/cancel",
                           headers={"origin": "http://127.0.0.1:8765"}).status_code == 200
        assert client.post("/api/queue/cancel", headers={"origin": "null"}).status_code == 403
        try:
            with client.websocket_connect("/ws", headers={"origin": "https://example.com"}) as ws:
                ws.receive_json()
            raise AssertionError("foreign origin websocket was accepted")
        except WebSocketDisconnect as e:
            assert e.code == 1008
        with client.websocket_connect("/ws", headers={"origin": "http://localhost:5173"}) as ws:
            assert ws.receive_json()["type"] == "hello"
