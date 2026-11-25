import numpy as np
import pytest

from factory import enemy, fight, player, zerg
from wvw_analyzer.analysis import Skipped, analyze_ei
from wvw_analyzer.config import Settings
from wvw_analyzer.detectors.boon_wipe import BoonWipe
from wvw_analyzer.detectors.early_cascade import EarlyCascade
from wvw_analyzer.detectors.stab_gap_deaths import StabGapDeaths
from wvw_analyzer.detectors.strip_balance import StripBalance
from wvw_analyzer.ingest.loader import clean_map_name, load_fight
from wvw_analyzer.metrics.summary import classify_result, compute_metrics
from wvw_analyzer.model.fight import interval_mask, sample_states


def test_sample_states_step_function():
    states = [[0, 0], [1000, 3], [2500, 1]]
    out = sample_states(states, np.array([0.0, 999, 1000, 2000, 2500, 9000]))
    assert out.tolist() == [0, 0, 3, 3, 1, 1]


def test_interval_mask():
    m = interval_mask([[1000, 2000]], np.array([500.0, 1000, 1999, 2000]))
    assert m.tolist() == [False, True, True, False]


def test_map_name_cleanup():
    assert clean_map_name("Detailed  Seared Borderlands") == "Seared Borderlands"
    assert clean_map_name("Detailed WvW - Eternal Battlegrounds") == "Eternal Battlegrounds"


def test_loader_squad_allies_enemies():
    d = zerg(6, enemies=12)
    d["players"].append(player("Pug", 0, not_in_squad=True))
    f = load_fight(d, "x")
    assert len(f.squad) == 6 and len(f.allies) == 1 and len(f.enemies) == 12
    assert f.commander is not None and f.commander.name == "Player 0"
    assert f.enemies[0].profession == "Scourge"


@pytest.mark.parametrize("own,enemy_deaths,expected", [
    (10, 30, "win"), (30, 10, "loss"), (10, 12, "even"), (0, 1, "skirmish"),
])
def test_classify_result(own, enemy_deaths, expected):
    assert classify_result(own, enemy_deaths) == expected


def test_remote_player_is_not_in_fight():
    d = zerg(8)
    d["players"].append(player("Scout", 3, pos_inches=(50_000.0, 50_000.0), damage_per_s=0))
    m = compute_metrics(load_fight(d, "x"))
    scout = m.player("Scout")
    assert scout is not None and scout["in_fight"] is False
    assert all(r["in_fight"] for r in m.players if r["name"] != "Scout")


def test_stab_coverage_series():
    m = compute_metrics(load_fight(zerg(6, stab_states=[[0, 0], [10_000, 3], [20_000, 0]]), "x"))
    stab = m.timeline.squad["stab"]
    assert stab[5] == 0 and stab[15] == 1.0 and stab[25] == 0


def test_stab_gap_detector_fires_without_stab():
    m = compute_metrics(load_fight(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "x"))
    found = StabGapDeaths().detect(m)
    assert len(found) == 1
    assert found[0].evidence["downs"] == 4 and found[0].evidence["nostab"] == 4


def test_stab_gap_detector_quiet_with_stab():
    m = compute_metrics(load_fight(
        zerg(10, stab_states=[[0, 5]], downs_at=[30, 30.5, 31, 31.5]), "x"))
    assert StabGapDeaths().detect(m) == []


def test_stab_gap_ignores_log_warmup():
    m = compute_metrics(load_fight(zerg(10, downs_at=[1, 1.2, 1.4, 1.6]), "x"))
    assert StabGapDeaths().detect(m) == []


def test_early_cascade():
    m = compute_metrics(load_fight(zerg(10, downs_at=[8, 9, 10, 11]), "x"))
    found = EarlyCascade().detect(m)
    assert found and found[0].evidence["downs"] == 4


def test_strip_balance_losing():
    d = zerg(10, strips=5, boons_lost=30)
    m = compute_metrics(load_fight(d, "x"))
    found = StripBalance().detect(m)
    assert found and found[0].severity in ("major", "minor") and found[0].key == "strip_balance"


def test_boon_wipe():
    wipe = [[0, 8], [30_000, 1]]
    m = compute_metrics(load_fight(
        zerg(10, downs_at=[31, 32, 33], boons_states=wipe), "x"))
    found = BoonWipe().detect(m)
    assert found and found[0].evidence["before"] == 8.0


def test_analyze_skips_small_fights():
    with pytest.raises(Skipped):
        analyze_ei(fight([player("A", 1)], [enemy(0)]), "x", Settings())


def test_analyze_end_to_end_renders_notes():
    a = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "x", Settings())
    titles = [f["title"] for f in a.notes["issues"]]
    mentioned = titles + [r for f in a.notes["issues"] for r in f["related"]]
    assert any("Stability gap" in t for t in mentioned)  # may be merged into the opening loss
    for f in a.notes["issues"]:
        assert "{" not in f["cause"] and "{" not in f["fix"]
    assert a.summary["topIssue"] == titles[0]


def test_detector_can_be_disabled():
    s = Settings(detectors={"stab_gap_deaths": {"enabled": False}})
    a = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "x", s)
    assert all(f["detector"] != "stab_gap_deaths" for f in a.notes["issues"] + a.notes["more"])


def test_stacking_boon_generation_has_pct_and_stacks():
    from wvw_analyzer.metrics.columns import COLUMNS_BY_KEY

    for source in ("selfBuffs", "groupBuffs", "offGroupBuffs", "squadBuffs"):
        pct = COLUMNS_BY_KEY[f"gen_{source}_1122_pct"]
        stacks = COLUMNS_BY_KEY[f"gen_{source}_1122"]
        assert (pct.fmt, pct.label) == ("pct", "Stability %")
        assert (stacks.fmt, stacks.label) == ("stacks", "Stability stacks")
    d = zerg(4)
    d["players"][0]["groupBuffs"] = [
        {"id": 1122, "buffData": [{"generation": 1.5, "generationPresence": 36.0}]}]
    m = compute_metrics(load_fight(d, "x"))
    row = m.players[0]
    assert row["gen_groupBuffs_1122_pct"] == 36.0 and row["gen_groupBuffs_1122"] == 1.5


def test_ranker_orders_by_severity_then_impact():
    from wvw_analyzer.detectors.base import Finding
    from wvw_analyzer.notes.ranker import rank

    def f(name: str, severity: str, impact: float) -> Finding:
        # Separate windows: nothing merges.
        return Finding(detector=name, severity=severity, impact=impact,
                       window=(impact * 100, impact * 100 + 1))

    out = rank([f("ctx", "info", 9.0), f("maj", "major", 8.0), f("min", "minor", 1.0),
                f("crit", "critical", 2.0), f("maj2", "major", 3.0), f("min2", "minor", 4.0)])
    order = [x.detector for x in out["issues"] + out["more"]]
    # A major with more impact than the critical, and a context note with more impact than
    # either minor, still come after them.
    assert order == ["crit", "maj", "maj2", "min2", "min", "ctx"]
    assert [x.detector for x in out["more"]] == ["ctx"]
