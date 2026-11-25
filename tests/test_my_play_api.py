"""The personal review API ("My play"): players, scopes, the default account."""

from pathlib import Path

from fastapi.testclient import TestClient

from factory import enemy, fight, player
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database

DOWNER = "Player3.1234"  # goes down twice in every fight; nobody else does


def _fight(i: int, downs: bool = True):
    squad = []
    for p in range(10):
        dn = [[20_000, 22_000], [40_000, 41_000]] if downs and p == 3 else []
        squad.append(player(f"Player {p}", 1 + p % 2, commander=(p == 0), downs=dn,
                            stab=[[0, 5]]))
    data = fight(squad, [enemy(j) for j in range(10)])
    data["timeStartStd"] = f"2026-11-{17 + i // 6} 20:{(i % 6) * 5:02d}:00 +01:00"
    return data


def _client(tmp_path: Path, n: int = 12):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    sessions = [state.db.create_session(f"Day {d}", "import") for d in range(2)]
    ids = []
    for i in range(n):
        fid = state.db.add_fight(f"/x/{i}.zevtc", sessions[i // 6], 0)
        a = analyze_ei(_fight(i), str(i), Settings())
        state.db.save_analysis(fid, a.summary, a.stats, a.notes, a.facts)
        ids.append(fid)
    return TestClient(create_app(state)), state, sessions, ids


def test_players_and_the_default_account(tmp_path: Path):
    client, state, *_ = _client(tmp_path)
    with client:
        body = client.get("/api/players").json()
        assert len(body["players"]) == 10 and body["players"][0]["fights"] == 12
        assert body["default"] == "Player0.1234"  # recorded every fight
        client.put("/api/settings", json={"my_account": DOWNER})
        assert client.get("/api/players").json()["default"] == DOWNER
        client.put("/api/settings", json={"my_account": "Gone.1"})  # no longer in any fight
        assert client.get("/api/players").json()["default"] == "Player0.1234"


def test_profile_session_and_fight_scopes(tmp_path: Path):
    client, state, sessions, ids = _client(tmp_path)
    with client:
        prof = client.get(f"/api/players/{DOWNER}/review").json()
        assert prof["scope"]["kind"] == "profile" and prof["scope"]["fights"] == 12
        assert prof["scope"]["sessions"] == 2 and prof["downCount"] == 24
        assert [a["key"] for a in prof["advice"]["work"]] == ["me_deaths"]
        assert prof["advice"]["work"][0]["trend"] == "same"
        assert prof["recentDowns"][0]["fightId"] == ids[-1]
        assert prof["recentDowns"][0]["hint"]["title"].startswith("0:40")
        assert {n["key"] for n in prof["numbers"]} >= {"damage", "stab_up", "dist_tag"}
        assert "cast" not in {n["key"] for n in prof["numbers"]}  # not in these logs

        sess = client.get(f"/api/players/{DOWNER}/review",
                          params={"session": sessions[0]}).json()
        assert sess["scope"]["kind"] == "session" and sess["scope"]["fights"] == 6
        assert sess["advice"]["work"][0]["cause"].startswith("This session (6 fights)")
        last = client.get(f"/api/players/{DOWNER}/review", params={"sessions": 1}).json()
        assert last["scope"]["kind"] == "session" and last["scope"]["to"].startswith("2026-11-18")
        days = client.get(f"/api/players/{DOWNER}/review",
                          params={"from": "2026-11-18", "to": "2026-11-18"}).json()
        assert days["scope"]["fights"] == 6

        one = client.get(f"/api/players/{DOWNER}/review", params={"fight": ids[0]}).json()
        assert one["scope"]["kind"] == "fight" and one["advice"] is None
        f = one["fight"]
        assert [d["t"] for d in f["downs"]] == [20.0, 40.0] and f["spec"] == "Firebrand"
        assert all(d["hint"]["key"].startswith("me_hint_") for d in f["downs"])
        spec = client.get(f"/api/players/{DOWNER}/review",
                          params={"profession": "Scourge"}).json()
        assert spec["scope"]["fights"] == 0


def test_unknown_player_too_little_data_and_nothing_to_work_on(tmp_path: Path):
    client, state, sessions, ids = _client(tmp_path, n=3)
    with client:
        assert client.get("/api/players/Nobody.1/review").status_code == 404
        r = client.get(f"/api/players/{DOWNER}/review", params={"fight": 9999})
        assert r.status_code == 404
        few = client.get(f"/api/players/{DOWNER}/review").json()
        assert few["advice"]["work"] == [] and few["advice"]["nothing"]
        assert any(g["rule"] == "me_deaths" and "needs 5 fights" in g["need"]
                   for g in few["gates"])
        calm = client.get("/api/players/Player5.1234/review").json()
        assert calm["downCount"] == 0 and calm["advice"]["work"] == []


def test_settings_list_the_personal_rules(tmp_path: Path):
    client, *_ = _client(tmp_path, n=1)
    with client:
        s = client.get("/api/settings").json()
        rules = {r["name"]: r for r in s["personalRules"]}
        assert rules["me_deaths"]["enabled"] and not rules["me_down_far"]["enabled"]
        r = client.put("/api/settings", json={"detectors": {"me_down_far": {"enabled": True}}})
        assert {x["name"]: x for x in r.json()["personalRules"]}["me_down_far"]["enabled"]


def test_downs_table_and_hints_follow_the_settings(tmp_path: Path):
    client, state, sessions, ids = _client(tmp_path, n=2)
    with client:
        far = lambda r: next(x for x in r["downSplit"] if x["key"] == "me_down_far")  # noqa: E731
        before = client.get(f"/api/players/{DOWNER}/review").json()
        assert far(before)["label"] == "over 1000 from the tag"
        r = client.put("/api/settings", json={"detectors": {"me_down_far": {"far_tag": 1500},
                                                             "me_caught_alone": {"max_near": 2}}})
        assert r.status_code == 200
        after = client.get(f"/api/players/{DOWNER}/review").json()
        assert far(after)["label"] == "over 1500 from the tag"
        alone = next(x for x in after["downSplit"] if x["key"] == "me_caught_alone")
        assert alone["label"].startswith("at most 2 other")
        # Nobody else goes down here: every down is "alone" under any max_near.
        assert after["recentDowns"][0]["hint"]["key"] == "me_hint_alone"


def test_a_player_not_in_the_fight_has_no_recap(tmp_path: Path):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    squad = [player(f"Player {p}", 1 + p % 2, commander=(p == 0)) for p in range(9)]
    squad.append(player("Away", 1, pos_inches=(90_000.0, 0.0), damage_per_s=0))
    fid = state.db.add_fight("/x/a.zevtc", None, 0)
    a = analyze_ei(fight(squad, [enemy(j) for j in range(10)]), "a", Settings())
    state.db.save_analysis(fid, a.summary, a.stats, a.notes, a.facts)
    assert not next(r for r in a.facts if r["account"] == "Away.1234")["in_fight"]
    with TestClient(create_app(state)) as client:
        r = client.get("/api/players/Away.1234/review", params={"fight": fid})
        assert r.status_code == 404
        assert client.get("/api/players/Player1.1234/review",
                          params={"fight": fid}).json()["fight"]
