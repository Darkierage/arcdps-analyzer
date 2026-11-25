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


def test_result_block_facts_and_strip(tmp_path: Path):
    client, state = make_client(tmp_path)
    with client:
        sid = state.db.create_session("Raid", "recording")
        lost = add_fight(state, sid, "a", downs_at=[30, 30.5, 31, 31.5])
        newest = add_fight(state, sid, "b")
        p = client.get("/api/overlay", params={"fight": lost}).json()
        f = p["fight"]
        # The old fields stay for older addons.
        assert f["title"] and f["resultLine"].startswith("Result: loss")
        assert f["badge"] == "LOSS" and f["heading"] == "Seared Borderlands"
        assert f["meta"] == "20:00 · 1:00 long"
        assert [(x["label"], x["value"], x["tone"]) for x in f["facts"]] == [
            ("Kills", "0", "good"), ("Deaths", "4", "bad"), ("Squad", "10", ""),
            ("Enemies", "20", "")]
        assert f["headline"] == "0 kills for 4 deaths" and f["numbers"] == "10 vs 20"
        assert f["issuesTitle"] == "Why this fight was lost"
        assert f["moreCount"] == 0
        strip = p["session"]["strip"]
        assert [x["id"] for x in strip] == [lost, newest]  # oldest first
        assert strip[0] == {"id": lost, "result": "loss", "letter": "L"}


def test_gvg_facts_count_only_round_kills(tmp_path: Path):
    from test_gvg import _round_with_left_enemy_downs

    client, state = make_client(tmp_path)
    with client:
        sid = state.db.create_session("GvG", "recording")
        fid = state.db.add_fight("/x/g.zevtc", sid, 0)
        a = analyze_ei(_round_with_left_enemy_downs(), "g", Settings(), mode="gvg")
        state.db.save_analysis(fid, a.summary, a.stats, a.notes)
        f = client.get("/api/overlay").json()["fight"]
        s = a.summary
        assert f["badge"] == s["result"].upper()  # one round: no score
        labels = [x["label"] for x in f["facts"]]
        assert labels == ["Rounds", "Kills", "Deaths", "Players"]
        kills = s["enemyDeaths"] - s["enemyDeathsLate"]
        assert f["facts"][1]["value"] == str(kills)
        assert f["facts"][3]["value"] == f"{s['squadInFight']} vs {s['enemyCount']}"
        assert f["meta"].endswith(f"{overlay_mmss(s['fightS'])} long")


def overlay_mmss(seconds: float) -> str:
    from wvw_analyzer.api.overlay import _mmss

    return _mmss(seconds)


def test_session_problems_carry_their_worst_severity(tmp_path: Path):
    from wvw_analyzer.api.overlay import _worst
    from wvw_analyzer.metrics.aggregate import aggregate_session

    assert _worst([{"severity": "minor"}, {"severity": "critical"}, {"severity": "major"}],
                  "minor") == "critical"
    assert _worst([], "major") == "major"
    client, state = make_client(tmp_path)
    with client:
        sid = state.db.create_session("Raid", "recording")
        add_fight(state, sid, "a", downs_at=[30, 30.5, 31, 31.5])
        add_fight(state, sid, "b", downs_at=[20, 21, 40, 41])
        add_fight(state, sid, "c")
        problems = client.get("/api/overlay").json()["session"]["problems"]
        agg = aggregate_session(state.db.session_analyses(sid, players=False), detail=False)
        for p, r in zip(problems, agg["recurringIssues"], strict=False):
            assert p["title"] == r["title"]
            assert p["severity"] == _worst(r["occurrences"], r["severity"])


def test_empty_sessions_dont_hide_the_latest_fights(tmp_path: Path):
    # Two recordings started and stopped without a fight, at 02:05 on the day of a raid that
    # ran until the evening: the overlay showed the empty one (its ISO start sorted above the
    # fights' times as text), so it had no data.
    client, state = make_client(tmp_path)
    with client:
        raid = state.db.create_session("Raid", "recording")
        add_fight(state, raid, "a")
        state.db.end_session(raid)
        state.db._exec("UPDATE fights SET fight_start='2026-11-17 20:00:00 +01:00'")
        for _ in range(2):
            empty = state.db.create_session("Empty", "recording")
            state.db.end_session(empty)
            state.db._exec("UPDATE sessions SET started_at='2026-11-17T02:05:00' WHERE id=?",
                           (empty,))
        assert state.db.sessions()[0]["id"] == raid  # 20:00 is later than 02:05
        assert client.get("/api/overlay").json()["session"]["id"] == raid
        # An empty session that really is newer still sorts first, but the overlay skips it.
        newer = state.db.create_session("Later", "recording")
        state.db.end_session(newer)
        assert state.db.sessions()[0]["id"] == newer
        p = client.get("/api/overlay").json()
        assert p["session"]["id"] == raid and p["session"]["fights"] == 1
