"""Per-party boon series over time (the fight page's Boons tab chart)."""

from factory import enemy, fight, player
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.config import Settings
from wvw_analyzer.metrics.timeline import TIMELINE_BOONS

QUICKNESS, MIGHT, STEALTH = 1187, 740, 13017


def _analyze():
    party1 = [
        # Quickness all fight; downed from 10 s to 20 s (doesn't count while down).
        player("Ann One", 1, buffs={QUICKNESS: [[0, 1]], MIGHT: [[0, 10]]},
               downs=[[10_000, 20_000]]),
        player("Bob One", 1, buffs={QUICKNESS: [[0, 1]], MIGHT: [[0, 20]]}),
        player("Cid One", 1),
        player("Dan One", 1, commander=True),
    ]
    # Party 2: a lone player, dead from 30 s on (nobody up in that party then).
    party2 = [player("Eve Two", 2, buffs={QUICKNESS: [[0, 1]]}, deaths=[[30_000, 60_000]])]
    others = [player(f"Fill {i}", 3) for i in range(5)]
    return analyze_ei(fight(party1 + party2 + others, [enemy(j) for j in range(10)]), "x",
                      Settings())


def test_party_boon_coverage_and_stacks():
    tl = _analyze().stats["timeline"]
    t = tl["t"]
    p1 = tl["boons"]["1"]
    at = {s: t.index(s) for s in (5, 15, 40)}
    assert p1[str(QUICKNESS)][at[5]] == 50  # 2 of 4 up members
    assert p1[str(QUICKNESS)][at[15]] == 33  # Ann is down: 1 of 3
    assert p1[f"{MIGHT}s"][at[5]] == 7.5  # (10 + 20 + 0 + 0) / 4 up members
    p2 = tl["boons"]["2"]
    assert p2[str(QUICKNESS)][at[5]] == 100 and p2[str(QUICKNESS)][at[40]] is None


def test_every_boon_but_stealth_for_squad_and_each_party():
    tl = _analyze().stats["timeline"]
    assert set(tl["boons"]) == {"squad", "1", "2", "3"}
    ids = {str(b) for b in TIMELINE_BOONS}
    assert str(STEALTH) not in ids and {b for b, _ in tl["boonNames"]} == ids
    assert tl["boonNames"][0] == ["1122", "Stability"]  # display order, not sorted ids
    for series in tl["boons"].values():
        assert ids <= set(series)
        assert {"1122s", f"{MIGHT}s"} <= set(series)  # stacking boons: average stacks too
        assert all(len(v) == len(tl["t"]) for v in series.values())
