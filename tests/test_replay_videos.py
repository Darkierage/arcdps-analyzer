"""Combat replay, its cache and cleanup, linked videos and their API (plan 18)."""

from __future__ import annotations

import gzip
import json
import os
import time
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from factory import zerg
from wvw_analyzer import tools
from wvw_analyzer import videos as vid
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.replay import build_replay, cache_path, replay_gz
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database
from wvw_analyzer.store.files import cleanup_orphans, remove_fight_files


def _client(tmp_path: Path) -> tuple[TestClient, AppState]:
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    state.processor.use_worker = False
    return TestClient(create_app(state)), state


def _fight_with_json(state: AppState, tmp_path: Path, doc: dict) -> tuple[int, Path]:
    ei = tmp_path / "ei"
    ei.mkdir(exist_ok=True)
    path = ei / f"{len(list(ei.iterdir()))}_detailed_wvw_kill.json.gz"
    path.write_bytes(gzip.compress(json.dumps(doc).encode()))
    sid = state.db.create_session("Raid", "recording")
    fid = state.db.add_fight(str(tmp_path / f"{path.stem}.zevtc"), sid, 0)
    a = analyze_ei(doc, "a", Settings())
    state.db.save_analysis(fid, a.summary, a.stats, a.notes)
    state.db.set_ei_json(fid, str(path))
    return fid, path


def _local_start(dt: datetime) -> str:
    """A fight start in EI's format for a local wall-clock time (tests run in any time zone)."""
    s = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    return s[:-2] + ":" + s[-2:]


# ---- replay ---------------------------------------------------------------------------------
def test_build_replay_shapes_and_intervals():
    doc = zerg(4, downs_at=[10, 20], enemies=3)
    r = build_replay(doc)
    kinds = [a["kind"] for a in r["actors"]]
    assert kinds.count("squad") == 4 and kinds.count("enemy") == 3
    a0 = r["actors"][0]
    assert a0["commander"] is True and a0["group"] == 1
    assert len(a0["p"]) % 2 == 0 and a0["p"][0] == 0.0
    # Downs and deaths in ms; the int64 "open end" of a disconnect is clipped to the fight.
    assert a0["down"] == [[10_000, 12_000]] and a0["dead"] == [[12_000, 60_000]]
    assert all(0 <= x <= 60_000 for iv in a0["dc"] for x in iv)
    enemy = next(a for a in r["actors"] if a["kind"] == "enemy")
    assert enemy["name"] == "Scourge" and "account" not in enemy  # anonymized "<spec> pl-1234"
    assert r["map"] == {"key": None, "hasImage": False}
    assert r["start"] == "2026-11-17 20:00:00 +01:00" and r["durationMs"] == 60_000


def test_replay_map_key_from_elite_insights_url():
    doc = zerg(3)
    doc["combatReplayMetaData"]["maps"] = [{"url": tools.MAP_IMAGES["ebg"][0]}]
    assert build_replay(doc)["map"] == {"key": "ebg", "hasImage": True}
    doc["combatReplayMetaData"]["maps"] = [{"url": "https://example.invalid/new.png"}]
    assert build_replay(doc)["map"] == {"key": None, "hasImage": True}


def test_replay_cache_is_reused_and_rebuilt_when_the_json_changes(tmp_path: Path):
    src = tmp_path / "x_detailed_wvw_kill.json.gz"
    src.write_bytes(gzip.compress(json.dumps(zerg(3)).encode()))
    calls = []

    def build(p: str) -> dict:
        calls.append(p)
        return build_replay(json.loads(gzip.decompress(Path(p).read_bytes())))

    first = replay_gz(src, build)
    assert cache_path(src).name == "x_detailed_wvw_kill.replay.json.gz"
    assert replay_gz(src, build) == first and len(calls) == 1
    # A re-parse rewrites the EI JSON: the cache no longer matches it.
    src.write_bytes(gzip.compress(json.dumps(zerg(5)).encode()))
    os.utime(src, (time.time() + 5, time.time() + 5))
    again = json.loads(gzip.decompress(replay_gz(src, build)))
    assert len(calls) == 2 and sum(a["kind"] == "squad" for a in again["actors"]) == 5


def test_replay_api_and_cache_cleanup(tmp_path: Path):
    client, state = _client(tmp_path)
    with client:
        fid, ei = _fight_with_json(state, tmp_path, zerg(6))
        r = client.get(f"/api/fights/{fid}/replay")
        assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
        assert len(r.json()["actors"]) == 6 + 20
        cache = cache_path(ei)
        assert cache.is_file()
        assert client.get("/api/fights/999/replay").status_code == 404

        # The startup cleanup keeps a cache whose EI JSON is used (it used to delete every
        # unreferenced .json.gz in ei/)...
        old = time.time() - 3600
        os.utime(cache, (old, old))
        cleanup_orphans(state.db)
        assert cache.is_file() and ei.is_file()
        # ...and an orphan cache (its fight is gone) goes.
        orphan = tmp_path / "ei" / "gone_detailed_wvw_kill.replay.json.gz"
        orphan.write_bytes(b"x")
        os.utime(orphan, (old, old))
        cleanup_orphans(state.db)
        assert not orphan.exists() and cache.is_file()

        # Deleting the fight removes its EI JSON and the replay made from it.
        remove_fight_files(state.db.delete_fight(fid), state.db)
        assert not ei.exists() and not cache.exists()


def test_replay_maps_route_serves_only_downloaded_pinned_images(tmp_path: Path, monkeypatch):
    # paths.data_dir() is cached per process: point the maps folder itself at the temp dir.
    monkeypatch.setattr(tools, "maps_dir", lambda: tmp_path / "maps")
    client, _ = _client(tmp_path)
    with client:
        assert client.get("/api/replay-maps").json()["installed"] is False
        assert client.get("/api/replay-maps/ebg").status_code == 404
        d = tools.maps_dir()
        d.mkdir(parents=True)
        (d / "ebg.png").write_bytes(b"\x89PNG")
        assert client.get("/api/replay-maps/ebg").status_code == 200
        assert client.get("/api/replay-maps/..%2Fconfig.yaml").status_code == 404
        assert client.get("/api/replay-maps").json()["maps"]["ebg"] is True


# ---- videos ---------------------------------------------------------------------------------
def test_recorder_file_names_give_the_local_start_time():
    want = int(datetime(2026, 11, 10, 18, 11, 50).timestamp() * 1000)
    for name in ("2026-11-10 18-11-50.mkv",  # OBS default
                 "Guild Wars 2 2026.11.10 - 18.11.50.02.DVR.mp4",  # NVIDIA
                 "Guild Wars 2 2026-11-10 18-11-50.mp4",  # Game Bar
                 "raid_2026-11-10_18-11-50.mp4"):
        assert vid.name_time_ms(name) == want, name
    assert vid.name_time_ms("my fight.mp4") is None
    assert vid.name_time_ms("2026-13-40 99-99-99.mp4") is None


def test_fight_start_and_coverage_with_offset():
    start = vid.parse_fight_start("2026-11-17 20:00:00 +01:00")
    assert start == int(datetime.fromisoformat("2026-11-17T20:00:00+01:00").timestamp() * 1000)
    assert vid.parse_fight_start("2026-11-17 20:00:00 +01") == start
    assert vid.parse_fight_start(None) is None
    span = (start, start + 60_000)
    v = {"start_ms": start + 70_000, "end_ms": start + 200_000, "offset_ms": 0}
    assert not vid.covers(v, span)
    # +15 s: each moment shows 15 s later in the file, so the file now starts before the end.
    assert vid.covers({**v, "offset_ms": 15_000}, span)
    assert vid.covers({"start_ms": start - 10, "end_ms": None, "offset_ms": 0}, span)
    # Review U3: a row whose length is unknown (end = start) covers no fight, even one
    # running at its start.
    assert not vid.covers({"start_ms": start + 1000, "end_ms": start + 1000, "offset_ms": 0}, span)


def _setup_video_fight(state: AppState, tmp_path: Path) -> tuple[int, int, Path]:
    fid, _ = _fight_with_json(state, tmp_path, zerg(5))
    start = datetime(2026, 11, 17, 20, 0, 0)
    state.db._exec("UPDATE fights SET fight_start=? WHERE id=?", (_local_start(start), fid))
    folder = tmp_path / "Videos"
    folder.mkdir()
    video = folder / "2026-11-17 19-58-00.mp4"  # started 2 min before the fight
    video.write_bytes(b"\x00" * 4096)
    end = (start.timestamp() + 600)  # written until 10 min after it
    os.utime(video, (end, end))
    sid = state.db.fight(fid)["session_id"]
    return fid, sid, video


def test_video_api_link_cover_sync_and_serve(tmp_path: Path):
    client, state = _client(tmp_path)
    with client:
        fid, sid, video = _setup_video_fight(state, tmp_path)
        client.put("/api/settings", json={"videos": {"folders": [str(video.parent)]}})

        # Found in the recording folder before it is linked.
        sv = client.get(f"/api/sessions/{sid}/videos").json()
        assert [s["name"] for s in sv["suggestions"]] == [video.name]
        assert sv["suggestions"][0]["fightIds"] == [fid] and sv["videos"] == []

        bad = tmp_path / "notes.txt"
        bad.write_text("x")
        assert client.post("/api/videos", json={"path": str(bad)}).status_code == 400
        missing = {"path": str(tmp_path / "nope.mp4")}
        assert client.post("/api/videos", json=missing).status_code == 400
        row = client.post("/api/videos", json={"path": str(video), "label": "Me"}).json()
        assert row["syncSource"] == "filename" and row["label"] == "Me" and row["exists"]
        assert client.post("/api/videos", json={"path": str(video)}).status_code == 409

        fv = client.get(f"/api/fights/{fid}/videos").json()
        assert [v["id"] for v in fv["videos"]] == [row["id"]] and fv["leadInS"] == 3
        # The fight's second 0 is 120 s into the file.
        assert (fv["fightStartMs"] - row["startMs"]) == 120_000
        assert client.get("/api/fights").json()[0]["hasVideo"] is True
        assert client.get(f"/api/sessions/{sid}").json()["fights"][0]["hasVideo"] is True
        sv = client.get(f"/api/sessions/{sid}/videos").json()
        assert sv["suggestions"] == [] and sv["videos"][0]["fightIds"] == [fid]

        # A nudge / Sync here is by hand from then on; the length from the page sets the end.
        p = client.patch(f"/api/videos/{row['id']}", json={"offsetMs": 1500, "manual": True}).json()
        assert p["offsetMs"] == 1500 and p["syncSource"] == "manual" and not p["approximate"]
        p = client.patch(f"/api/videos/{row['id']}", json={"durationMs": 300_000}).json()
        assert p["endMs"] == p["startMs"] + 300_000

        # Served by id, with Range support so the page can seek.
        r = client.get(f"/api/videos/{row['id']}/file", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and len(r.content) == 100
        assert r.headers["content-type"] == "video/mp4"
        # A reused id may point at another file: the browser must revalidate its copy.
        assert r.headers["cache-control"] == "no-cache"
        assert client.get("/api/videos/999/file").status_code == 404

        # Unlinking keeps the file.
        assert client.delete(f"/api/videos/{row['id']}").json() == {"ok": True}
        assert video.is_file() and client.get(f"/api/fights/{fid}/videos").json()["videos"] == []


def test_video_without_a_time_in_its_name_starts_one_length_before_its_last_write(tmp_path):
    client, state = _client(tmp_path)
    with client:
        f = tmp_path / "my clip.webm"
        f.write_bytes(b"x")
        end = time.time() - 100
        os.utime(f, (end, end))
        row = client.post("/api/videos", json={"path": str(f)}).json()
        assert row["syncSource"] == "filetime"
        if row["approximate"]:  # no creation time on this system (Linux)
            p = client.patch(f"/api/videos/{row['id']}", json={"durationMs": 30_000}).json()
            assert p["startMs"] == p["endMs"] - 30_000


def test_settings_never_return_the_obs_password(tmp_path: Path):
    client, state = _client(tmp_path)
    with client:
        r = client.put("/api/settings", json={"obs": {"enabled": False, "password": "s3cret"}})
        obs = r.json()["settings"]["obs"]
        assert "password" not in obs and obs["password_set"] is True
        assert "s3cret" not in client.get("/api/settings").text
        # The page saves the whole form back without the password: the stored one stays.
        form = client.get("/api/settings").json()["settings"]
        client.put("/api/settings", json=form)
        assert state.config.settings.obs.password == "s3cret"
        client.put("/api/settings", json={"obs": {"password": ""}})
        assert state.config.settings.obs.password == ""
