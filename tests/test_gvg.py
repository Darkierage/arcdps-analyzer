"""GvG mode: rounds end with a call-off; downs left then and kills after it are not counted."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from factory import enemy, fight, player, zerg
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.llm import prompts
from wvw_analyzer.model.fight import _merge_continued
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database

DUR = 60_000


def _squad(n=10, active=((0, 40),), duration_ms=DUR, downs=None):
    """Squad fighting only inside ``active`` (s); downs = {index: (down_ms, dead_ms or None)}."""
    downs = downs or {}
    out = []
    for i in range(n):
        down, dead = [], []
        if i in downs:
            d, k = downs[i]
            down = [[d, k if k else duration_ms]]
            dead = [[k, duration_ms]] if k else []
        out.append(player(f"Player {i}", 1 + i % 2, commander=(i == 0), pos_inches=(i * 10.0, 0),
                          duration_ms=duration_ms, active=list(active), downs=down, deaths=dead))
    return out


def _round_with_left_enemy_downs():
    """One round fought until 40 s, then called off with 6 enemies still downed."""
    enemies = [enemy(j, down_iv=[[38_000, DUR]]) for j in range(6)]
    enemies += [enemy(j) for j in range(6, 20)]
    return fight(_squad(), enemies)


def _keys(a):
    return {f["key"] for b in ("issues", "more", "positives") for f in a.notes[b]}


def test_left_enemy_downs_are_not_an_issue_in_gvg():
    data = _round_with_left_enemy_downs()
    zerg_a = analyze_ei(data, "x", Settings())
    gvg_a = analyze_ei(data, "x", Settings(), mode="gvg")
    assert "downstate_enemy" in _keys(zerg_a)  # 6 downs, 0 kills: looks like failed cleaves
    assert "downstate_enemy" not in _keys(gvg_a)
    s = gvg_a.summary
    assert s["mode"] == "gvg" and s["enemyDownsLeft"] == 6 and len(s["rounds"]) == 1
    # 6 enemies taken out vs none of ours: a round win, while the deaths trade says "skirmish".
    assert zerg_a.summary["result"] == "skirmish" and s["result"] == "win"


def test_kill_after_calloff_is_not_counted():
    enemies = [enemy(0, down_iv=[[38_000, 50_000]], dead_iv=[[50_000, DUR]])]
    enemies += [enemy(j) for j in range(1, 20)]
    squad = _squad(downs={3: (39_000, 52_000)})  # our down, finished long after the call
    s = analyze_ei(fight(squad, enemies), "x", Settings(), mode="gvg").summary
    assert s["enemyDeathsLate"] == 1 and s["enemyDownsLeft"] == 1
    assert s["squadDeathsLate"] == 1 and s["squadDownsLeft"] == 1
    r = s["rounds"][0]
    assert r["enemyDeaths"] == 0 and r["squadDeaths"] == 0 and r["enemyLeft"] == r["squadLeft"] == 1


def test_kill_within_grace_counts():
    enemies = [enemy(0, down_iv=[[38_000, 41_500]], dead_iv=[[41_500, DUR]])]
    enemies += [enemy(j) for j in range(1, 20)]
    s = analyze_ei(fight(_squad(), enemies), "x", Settings(), mode="gvg").summary
    assert s["enemyDeathsLate"] == 0 and s["enemyDownsLeft"] == 0
    assert s["rounds"][0]["enemyDeaths"] == 1


def test_two_rounds_in_one_log_are_judged_separately():
    dur = 120_000
    # Round 2 opens with 4 downs in 2 s before the enemy loses anyone.
    downs = {i: (72_000 + i * 500, 74_000 + i * 500) for i in range(1, 5)}
    squad = _squad(active=((0, 30), (70, 100)), duration_ms=dur, downs=downs)
    data = fight(squad, [enemy(j) for j in range(20)], duration_ms=dur)
    gvg_a = analyze_ei(data, "x", Settings(), mode="gvg")
    s = gvg_a.summary
    assert [round(r["start"]) for r in s["rounds"]] == [1, 71]
    assert s["rounds"][1]["squadDeaths"] == 4 and s["rounds"][1]["result"] == "loss"
    cascade = next(f for f in gvg_a.notes["issues"] if f["key"] == "early_cascade")
    assert cascade["evidence"]["since_engage"] < 5  # measured from round 2's start
    assert "1 of 2 rounds" in cascade["cause"]
    # Zerg mode keeps one window over the whole log.
    assert "rounds" not in analyze_ei(data, "x", Settings()).summary


def test_zerg_summary_has_nothing_left():
    s = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "x", Settings()).summary
    assert s["mode"] == "zerg"
    assert s["squadDownsLeft"] == s["enemyDownsLeft"] == s["enemyDeathsLate"] == 0


def test_gvg_header_line():
    a = analyze_ei(_round_with_left_enemy_downs(), "x", Settings(), mode="gvg")
    head = prompts.header_v8(a.summary, a.notes)
    assert head.startswith("Result: GvG round win")
    assert "Left at the call-off (not counted): 6 enemy downs, 0 of ours." in head
    assert "skirmish" not in head.lower()
    _, user = prompts.messages("v8_header", a.summary, a.notes)
    assert "6 enemy downs" in user  # the header counts as input for the number check


def test_continued_intervals_are_merged():
    # EI splits a state that is still open at the end of the log.
    assert _merge_continued([[1, 5], [5, 9], [12, 13]]) == [[1, 9], [12, 13]]


def test_db_migration_marks_old_fights_zerg(tmp_path: Path):
    db_file = tmp_path / "old.db"
    con = sqlite3.connect(db_file)
    con.execute("""CREATE TABLE fights (id INTEGER PRIMARY KEY, session_id INTEGER,
        log_path TEXT NOT NULL UNIQUE, log_name TEXT NOT NULL, log_mtime REAL, status TEXT NOT NULL,
        error TEXT, ei_json TEXT, fight_start TEXT, result TEXT, summary TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    con.execute("INSERT INTO fights(log_path, log_name, status, created_at, updated_at) "
                "VALUES ('a', 'a', 'done', 'x', 'x')")
    con.commit()
    con.close()
    db = Database(db_file)
    assert db.fight(1)["mode"] == "zerg"
    assert db.fight(db.add_fight("b", None, 0, "gvg"))["mode"] == "gvg"


def test_mode_api_stores_mode_and_reanalyzes(tmp_path: Path, monkeypatch):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    queued: list[int] = []
    monkeypatch.setattr(state.processor, "enqueue", lambda fid, **kw: queued.append(fid))
    with TestClient(create_app(state)) as client:
        client.put("/api/settings", json={"fight_mode": "gvg"})
        assert client.get("/api/status").json()["fightMode"] == "gvg"
        sid = state.db.create_session("GvG night", "recording")
        f1 = state.db.add_fight("/x/a.zevtc", sid, 0)
        f2 = state.db.add_fight("/x/b.zevtc", sid, 0)
        assert client.put(f"/api/fights/{f1}/mode", json={"mode": "gvg"}).json() == {"queued": 1}
        assert state.db.fight(f1)["mode"] == "gvg" and queued == [f1]
        assert client.put(f"/api/sessions/{sid}/mode", json={"mode": "gvg"}).json()["queued"] == 2
        assert state.db.fight(f2)["mode"] == "gvg"
        assert client.put(f"/api/fights/{f1}/mode", json={"mode": "pvp"}).status_code == 422
        assert client.put("/api/fights/999/mode", json={"mode": "gvg"}).status_code == 404


def test_mode_change_during_processing_runs_again(tmp_path: Path):
    from wvw_analyzer.events import EventBus
    from wvw_analyzer.ingest.processor import Processor

    db = Database(tmp_path / "t.db")
    p = Processor(db, ConfigStore(tmp_path / "c.yaml"), EventBus())
    fid = db.add_fight("/x/a.zevtc", None, 0)
    p._pending.add(fid)
    p._current = fid  # being analyzed with the old mode right now
    p.enqueue(fid)
    assert p._rerun == {fid: False}  # not dropped: it runs again once the current pass ends
