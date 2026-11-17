from pathlib import Path

from fastapi.testclient import TestClient

from factory import zerg
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database


def make_client(tmp_path: Path) -> tuple[TestClient, AppState]:
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    return TestClient(create_app(state)), state


def test_status_settings_and_fight(tmp_path: Path):
    client, state = make_client(tmp_path)
    with client:
        assert client.get("/api/status").json()["queue"]["pending"] == 0
        s = client.get("/api/settings").json()
        assert any(d["name"] == "stab_gap_deaths" for d in s["detectors"])
        r = client.put("/api/settings", json={"filters": {"min_enemies": 7}})
        assert r.json()["settings"]["filters"]["min_enemies"] == 7

        sid = state.db.create_session("Raid", "recording")
        fid = state.db.add_fight("/x/a.zevtc", sid, 0)
        a = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "a", Settings())
        state.db.save_analysis(fid, a.summary, a.stats, a.notes)

        fights = client.get("/api/fights").json()
        assert fights[0]["id"] == fid and fights[0]["summary"]["topIssue"]
        detail = client.get(f"/api/fights/{fid}").json()
        assert detail["notes"]["issues"] and detail["stats"]["columns"]
        sess = client.get(f"/api/sessions/{sid}").json()
        assert sess["aggregate"]["totals"]["fights"] == 1
        assert client.get("/api/fights/9999").status_code == 404
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"


def test_recording_needs_log_dir(tmp_path: Path):
    client, state = make_client(tmp_path)
    with client:
        client.put("/api/settings", json={"log_dir": str(tmp_path / "missing")})
        r = client.post("/api/recording/start", json={})
        assert r.status_code == 400


def test_upload_single_log(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WVW_DATA_DIR", str(tmp_path / "data"))
    from wvw_analyzer import paths

    paths.data_dir.cache_clear()
    logs = tmp_path / "cbtlogs" / "WvW (1)"
    logs.mkdir(parents=True)
    original = logs / "20261117-200000.zevtc"
    original.write_bytes(b"arcdps")
    client, state = make_client(tmp_path)
    # Don't run Elite Insights.
    state.processor.enqueue = lambda fid, reparse=False, cancellable=False: None
    with client:
        client.put("/api/settings", json={"log_dir": str(tmp_path / "cbtlogs")})
        # Same file as in the log folder -> original path is used, no copy.
        r = client.post("/api/import/upload", params={"filename": original.name},
                        content=b"arcdps").json()
        assert r["added"] == 1 and r["path"] == str(original) and len(r["fightIds"]) == 1
        again = client.post("/api/import/upload", params={"filename": original.name},
                            content=b"arcdps").json()
        assert again["added"] == 0 and again["fightIds"] == r["fightIds"]
        # A log from elsewhere is stored under data/uploads.
        other = client.post("/api/import/upload", params={"filename": "20261118-010101.zevtc"},
                            content=b"other").json()
        assert other["added"] == 1 and "uploads" in other["path"]
        bad = client.post("/api/import/upload", params={"filename": "notes.txt"}, content=b"x")
        assert bad.status_code == 400
    paths.data_dir.cache_clear()


def _evtc(species: int, zipped: bool = True) -> bytes:
    import io
    import struct
    import zipfile

    raw = b"EVTC20261117\x00" + struct.pack("<H", species) + b"\x00" + b"\x00" * 64
    if not zipped:
        return raw
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("log.evtc", raw)
    return buf.getvalue()


def test_evtc_header_detection():
    from wvw_analyzer.ingest.evtc import is_wvw_log, species_id

    assert species_id(_evtc(1)) == 1 and is_wvw_log(_evtc(1)) is True
    assert is_wvw_log(_evtc(16199)) is False  # golem
    assert is_wvw_log(_evtc(1, zipped=False)) is True
    assert is_wvw_log(b"garbage") is None  # unreadable -> let Elite Insights decide


def test_check_non_wvw_upload_and_cancel(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WVW_DATA_DIR", str(tmp_path / "data"))
    from wvw_analyzer import paths

    paths.data_dir.cache_clear()
    client, state = make_client(tmp_path)
    queued: list[int] = []
    with client:
        state.processor._q.put = lambda item: queued.append(item[0])  # keep jobs from running
        client.put("/api/settings", json={"log_dir": str(tmp_path / "none")})
        pve = client.post("/api/import/upload", params={"filename": "20261117-190000.zevtc"},
                          content=_evtc(16199)).json()
        assert pve["notWvw"] == 1 and pve["added"] == 0
        ids = []
        for i in range(3):
            r = client.post("/api/import/upload", params={"filename": f"20261117-20000{i}.zevtc"},
                            content=_evtc(1)).json()
            ids += r["fightIds"]
        known = client.post("/api/import/check",
                            json={"names": ["20261117-200000.zevtc", "new.zevtc"]}).json()
        assert known["known"] == {"20261117-200000.zevtc": ids[0]}
        assert client.get("/api/status").json()["queue"]["cancellable"] == 3
        assert client.post("/api/queue/cancel").json() == {"cancelled": 3}
        assert client.get("/api/fights", params={"include_skipped": True}).json() == []
        assert client.get("/api/sessions").json() == []  # empty import session removed
        # cancelled logs can be imported again
        again = client.post("/api/import/upload", params={"filename": "20261117-200000.zevtc"},
                            content=_evtc(1)).json()
        assert again["added"] == 1
    paths.data_dir.cache_clear()
