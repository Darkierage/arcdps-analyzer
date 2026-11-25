"""Per-fight player facts for the personal review (metrics/personal.py) and their table."""

from pathlib import Path

from factory import enemy, fight, player
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.config import Settings
from wvw_analyzer.store.db import Database

DUR = 60_000
END = 2**63 - 1  # EI's "until the log ends"


def _squad(downs=None, stab_less=(), **kw):
    """10 players in two parties, all with stability except `stab_less`; player 0 commands.
    downs = {index: (down_ms, dead_ms or None)}."""
    downs = downs or {}
    out = []
    for i in range(10):
        down, dead = [], []
        if i in downs:
            d, k = downs[i]
            down = [[d, k if k else d + 2000]]
            dead = [[k, END]] if k else []
        out.append(player(f"Player {i}", 1 + i % 2, commander=(i == 0), downs=down, deaths=dead,
                          stab=[[0, 0]] if i in stab_less else [[0, 5]], **kw))
    return out


def _facts(squad, mode="zerg", **fight_kw):
    a = analyze_ei(fight(squad, [enemy(j) for j in range(10)], **fight_kw), "x", Settings(),
                   mode=mode)
    return a, {r["key"]: r for r in a.facts}


def _key(i):
    return f"Player{i}.1234"


def test_downs_with_and_without_stability_alone_and_in_a_bomb():
    # Player 3 (party 2) goes down without stability at 20 s, player 5 (party 2) half a second
    # later with it; player 7 alone at 40 s and rallies.
    squad = _squad(downs={3: (20_000, 22_000), 5: (20_500, 23_000), 7: (40_000, None)},
                   stab_less={3})
    _, rows = _facts(squad)
    d3 = rows[_key(3)]["facts"]["downs"]
    assert len(d3) == 1
    d = d3[0]
    assert d["stab"] == 0 and d["died"] and d["near"] == 1 and d["rank"] == 1
    assert d["party_stab"] == 100  # every other up member of party 2 had stability
    assert d["hp_before"] == 100
    d5 = rows[_key(5)]["facts"]["downs"][0]
    assert d5["stab"] == 5 and d5["near"] == 1 and d5["rank"] == 2
    d7 = rows[_key(7)]["facts"]["downs"][0]
    assert d7["near"] == 0 and not d7["died"] and d7["rank"] == 3
    # The squad's side excludes the player's own downs.
    sq = rows[_key(3)]["facts"]["squad"]
    assert sq["downs_total"] == 3 and sq["players_downed"] == 3 and len(sq["downs"]) == 2
    assert [x[0] for x in sq["downs"]] == [5, 5]  # stab stacks of the other two downs
    assert rows[_key(3)]["facts"]["first_rank"] == 1
    assert rows[_key(7)]["facts"]["first_rank"] == 3
    assert rows[_key(1)]["facts"]["first_rank"] is None
    assert len(rows[_key(1)]["facts"]["squad"]["downs"]) == 3


def test_gvg_downs_left_at_the_calloff_are_kept_apart():
    active = [(0, 40)]
    squad = []
    for i in range(10):
        down = [[39_000, DUR]] if i == 3 else []  # still downed when the round was called
        squad.append(player(f"Player {i}", 1 + i % 2, commander=(i == 0), downs=down,
                            active=active, stab=[[0, 5]]))
    _, rows = _facts(squad, mode="gvg")
    f3 = rows[_key(3)]["facts"]
    assert f3["downs"] == [] and len(f3["downs_left"]) == 1 and f3["downs_left"][0]["left"]
    assert rows[_key(1)]["facts"]["squad"]["downs"] == []
    assert rows[_key(1)]["facts"]["squad"]["downs_total"] == 0
    # The same log in zerg mode judges it.
    _, zrows = _facts(squad)
    assert len(zrows[_key(3)]["facts"]["downs"]) == 1


def test_times_are_clamped_and_cast_uptime_above_100_is_dropped():
    squad = _squad(downs={4: (30_000, 32_000)})
    squad[4]["statsAll"][0].update(skillCastUptimeNoAA=114.6, wasted=3, timeWasted=1.5)
    squad[5]["statsAll"][0].update(skillCastUptimeNoAA=42.0)
    _, rows = _facts(squad)
    f4 = rows[_key(4)]["facts"]
    assert f4["dead_s"] == 28 and f4["downed_s"] == 2  # dead until the end, not until int64
    assert f4["cast"] is None and f4["cancels"] == 3 and f4["cancel_s"] == 1.5
    assert rows[_key(5)]["facts"]["cast"] == 42
    assert rows[_key(6)]["facts"]["cast"] is None  # not in the log


def test_death_recap_skill_tables_consumables_and_dodges():
    squad = _squad(downs={4: (30_000, 32_000)})
    squad[4]["deathRecap"] = [{"deathTime": 32_000, "toDown": [
        {"id": 100, "indirectDamage": False, "src": "Scourge pl-1", "damage": 6000, "time": 29_000},
        {"id": 100, "indirectDamage": False, "src": "Scourge pl-2", "damage": 2000, "time": 29_500},
        {"id": 737, "indirectDamage": True, "src": "Reaper pl-3", "damage": 2000, "time": 29_900},
        {"id": 5, "indirectDamage": False, "src": "UNKNOWN", "damage": 0, "time": 28_000},
    ], "toKill": []}]
    squad[4]["totalDamageDist"] = [[
        {"id": 100, "totalDamage": 9000, "hits": 10, "connectedHits": 8, "blocked": 1,
         "evaded": 1, "missed": 0, "indirectDamage": False},
        {"id": 737, "totalDamage": 1000, "hits": 4, "connectedHits": 4, "indirectDamage": True},
    ]]
    squad[4]["totalDamageTaken"] = [[]]
    squad[4]["consumables"] = [{"id": 1, "time": 0, "duration": 1}]
    squad[5]["consumables"] = [{"id": 1, "time": 0, "duration": 1},
                               {"id": 2, "time": 0, "duration": 1}]
    squad[4]["rotation"] = [{"id": 23275, "skills": [{"castTime": 1}, {"castTime": 2}]},
                            {"id": 100, "skills": [{"castTime": 3}]}]
    data = fight(squad, [enemy(j) for j in range(10)])
    data["skillMap"] = {"s100": {"name": "Big Hit"}, "s23275": {"name": "Dodge"}}
    data["buffMap"] = {"b737": {"name": "Burning", "classification": "Condition"},
                       "b1": {"name": "Food", "classification": "Nourishment"},
                       "b2": {"name": "Utility", "classification": "Enhancement"}}
    rows = {r["key"]: r for r in analyze_ei(data, "x", Settings()).facts}
    f4 = rows[_key(4)]["facts"]
    rc = f4["downs"][0]["recap"]
    assert rc["span"] == 0.9 and rc["enemies"] == 3
    assert rc["top"][0] == {"skill": "Big Hit", "share": 0.8, "spec": "Scourge"}
    assert rc["top"][1] == {"skill": "Burning", "share": 0.2, "spec": "Reaper"}
    assert f4["dealt"][0]["skill"] == "Big Hit" and f4["dealt"][0]["connected"] == 0.8
    assert f4["dealt"][1]["skill"] == "Burning"
    assert f4["taken"] is None  # the log has none for this row
    assert f4["food"] is True and f4["utility"] is False
    assert rows[_key(5)]["facts"]["utility"] is True
    assert rows[_key(6)]["facts"]["food"] is None  # no consumables list at all
    assert f4["dodges"] == 2
    assert rows[_key(6)]["facts"]["dodges"] is None  # no casts in the log
    # A death without a recap entry has no recap.
    squad2 = _squad(downs={4: (30_000, 32_000)})
    rows2 = {r["key"]: r for r in analyze_ei(fight(squad2, [enemy(j) for j in range(10)]),
                                             "x", Settings()).facts}
    assert "recap" not in rows2[_key(4)]["facts"]["downs"][0]


def test_peers_same_spec_and_job_without_the_commander():
    squad = _squad()
    squad[1]["profession"] = "Scrapper"  # nobody else plays it
    squad[2]["support"][0]["condiCleanse"] = 400  # a cleanser among damage dealers
    _, rows = _facts(squad)
    f1 = rows[_key(1)]["facts"]
    assert f1["peers"]["damage"][2] == 0 and f1["peers"]["damage"][1] is None
    assert f1["peers"]["damage"][3] is not None  # the squad median is still there
    assert rows[_key(2)]["facts"]["job"] == "cleanses"
    assert rows[_key(3)]["facts"]["job"] == "damage"
    # Peers of a damage Firebrand: the 6 other damage Firebrands (no commander, no cleanser).
    assert rows[_key(3)]["facts"]["peers"]["damage"][2] == 6
    assert rows[_key(2)]["facts"]["peers"]["cleanses"][2] == 0
    cmd = rows[_key(0)]
    assert cmd["is_commander"] and not cmd["facts"]["eligible"]
    assert cmd["facts"]["peers"]["dist_tag"][0] is None


def test_a_split_player_is_one_account():
    squad = _squad(downs={3: (20_000, 22_000)})
    twin = {**player("Player 3b", 2, downs=[[40_000, 41_000]]), "account": _key(3)}
    squad.append(twin)
    _, rows = _facts(squad)
    a, b = rows[_key(3)], rows[_key(3) + "#2"]
    assert a["account"] == b["account"] == _key(3)
    # Neither row counts the account's own downs in the squad's side.
    assert a["facts"]["squad"]["downs"] == [] and b["facts"]["squad"]["downs"] == []
    assert a["facts"]["first_rank"] == b["facts"]["first_rank"] == 1
    assert a["facts"]["squad"]["players_downed"] == 1
    assert a["facts"]["squad"]["players"] == 10


def test_pov_flag_and_player_fights_table(tmp_path: Path):
    squad = _squad()
    a, rows = _facts(squad)
    assert rows[_key(0)]["is_pov"]  # the factory's recorder is the first player
    assert sum(r["is_pov"] for r in rows.values()) == 1
    db = Database(tmp_path / "t.db")
    fid = db.add_fight("x.zevtc", None, None)
    db.save_analysis(fid, a.summary, a.stats, a.notes, a.facts)
    n = db._one("SELECT COUNT(*) AS n FROM player_fights WHERE fight_id=?", (fid,))["n"]
    assert n == 10
    db.save_analysis(fid, a.summary, a.stats, a.notes, a.facts[:3])  # replaces, not adds
    assert db._one("SELECT COUNT(*) AS n FROM player_fights")["n"] == 3
    db.set_skipped(fid, "too short", None)
    assert db._one("SELECT COUNT(*) AS n FROM player_fights")["n"] == 0
    db.save_analysis(fid, a.summary, a.stats, a.notes, a.facts)
    db.delete_fight(fid)
    assert db._one("SELECT COUNT(*) AS n FROM player_fights")["n"] == 0
