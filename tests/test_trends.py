"""Trends across sessions: one row per session, numbers equal to the session's own summary."""

from pathlib import Path

from fastapi.testclient import TestClient

from factory import enemy, fight, player
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.metrics.aggregate import session_trend
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database


def _item(fid: int, result: str, squad_deaths: int = 0, enemy_deaths: int = 0,
          notes: dict | None = None, **extra) -> dict:
    return {"id": fid, "notes": notes or {},
            "summary": {"result": result, "squadDeaths": squad_deaths,
                        "enemyDeaths": enemy_deaths, "durationS": 60.0, "map": "EBG",
                        "start": f"2026-11-21 20:{fid:02d}:00", **extra}}


def _session(sid: int, items: list[dict], name: str = "Raid") -> dict:
    return {"id": sid, "name": name, "kind": "recording",
            "start": f"2026-11-{sid:02d} 20:00:00", "items": items}


def test_one_row_per_session_in_the_order_given():
    rows = session_trend([
        _session(1, [_item(1, "win", 1, 6), _item(2, "loss", 8, 2), _item(3, "even", 4, 4),
                     _item(4, "win", 0, 5)]),
        _session(2, [_item(5, "loss", 9, 1)]),
    ])
    assert [r["id"] for r in rows] == [1, 2]
    a, b = rows
    assert a["fights"] == 4 and a["results"] == {"win": 2, "loss": 1, "even": 1, "skirmish": 0}
    assert a["winRate"] == 50.0
    assert a["squadDeaths"] == 13 and a["enemyDeaths"] == 17
    assert a["kdr"] == round(17 / 13, 2) and a["deathsPerFight"] == round(13 / 4, 1)
    assert b["winRate"] == 0.0 and b["kdr"] == round(1 / 9, 2) and b["deathsPerFight"] == 9.0


def test_skirmishes_stay_out_of_the_win_rate():
    rows = session_trend([
        _session(1, [_item(1, "win", 0, 4), _item(2, "skirmish", 1, 0),
                     _item(3, "skirmish", 0, 1)]),
        _session(2, [_item(4, "skirmish", 1, 1)]),
    ])
    assert rows[0]["results"]["skirmish"] == 2 and rows[0]["winRate"] == 100.0
    assert rows[0]["fights"] == 3 and rows[0]["deathsPerFight"] == round(1 / 3, 1)
    # Skirmishes only: no rate (not 0%), and no squad deaths still gives a K/D.
    assert rows[1]["winRate"] is None and rows[1]["kdr"] == 1.0


def test_sessions_without_analyzed_fights_are_left_out():
    assert session_trend([]) == []
    rows = session_trend([_session(1, []), _session(2, [_item(1, "win", 0, 3)])])
    assert [r["id"] for r in rows] == [2]


def test_gvg_late_deaths_do_not_count_like_on_the_session_page():
    rows = session_trend([_session(1, [
        _item(1, "win", 5, 9, mode="gvg", squadDeathsLate=2, enemyDeathsLate=1)])])
    assert rows[0]["squadDeaths"] == 3 and rows[0]["enemyDeaths"] == 8
    assert rows[0]["deathsPerFight"] == 3.0 and rows[0]["kdr"] == round(8 / 3, 2)


def test_top_recurring_problem_is_the_session_summarys_first():
    finding = {"detector": "stab_gap_deaths", "key": "stab_gap_deaths", "severity": "major",
               "title": "Deaths without stability (3)", "short": "3 died without stability"}
    minor = {"detector": "late_push", "key": "late_push", "severity": "minor",
             "title": "Late push", "short": "pushed late"}
    rows = session_trend([_session(1, [
        _item(1, "loss", 6, 1, notes={"issues": [finding, minor]}),
        _item(2, "loss", 7, 1, notes={"issues": [finding]}),
        _item(3, "win", 1, 6, notes={"issues": [minor]}),
    ]), _session(2, [_item(4, "win", 0, 5)])])
    assert rows[0]["topIssue"] == {"key": "stab_gap_deaths", "title": "Deaths without stability",
                                   "count": 2, "losses": 2, "severity": "major"}
    assert rows[1]["topIssue"] is None


def _ei(start: str, squad_deaths: int, enemy_deaths: int) -> dict:
    players = [player(f"Player {i}", 1 + i % 2, commander=(i == 0), pos_inches=(i * 10.0, 0.0),
                      downs=[[20_000, 22_000]] if i < squad_deaths else [],
                      deaths=[[22_000, 60_000]] if i < squad_deaths else [])
               for i in range(10)]
    ei = fight(players, [enemy(j, deaths=1 if j < enemy_deaths else 0) for j in range(20)])
    ei["timeStartStd"] = start
    return ei


def test_api_trends_matches_each_session_summary(tmp_path: Path):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    plan = {
        "Late raid": [("2026-11-20 20:00:00 +01:00", 1, 8), ("2026-11-20 20:10:00 +01:00", 7, 1)],
        "Early raid": [("2026-11-18 21:00:00 +01:00", 6, 0), ("2026-11-18 20:00:00 +01:00", 0, 9),
                       ("2026-11-18 20:30:00 +01:00", 1, 0)],
    }
    ids = {}
    with TestClient(create_app(state)) as client:
        n = 0
        for name, fights in plan.items():   # the later session is created first
            ids[name] = state.db.create_session(name, "recording")
            for start, sq, en in fights:
                n += 1
                fid = state.db.add_fight(f"/x/{n}.zevtc", ids[name], 0)
                a = analyze_ei(_ei(start, sq, en), str(n), Settings())
                state.db.save_analysis(fid, a.summary, a.stats, a.notes)
        empty = state.db.create_session("No fights yet", "recording")
        queued = state.db.create_session("Only queued", "import")
        state.db.add_fight("/x/queued.zevtc", queued, 0)

        rows = client.get("/api/trends").json()["sessions"]
        assert [r["name"] for r in rows] == ["Early raid", "Late raid"]   # oldest first
        assert empty not in [r["id"] for r in rows] and queued not in [r["id"] for r in rows]
        assert rows[0]["start"] == "2026-11-18 20:00:00 +01:00"
        for r in rows:
            totals = client.get(f"/api/sessions/{r['id']}").json()["aggregate"]["totals"]
            assert r["fights"] == totals["fights"] == len(plan[r["name"]])
            assert r["kdr"] == totals["kdr"]
            assert r["squadDeaths"] == totals["squadDeaths"]
            assert r["enemyDeaths"] == totals["enemyDeaths"]
            assert {k: v for k, v in r["results"].items() if v} == totals["results"]
        early = rows[0]
        assert early["results"]["skirmish"] == 1 and early["winRate"] == 50.0


def test_top_problem_matches_the_session_page_when_a_fight_has_no_start(tmp_path: Path):
    """Two problems tie, and the later fight has no start time: both pages must read the
    session's fights in the same order, or they name different top problems."""
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))

    def note(key: str) -> dict:
        return {"issues": [{"detector": key, "key": key, "severity": "major",
                            "title": key.upper(), "short": key}]}

    with TestClient(create_app(state)) as client:
        sid = state.db.create_session("Raid", "recording")
        summary = {"result": "loss", "squadDeaths": 5, "enemyDeaths": 1, "durationS": 60.0}
        first = state.db.add_fight("/x/1.zevtc", sid, 0)
        state.db.save_analysis(first, {**summary, "start": "2026-11-20 20:00:00 +01:00"},
                               {"players": []}, note("aaa"))
        second = state.db.add_fight("/x/2.zevtc", sid, 0)
        state.db.save_analysis(second, summary, {"players": []}, note("bbb"))   # no start

        row = client.get("/api/trends").json()["sessions"][0]
        agg = client.get(f"/api/sessions/{sid}").json()["aggregate"]
        assert row["topIssue"]["key"] == agg["recurringIssues"][0]["key"]
        assert row["start"] == "2026-11-20 20:00:00 +01:00"   # not the start-less fight's
