import time
from pathlib import Path

from factory import zerg
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.events import EventBus
from wvw_analyzer.ingest.recorder import Recorder
from wvw_analyzer.llm.manager import unverified_numbers
from wvw_analyzer.metrics.aggregate import aggregate_session
from wvw_analyzer.notes.templates import _format
from wvw_analyzer.store.db import Database


class FakeProcessor:
    def __init__(self):
        self.queued: list[int] = []

    def enqueue(self, fight_id: int, reparse: bool = False, cancellable: bool = False) -> None:
        self.queued.append(fight_id)


def test_db_roundtrip_and_session_aggregate(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    sid = db.create_session("Raid", "recording")
    fid = db.add_fight("/logs/a.zevtc", sid, 1.0)
    assert fid and db.add_fight("/logs/a.zevtc", sid, 1.0) is None  # duplicate path
    a = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "a", Settings())
    db.save_analysis(fid, a.summary, a.stats, a.notes)
    row = db.fight(fid)
    assert row["status"] == "done" and row["summary"]["map"] == "Seared Borderlands"
    assert db.analysis(fid)["stats"]["players"][0]["name"]
    agg = aggregate_session(db.session_analyses(sid))
    assert agg["totals"]["fights"] == 1 and agg["leaderboards"]["damage"]["rows"]
    assert agg["recurringIssues"]


def test_recorder_waits_for_complete_log(tmp_path: Path):
    logs = tmp_path / "arcdps.cbtlogs" / "WvW (1)"
    logs.mkdir(parents=True)
    cfg = ConfigStore(tmp_path / "config.yaml")
    cfg.update({"log_dir": str(tmp_path / "arcdps.cbtlogs"),
                "recording": {"poll_interval_s": 0.1, "stable_s": 0.5}})
    db = Database(tmp_path / "t.db")
    old = logs / "20261117-190000.zevtc"
    old.write_bytes(b"old")
    import os

    os.utime(old, (time.time() - 3600, time.time() - 3600))  # before recording started
    proc = FakeProcessor()
    rec = Recorder(db, cfg, EventBus(), proc)  # type: ignore[arg-type]
    rec.start()
    try:
        new = logs / "20261117-200000.zevtc"
        with open(new, "wb") as fh:  # simulate arcdps writing in chunks
            for _ in range(4):
                fh.write(b"x" * 1000)
                fh.flush()
                time.sleep(0.2)
                assert proc.queued == []
        deadline = time.time() + 5
        while not proc.queued and time.time() < deadline:
            time.sleep(0.1)
        assert len(proc.queued) == 1
        assert db.fight(proc.queued[0])["log_name"] == new.name
    finally:
        rec.stop()
    assert db.session(rec.state()["sessionId"] or 1)["ended_at"]


def test_import_groups_by_day(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    for name in ["20261115-200000.zevtc", "20261115-210000.zevtc", "20261117-200000.zevtc"]:
        (logs / name).write_bytes(b"x")
    cfg = ConfigStore(tmp_path / "config.yaml")
    db = Database(tmp_path / "t.db")
    proc = FakeProcessor()
    rec = Recorder(db, cfg, EventBus(), proc)  # type: ignore[arg-type]
    first = rec.import_logs(folder=logs)
    assert (first["added"], first["alreadyKnown"]) == (3, 0) and len(first["fightIds"]) == 3
    again = rec.import_logs(folder=logs)
    assert (again["added"], again["alreadyKnown"]) == (0, 3)
    assert sorted(again["fightIds"]) == sorted(first["fightIds"])
    names = sorted(s["name"] for s in db.sessions())
    assert names == ["Import 2026-11-15", "Import 2026-11-17"]


def test_template_formatting():
    out = _format("{a} {b} {missing} {c}", {"a": 175657, "b": 3, "c": 2_500_000})
    assert out == "176k 3 ? 2.5M"


def test_unverified_numbers():
    src = '{"deaths": 22, "coverage": 35, "dmg": "1.2M"}'
    assert unverified_numbers("22 deaths at 35% coverage, 3 bombs", src) == []
    assert unverified_numbers("47 deaths", src) == ["47"]


def test_deleting_fights_removes_owned_files_only(tmp_path: Path):
    from wvw_analyzer.store.files import cleanup_orphans, remove_fight_files

    db = Database(tmp_path / "t.db")
    (tmp_path / "ei").mkdir()
    (tmp_path / "uploads").mkdir()
    original = tmp_path / "arcdps" / "20261117-200000.zevtc"
    original.parent.mkdir()
    original.write_bytes(b"log")
    upload = tmp_path / "uploads" / "20261117-210000.zevtc"
    upload.write_bytes(b"log")
    sid = db.create_session("Raid", "import")
    f1 = db.add_fight(str(original), sid, 0)
    f2 = db.add_fight(str(upload), sid, 0)
    ei1, ei2 = tmp_path / "ei" / "a.json.gz", tmp_path / "ei" / "b.json.gz"
    for f, ei in ((f1, ei1), (f2, ei2)):
        ei.write_bytes(b"{}")
        db.set_ei_json(f, str(ei))

    remove_fight_files(db.delete_fight(f1), db)
    assert not ei1.exists() and original.exists()  # arcdps log is never deleted
    remove_fight_files(db.delete_session(sid), db)
    assert not ei2.exists() and not upload.exists()

    orphan = tmp_path / "ei" / "orphan.json.gz"
    orphan.write_bytes(b"{}")
    assert cleanup_orphans(db, min_age_s=0) == 1 and not orphan.exists()
    assert (tmp_path / "arcdps").exists() and original.exists()
