"""Session stats: how per-fight rows combine over a session, and per-player chart data."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factory import enemy, fight, player
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.metrics.aggregate import TREND_KEYS, aggregate_session
from wvw_analyzer.metrics.columns import COLUMNS_BY_KEY
from wvw_analyzer.metrics.timeline import boon_runs
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database

STAB_GEN, STAB_UP = "gen_squadBuffs_1122", "up_1122"
QUICKNESS, MIGHT = 1187, 740


def _row(acc: str, group: int, active_s: float, **vals) -> dict:
    return {"name": acc.split(".")[0], "account": acc, "profession": "Firebrand",
            "group": group, "in_fight": True, "active_s": active_s, **vals}


def _fight(fid: int, duration: float, rows: list[dict]) -> dict:
    return {"id": fid, "summary": {"result": "win", "durationS": duration, "map": "EBG",
                                   "start": f"2026-11-21 20:0{fid}:00"},
            "notes": {}, "players": rows}


def _session() -> dict:
    # Ann: a 5 min fight and a 1 min fight. Bob: the long fight only, then not in the fight.
    # Cid: only the short fight, with a lot of stability.
    return aggregate_session([
        _fight(1, 300, [
            _row("Ann.1", 1, 300, damage=1000, dps=3.3, strips=5, deaths=1,
                 **{STAB_GEN: 40, STAB_UP: 80}, fight_dist_tag=200),
            _row("Bob.2", 1, 300, damage=500, dps=1.7, strips=1, **{STAB_GEN: 20, STAB_UP: 60}),
        ]),
        _fight(2, 60, [
            _row("Ann.1", 1, 60, damage=200, dps=3.3, strips=1, **{STAB_GEN: 10, STAB_UP: 20},
                 fight_dist_tag=500),
            {**_row("Bob.2", 1, 60, damage=999, strips=99), "in_fight": False},
            _row("Cid.3", 2, 60, damage=100, dps=1.7, strips=0, **{STAB_GEN: 90, STAB_UP: 90}),
        ]),
    ])


def _player(agg: dict, acc: str) -> dict:
    return next(r for r in agg["players"] if r["account"] == acc)


def test_columns_carry_their_session_rule():
    assert COLUMNS_BY_KEY["damage"].session_agg == "sum"
    assert COLUMNS_BY_KEY["active_s"].session_agg == "sum"  # time in fights adds up
    assert COLUMNS_BY_KEY[STAB_GEN].session_agg == "time"  # generation: agg "sum", but a rate
    assert COLUMNS_BY_KEY[STAB_UP].session_agg == "time"
    assert COLUMNS_BY_KEY["dist_to_com"].session_agg == "time"
    assert COLUMNS_BY_KEY["dps"].session_agg == "dps"
    assert COLUMNS_BY_KEY["dps"].meta()["session"] == "dps"


def test_player_rows_sum_counts_and_time_weight_rates():
    ann = _player(_session(), "Ann.1")
    assert ann["fights"] == 2 and ann["activeS"] == 360
    assert ann["damage"] == 1200 and ann["strips"] == 6 and ann["deaths"] == 1
    assert ann[STAB_GEN] == pytest.approx((40 * 300 + 10 * 60) / 360)  # 35, not 50 or 25
    assert ann[STAB_UP] == pytest.approx((80 * 300 + 20 * 60) / 360)
    assert ann["dps"] == pytest.approx(1200 / 360)  # damage / time, not the DPS added up
    assert ann["fight_dist_tag"] == pytest.approx((200 * 300 + 500 * 60) / 360)
    assert ann["perMin"]["strips"] == pytest.approx(6 / 6) and STAB_GEN not in ann["perMin"]


def test_fights_a_player_was_not_in_are_left_out():
    bob = _player(_session(), "Bob.2")
    assert bob["fights"] == 1 and bob["damage"] == 500 and bob["strips"] == 1


def test_squad_and_party_rows():
    agg = _session()
    sq = agg["squad"]
    # Fight 1: Ann + Bob; fight 2: Ann + Cid (Bob wasn't in it).
    assert sq["damage"] == 1000 + 500 + 200 + 100
    # Squad generation per fight is the members' sum, then weighted by fight length.
    assert sq[STAB_GEN] == pytest.approx(((40 + 20) * 300 + (10 + 90) * 60) / 360)
    assert sq[STAB_UP] == pytest.approx(((80 + 60) / 2 * 300 + (20 + 90) / 2 * 60) / 360)
    p1, p2 = agg["parties"]
    assert p1["name"] == "Party 1" and p1["accounts"] == ["Ann.1", "Bob.2"]
    assert p1["members"] == 2 and p1["fights"] == 2
    assert p2["accounts"] == ["Cid.3"] and p2["fights"] == 1 and p2[STAB_GEN] == 90


def test_rate_leaderboard_needs_a_share_of_the_session():
    boards = _session()["leaderboards"]
    stab = boards[STAB_GEN]
    # Cid's 90% over 60 s of a 360 s session (17%) doesn't count; Ann's and Bob's do.
    assert stab["rate"] and [r["account"] for r in stab["rows"]] == ["Ann.1", "Bob.2"]
    assert stab["rows"][0]["perFight"] is None
    dmg = boards["damage"]
    assert not dmg["rate"] and dmg["rows"][0]["perFight"] == 600


def test_trend_per_fight_with_gaps():
    tr = _session()["trend"]
    assert tr["keys"] == TREND_KEYS
    assert tr["squad"]["damage"] == [1500, 300]
    assert tr["players"]["Bob.2"]["damage"] == [500, None]  # not in fight 2: a gap
    assert tr["players"]["Cid.3"][STAB_GEN] == [None, 90]
    assert tr["parties"]["2"]["damage"] == [None, 100]
    assert tr["squad"]["fight_dist_tag"] == [200, 500]
    assert tr["playerAvg"]["damage"] == [750, 150]  # the average in-fight player


def test_boon_runs_merge_and_close_at_log_end():
    states = [[0, 0], [1000, 1], [3000, 1], [5000, 0], [8000, 2]]
    assert boon_runs(states, 10_000) == [[1.0, 5.0], [8.0, 10.0]]
    assert boon_runs(states, 10_000, stacks=True) == [[1.0, 5.0, 1], [8.0, 10.0, 2]]
    assert boon_runs([[0, 3], [2000, 5]], 4000, stacks=True) == [[0.0, 2.0, 3], [2.0, 4.0, 5]]
    assert boon_runs(None, 1000) == []


def _player_fight():
    squad = [
        player("Ann One", 1, buffs={QUICKNESS: [[0, 1], [20_000, 0]], MIGHT: [[0, 10]]},
               downs=[[30_000, 32_000]]),
        player("Bob One", 1, commander=True),
    ] + [player(f"Fill {i}", 2) for i in range(5)]
    return analyze_ei(fight(squad, [enemy(j) for j in range(10)]), "x", Settings())


def test_player_series_in_the_stored_timeline():
    players = _player_fight().stats["timeline"]["players"]
    ann = players["AnnOne.1234"]
    assert ann["group"] == 1 and ann["inFight"]
    assert ann["boons"][str(QUICKNESS)] == [[0.0, 20.0]]
    assert ann["boons"][str(MIGHT)] == [[0.0, 60.0, 10]]
    assert ann["downs"] == [[30.0, 32.0]] and ann["deaths"] == []
    n = len(_player_fight().stats["timeline"]["t"])
    assert all(len(ann[k]) == n for k in ("health", "dmg_out", "dmg_in", "boonCount"))
    assert players["BobOne.1234"]["dist_tag"] is None  # the commander has no distance to tag


def test_fight_api_serves_player_series_one_at_a_time(tmp_path: Path):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    with TestClient(create_app(state)) as client:
        sid = state.db.create_session("Raid", "recording")
        fid = state.db.add_fight("/x/a.zevtc", sid, 0)
        a = _player_fight()
        state.db.save_analysis(fid, a.summary, a.stats, a.notes)
        detail = client.get(f"/api/fights/{fid}").json()
        assert "players" not in detail["stats"]["timeline"]
        one = client.get(f"/api/fights/{fid}/players/AnnOne.1234/timeline").json()
        assert one["name"] == "Ann One" and one["t"] == detail["stats"]["timeline"]["t"]
        assert client.get(f"/api/fights/{fid}/players/Nobody.1/timeline").status_code == 404
        agg = client.get(f"/api/sessions/{sid}").json()["aggregate"]
        assert agg["squad"]["fights"] == 1 and agg["parties"] and agg["trend"]["players"]


# ---- review fixes (run 1 and run 2 of /review-changes) -------------------------------------

def _split_session() -> dict:
    # One fight: Ann split into two in-fight rows (a spec change), 240 s and 60 s.
    return aggregate_session([_fight(1, 300, [
        _row("Ann.1", 1, 240, damage=1000, strips=4, **{STAB_UP: 50}),  # a Firebrand
        {**_row("Ann.1", 2, 60, damage=50, strips=1, **{STAB_UP: 100}), "profession": "Willbender"},
        _row("Bob.2", 1, 300, damage=300),
    ])])


def test_split_rows_are_one_player_in_one_fight():
    agg = _split_session()
    ann = _player(agg, "Ann.1")
    assert ann["fights"] == 1 and ann["damage"] == 1050 and ann["strips"] == 5
    assert ann[STAB_UP] == pytest.approx((50 * 240 + 100 * 60) / 300)
    assert ann["activeS"] == 300 and ann["group"] == 1  # the longer row's party
    assert ann["profession"] == "Firebrand, Willbender"
    assert agg["trend"]["players"]["Ann.1"]["damage"] == [1050]  # not the last row's 50
    assert agg["leaderboards"]["damage"]["rows"][0]["perFight"] == 1050


def test_time_column_is_the_time_everything_else_uses():
    # EI recorded no active time for this row: the fight's length counts, for the column too.
    agg = aggregate_session([_fight(1, 100, [_row("Ann.1", 1, 0, damage=600)])])
    ann = _player(agg, "Ann.1")
    assert ann["active_s"] == ann["activeS"] == 100
    assert ann["dps"] == 6 and ann["perMin"]["damage"] == 360 and "active_s" not in ann["perMin"]
    col = next(c for c in agg["columns"] if c["key"] == "active_s")
    assert col["label"] == "Time in fights"


def test_party_number_is_its_usual_size():
    # Party 1 has two players in each fight, three different accounts over the session.
    agg = aggregate_session([
        _fight(1, 100, [_row("Ann.1", 1, 100), _row("Bob.2", 1, 100)]),
        _fight(2, 100, [_row("Ann.1", 1, 100), _row("Cid.3", 1, 100)]),
    ])
    p1 = agg["parties"][0]
    assert p1["members"] == 2 and sorted(p1["accounts"]) == ["Ann.1", "Bob.2", "Cid.3"]


def test_overlay_summary_skips_the_detail():
    items = [_fight(1, 300, [_row("Ann.1", 1, 300, damage=5)])]
    full, light = aggregate_session(items), aggregate_session(
        [{k: v for k, v in it.items() if k != "players"} for it in items], detail=False)
    for k in ("fights", "totals", "recurringIssues", "positives"):
        assert light[k] == full[k]
    assert not {"players", "parties", "squad", "trend", "leaderboards"} & light.keys()


def _split_fight():
    ann = player("Ann One", 1, deaths=[[30_000, 2**63 - 1]])  # dead until the log ends
    ann2 = {**player("Ann Two", 2, buffs={QUICKNESS: [[0, 1]]}), "account": ann["account"]}
    squad = [ann, ann2] + [player(f"Fill {i}", 3) for i in range(5)]
    return analyze_ei(fight(squad, [enemy(j) for j in range(10)]), "x", Settings())


def test_split_rows_keep_their_own_series_and_deaths_end_with_the_log():
    a = _split_fight()
    rows = a.stats["players"]
    keys = [r["series_key"] for r in rows[:2]]
    assert keys == ["AnnOne.1234", "AnnOne.1234#2"]
    series = a.stats["timeline"]["players"]
    assert series["AnnOne.1234"]["name"] == "Ann One"
    assert series["AnnOne.1234#2"]["name"] == "Ann Two"
    assert series["AnnOne.1234#2"]["boons"][str(QUICKNESS)] == [[0.0, 60.0]]
    assert series["AnnOne.1234"]["deaths"] == [[30.0, 60.0]]  # not EI's int64 sentinel


def test_the_main_row_of_a_split_account_gets_the_account_key():
    # The first row was elsewhere on the map (not in the fight); the second is the one that
    # fought. Links that only know the account (the session trend) must open the second.
    away = player("Ann One", 1, pos_inches=(90_000.0, 0.0), damage_per_s=0)
    fought = {**player("Ann Two", 2), "account": away["account"]}
    squad = [away, fought] + [player(f"Fill {i}", 3) for i in range(5)]
    rows = analyze_ei(fight(squad, [enemy(j) for j in range(10)]), "x", Settings()).stats["players"]
    assert [r["in_fight"] for r in rows[:2]] == [False, True]
    assert [r["series_key"] for r in rows[:2]] == ["AnnOne.1234#2", "AnnOne.1234"]


def test_overlay_poll_reads_no_stats_blob(tmp_path: Path, monkeypatch):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    with TestClient(create_app(state)) as client:
        sid = state.db.create_session("Raid", "recording")
        fid = state.db.add_fight("/x/a.zevtc", sid, 0)
        a = _player_fight()
        state.db.save_analysis(fid, a.summary, a.stats, a.notes)

        def no_blob(*_a, **_k):
            raise AssertionError("the overlay must not unpack the stats blob")

        monkeypatch.setattr(state.db, "analysis", no_blob)
        calls = []
        orig = state.db.session_analyses
        monkeypatch.setattr(state.db, "session_analyses",
                            lambda s, players=True: calls.append(players) or orig(s, players))
        p = client.get("/api/overlay").json()
        assert p["fight"]["id"] == fid and p["session"]["id"] == sid
        assert calls and not any(calls)  # no player rows loaded either


def test_stats_are_packed_outside_the_db_lock(tmp_path: Path, monkeypatch):
    from wvw_analyzer.store import db as dbmod

    db = Database(tmp_path / "t.db")
    sid = db.create_session("Raid", "recording")
    fid = db.add_fight("/x/a.zevtc", sid, 0)
    held = []
    orig = dbmod._pack
    monkeypatch.setattr(dbmod, "_pack", lambda v: held.append(db._lock._is_owned()) or orig(v))
    a = _player_fight()
    db.save_analysis(fid, a.summary, a.stats, a.notes)
    assert held == [False]


# ---- review fixes (run 3 of /review-changes) ------------------------------------------------

DIST = "dist_to_com"


def test_session_distances_leave_out_eis_no_distance_values():
    # Fight 1 has a tag (Cmd at 0 from itself), fight 2 none (EI gives -1 to everyone).
    agg = aggregate_session([
        _fight(1, 300, [_row("Ann.1", 1, 300, **{DIST: 300}),
                        {**_row("Cmd.2", 1, 300, **{DIST: 0}), "is_commander": True}]),
        _fight(2, 300, [_row("Ann.1", 1, 300, **{DIST: -1}),
                        {**_row("Cmd.2", 1, 300, **{DIST: -1}), "is_commander": True}]),
    ])
    assert _player(agg, "Ann.1")[DIST] == 300  # not (300 + -1) / 2
    assert _player(agg, "Cmd.2")[DIST] is None  # never a distance: shown as "–", not 0
    assert agg["squad"][DIST] == 300 and agg["parties"][0][DIST] == 300


def test_average_player_counts_a_split_player_once():
    agg = aggregate_session([_fight(1, 300, [
        _row("Ann.1", 1, 200, damage=600),
        _row("Ann.1", 2, 100, damage=300),  # the same player, split by EI
        _row("Bob.2", 1, 300, damage=300),
    ])])
    assert agg["trend"]["playerAvg"]["damage"] == [600]  # (900 + 300) / 2 players, not / 3


def test_split_rows_weighted_by_their_own_active_time():
    # Rows at 100 s and 0 s in a 300 s fight: the 0 s row adds no time and no weight.
    agg = aggregate_session([_fight(1, 300, [
        _row("Ann.1", 1, 100, damage=600, **{STAB_UP: 60}),
        _row("Ann.1", 2, 0, damage=0, **{STAB_UP: 0}),
    ])])
    ann = _player(agg, "Ann.1")
    assert ann["activeS"] == ann["active_s"] == 100
    assert ann[STAB_UP] == 60 and ann["dps"] == 6
    # No active time on any row: the fight's length, as for a single row.
    agg = aggregate_session([_fight(1, 300, [_row("Ann.1", 1, 0, **{STAB_UP: 50}),
                                             _row("Ann.1", 2, 0, **{STAB_UP: 100})])])
    ann = _player(agg, "Ann.1")
    assert ann["activeS"] == 300 and ann[STAB_UP] == 75


def test_session_aggregate_does_not_depend_on_the_hash_seed():
    # Party accounts with equal fight counts are ordered by row order, not by set iteration.
    import subprocess
    import sys

    # The child imports the same code as this test run (same sys.path).
    code = (
        "import json, sys; sys.path[:0] = json.loads(sys.argv[1])\n"
        "from test_session_stats import aggregate_session, _fight, _row\n"
        "rows = [_row(f'P{i}.{i}', 1, 100) for i in range(12)]\n"
        "print(json.dumps(aggregate_session([_fight(1, 100, rows)])['parties'][0]['accounts']))"
    )
    path = json.dumps([str(Path(__file__).parent), *sys.path])
    runs = {
        subprocess.run([sys.executable, "-c", code, path], capture_output=True,
                       text=True, check=True, env={"PYTHONHASHSEED": seed}).stdout
        for seed in ("1", "2", "3")
    }
    assert len(runs) == 1 and json.loads(runs.pop()) == [f"P{i}.{i}" for i in range(12)]


def test_recurring_problems_rank_and_show_their_worst_severity():
    # "Rezzes" was minor in its first fight and major after; three losses. "Outnumbered" (major)
    # was in two losses and two wins. Ranked by its first severity (minor: 3*2 + 3*0.3 = 6.9)
    # the rezzes would sink below it (2*2 + 4 = 8); by its worst (3*2 + 3 = 9) it leads.
    def note(key: str, severity: str) -> dict:
        return {"detector": key, "key": key, "title": key.title(), "severity": severity,
                "impact": 1.0, "short": ""}

    def fought(fid: int, result: str, *notes: dict) -> dict:
        f = _fight(fid, 60, [])
        f["summary"]["result"] = result
        f["notes"] = {"issues": list(notes)}
        return f

    rez_minor, rez_major, out = note("rezzes", "minor"), note("rezzes", "major"), note(
        "outnumbered", "major")
    agg = aggregate_session([
        fought(1, "loss", rez_minor, out),
        fought(2, "loss", rez_major, out),
        fought(3, "loss", rez_major),
        fought(4, "win", out),
        fought(5, "win", out),
    ], detail=False)
    ranked = [(p["key"], p["severity"]) for p in agg["recurringIssues"]]
    assert ranked == [("rezzes", "major"), ("outnumbered", "major")]
