"""The in-game overlay payload (/api/overlay) and its contract with the Rust addon."""

import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from factory import zerg
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.api.overlay import SCHEMA
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database

# Shared with `addon/` (the Rust tests parse it), so the two sides can't drift silently.
FIXTURE = Path(__file__).resolve().parents[1] / "addon" / "tests" / "fixtures" / "overlay.json"


def make_client(tmp_path: Path) -> tuple[TestClient, AppState]:
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    return TestClient(create_app(state)), state


def add_fight(state: AppState, sid: int, name: str, **kw: Any) -> int:
    fid = state.db.add_fight(f"/x/{name}.zevtc", sid, 0)
    a = analyze_ei(zerg(10, **kw), name, Settings())
    state.db.save_analysis(fid, a.summary, a.stats, a.notes)
    return fid


def shape(v: Any) -> Any:
    """Keys and value types, recursively (lists by their first item)."""
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    return type(v).__name__


def test_empty_database(tmp_path: Path):
    client, _ = make_client(tmp_path)
    with client:
        p = client.get("/api/overlay").json()
        assert p["schema"] == SCHEMA and p["session"] is None and p["fight"] is None
        assert p["recording"]["active"] is False
        assert client.get("/api/status").json()["app"] == "wvw-analyzer"


def test_latest_fight_browsing_and_session(tmp_path: Path):
    client, state = make_client(tmp_path)
    with client:
        sid = state.db.create_session("Raid", "recording")
        first = add_fight(state, sid, "a", downs_at=[30, 30.5, 31, 31.5])
        second = add_fight(state, sid, "b")
        state.db.save_debrief(second, 'Result: win\n\n- Why: x\n\n{"unverified": ["12"]}')

        p = client.get("/api/overlay").json()
        f = p["fight"]
        # Same start time in both synthetic fights -> newest id first.
        assert f["id"] == second and f["nextId"] is None and f["prevId"] == first
        assert f["index"] == 2 and f["count"] == 2
        assert f["title"].startswith("20:00") and "Seared Borderlands" in f["title"]
        assert f["resultLine"].startswith("Result:")
        assert f["debrief"] == ["Result: win", "- Why: x"] and f["debriefUnverified"] == 1

        older = client.get("/api/overlay", params={"fight": first}).json()["fight"]
        assert older["id"] == first and older["nextId"] == second and older["index"] == 1
        assert {"severity", "title", "short", "fix"} <= older["issues"][0].keys()
        assert older["debrief"] == []

        s = p["session"]
        assert s["name"] == "Raid" and s["fights"] == 2 and s["record"]
        assert client.get("/api/overlay", params={"fight": 9999}).status_code == 404


def test_latest_follows_the_current_session_while_browsing_an_older_one(tmp_path: Path):
    client, state = make_client(tmp_path)
    with client:
        old = state.db.create_session("Monday", "recording")
        a1 = add_fight(state, old, "a1")
        a2 = add_fight(state, old, "a2")
        p = client.get("/api/overlay").json()
        assert p["latest"]["id"] == a2 and p["latest"]["addedAt"]

        # A new session starts (recording) while the player looks at Monday's newest fight.
        state.recorder.session_id = new = state.db.create_session("Tuesday", "recording")
        browsing = client.get("/api/overlay", params={"fight": a2}).json()
        assert browsing["session"]["name"] == "Monday" and browsing["fight"]["nextId"] is None
        assert browsing["latest"] is None  # Tuesday has no fight yet
        b1 = add_fight(state, new, "b1")
        browsing = client.get("/api/overlay", params={"fight": a1}).json()
        assert browsing["latest"]["id"] == b1  # so the addon offers "Latest" and auto-shows
        assert browsing["session"]["latestId"] == a2
        state.recorder.session_id = None


def test_etag_returns_304_until_something_changes(tmp_path: Path):
    client, state = make_client(tmp_path)
    with client:
        sid = state.db.create_session("Raid", "recording")
        add_fight(state, sid, "a")
        r = client.get("/api/overlay")
        etag = r.headers["etag"]
        assert client.get("/api/overlay", headers={"If-None-Match": etag}).status_code == 304
        add_fight(state, sid, "b")
        r2 = client.get("/api/overlay", headers={"If-None-Match": etag})
        assert r2.status_code == 200 and r2.headers["etag"] != etag


def test_native_client_can_toggle_recording_but_websites_cannot(tmp_path: Path):
    client, _ = make_client(tmp_path)
    with client:
        # The addon sends no Origin header: allowed through (fails only on the missing folder).
        client.put("/api/settings", json={"log_dir": str(tmp_path / "missing")})
        assert client.post("/api/recording/start", json={}).status_code == 400
        assert client.post("/api/recording/stop").status_code == 200
        evil = client.post("/api/recording/stop", headers={"Origin": "https://example.com"})
        assert evil.status_code == 403
        assert client.get("/api/overlay", headers={"Host": "evil.example"}).status_code == 403


def test_contract_fixture_matches_payload(tmp_path: Path):
    client, state = make_client(tmp_path)
    with client:
        sid = state.db.create_session("Raid", "recording")
        add_fight(state, sid, "a", downs_at=[30, 30.5, 31, 31.5])
        fid = add_fight(state, sid, "b", downs_at=[20, 21, 40, 41])
        state.db.save_debrief(fid, "Result: loss\n- Why: stab ran out\n- Went well: strips")
        payload = client.get("/api/overlay").json()
    assert payload["fight"]["issues"] and payload["fight"]["positives"] is not None
    if os.environ.get("UPDATE_FIXTURES") or not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(payload, indent=2) + "\n")
    stored = json.loads(FIXTURE.read_text())
    assert shape(stored) == shape(payload), "run with UPDATE_FIXTURES=1 and update the addon"
