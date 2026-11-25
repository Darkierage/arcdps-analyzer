"""Personal rules (coach/): gates, baselines, trend, same fight twice, split rows, templates."""

import string

import pytest

from wvw_analyzer.coach.base import Scope
from wvw_analyzer.coach.data import build_views
from wvw_analyzer.coach.registry import RULES
from wvw_analyzer.coach.review import run_rules, trend
from wvw_analyzer.coach.rules import (
    CaughtAlone,
    CcTaken,
    DownFar,
    DownNoStab,
    DownRate,
    FarFromTag,
    FirstDown,
    LowActivity,
    LowOutput,
    NoFood,
)
from wvw_analyzer.detectors import registry as detector_registry
from wvw_analyzer.metrics.personal import PEER_METRICS
from wvw_analyzer.notes.templates import templates

ME = "Me.1234"
PROFILE, SESSION = Scope("profile"), Scope("session")


def down(t=10.0, stab=5, party_stab=100, dist_tag=200, near=3, died=True):
    return {"t": t, "stab": stab, "party_stab": party_stab, "dist_tag": dist_tag,
            "dist_stack": 100, "conditions": 0, "boons": 0, "died": died, "hp_before": 100,
            "near": near, "rank": 1}


def sq_down(stab=5, party_stab=100, dist_tag=200, near=3, died=False):
    return [stab, party_stab, dist_tag, near, int(died)]


def facts(*, downs=(), squad_downs=(), active=600.0, others_active=6000.0, spec="Firebrand",
          job="damage", peers=None, spec_peers=None, food=True, utility=True, first_rank=None,
          downs_total=None, players_downed=10, cast=40.0, party_stab_up=50.0):
    p = {k: [1.0, 1.0, 3, 1.0] for k in PEER_METRICS}
    p.update(peers or {})
    p["cast"] = [cast, cast, 3, cast] if "cast" not in (peers or {}) else p["cast"]
    return {
        "v": 1, "mode": "zerg", "dur_s": active, "active_s": active, "spec": spec, "job": job,
        "eligible": True, "dead_s": 0, "downed_s": 0, "cast": cast, "cancels": 0,
        "cancel_s": 0, "dodges": 0, "food": food, "utility": utility, "downs": list(downs),
        "downs_left": [], "first_rank": first_rank,
        "squad": {"players": 20, "downs_total": len(squad_downs) + len(downs)
                  if downs_total is None else downs_total,
                  "players_downed": players_downed, "active_s": others_active, "dead_s": 0,
                  "downs": list(squad_downs), "party_stab_up": party_stab_up},
        "peers": p,
        "spec_peers": spec_peers if spec_peers is not None else {job: [3, 1.0, cast, 0]},
        "dealt": None, "taken": None,
    }


def row(fid, f, *, key=ME, account=ME, commander=False, pov=False, active=None, spec=None):
    return {"fight_id": fid, "key": key, "account": account, "name": "Me",
            "profession": spec or f["spec"], "party": 1, "is_pov": pov,
            "is_commander": commander, "in_fight": True,
            "active_s": f["active_s"] if active is None else active, "facts": f}


def meta(n, dur=600.0, gap_min=15):
    """Fights 15 min apart, from 2026-11-17 18:00 (over as many days as it takes)."""
    out = {}
    for i in range(n):
        m = 18 * 60 + i * gap_min
        day, hh, mm = 17 + m // 1440, (m % 1440) // 60, m % 60
        out[i] = {"start": f"2026-11-{day:02d} {hh:02d}:{mm:02d}:00 +01:00", "dur_s": dur,
                  "session_id": 1}
    return out


def views(rows, n=None):
    n = n or (max(r["fight_id"] for r in rows) + 1)
    return build_views(rows, meta(n))


ALL_ON = {cls.name: {"enabled": True} for cls in RULES}


def run(rule, vs, scope=PROFILE):
    out = rule.run(vs, scope)
    return out, [a.key for a in out.advice]


# ---- survival ------------------------------------------------------------------------------


def _rate_fights(n, mine, theirs):
    """n fights of 10 min; `mine` downs each for you, the squad's others `theirs` in 100 min
    (10 others): the squad's rate predicts theirs / 10 downs per fight for you."""
    return views([row(i, facts(downs=[down(t=10 + j) for j in range(mine)],
                                squad_downs=[sq_down() for _ in range(theirs)]))
                  for i in range(n)])


def test_down_rate_at_the_squads_rate_does_not_fire():
    out, keys = run(DownRate(), _rate_fights(10, 1, 10))  # 10 downs, the squad's rate: 10
    assert keys == [] and out.gates == []


def test_down_rate_well_above_fires_and_below_is_a_strength():
    _, keys = run(DownRate(), _rate_fights(10, 2, 10))  # 20 against 10
    assert keys == ["me_deaths"]
    _, keys = run(DownRate(), _rate_fights(10, 0, 10))  # 0 against 10
    assert keys == ["me_survivor"]


def test_down_rate_gates():
    out, keys = run(DownRate(), _rate_fights(4, 3, 10))
    assert keys == [] and "needs 5 fights, has 4" in out.gates[0]["need"]
    out, keys = run(DownRate(), _rate_fights(5, 0, 2))  # 0 downs, predicts 1: too little
    assert keys == [] and "needs 3 downs" in out.gates[0]["need"]
    _, keys = run(DownRate(), _rate_fights(5, 2, 0))  # 10 downs, the squad never goes down
    assert keys == ["me_deaths"]
    # The session gate is half the profile's (rounded up): 3 fights.
    _, keys = run(DownRate(), _rate_fights(3, 3, 10), SESSION)
    assert keys == ["me_deaths"]


def test_down_rate_names_a_spec_that_stands_out_on_its_own():
    rows = [row(i, facts(spec="Reaper", squad_downs=[sq_down() for _ in range(10)]))
            for i in range(20)]
    rows += [row(20 + i, facts(spec="Chronomancer", downs=[down(t=j) for j in range(3)],
                               squad_downs=[sq_down() for _ in range(10)]))
             for i in range(10)]
    out, keys = run(DownRate(), views(rows))  # all fights: 30 against 30; Chronomancer: 30/10
    assert keys == ["me_deaths"] and out.advice[0].spec == "Chronomancer"
    assert out.advice[0].evidence["downs"] == 30 and out.advice[0].evidence["fights"] == 10


@pytest.mark.parametrize("rule,hit,miss", [
    (DownNoStab(), {"stab": 0, "party_stab": 100}, {"stab": 5, "party_stab": 100}),
    (DownFar(), {"dist_tag": 1500}, {"dist_tag": 300}),
    (CaughtAlone(), {"near": 0}, {"near": 4}),
])
def test_down_causes_are_judged_against_the_squads_share(rule, hit, miss):
    def fights(my_hits, my_total, sq_share):
        rows = []
        for i in range(my_total):
            sq = [sq_down(**_sq(hit)) for _ in range(sq_share)]
            sq += [sq_down(**_sq(miss)) for _ in range(10 - sq_share)]
            mine = down(**(hit if i < my_hits else miss))
            rows.append(row(i, facts(downs=[mine], squad_downs=sq)))
        return views(rows)

    # Half of your downs, half of the squad's: the same as the squad, never a finding.
    assert run(rule, fights(5, 10, 5))[1] == []
    # Clearly above the squad in the same fights.
    _, keys = run(rule, fights(9, 10, 2))
    assert keys == [rule.name]
    # Above, but too few downs to judge: silent, with what is missing.
    out, keys = run(rule, fights(5, 5, 0))
    assert keys == [] and out.gates[0]["need"] == "needs 6 downs, has 5"


def _sq(d):
    return {"stab": d.get("stab", 5), "party_stab": d.get("party_stab", 100),
            "dist_tag": d.get("dist_tag", 200), "near": d.get("near", 3)}


def test_no_stab_only_counts_when_the_party_had_it():
    rows = [row(i, facts(downs=[down(stab=0, party_stab=0)],
                         squad_downs=[sq_down(stab=5)] * 9)) for i in range(10)]
    assert run(DownNoStab(), views(rows))[1] == []


def test_first_down_against_chance():
    def fights(firsts):
        return views([row(i, facts(downs=[down()], first_rank=1 if i < firsts else 9,
                                   downs_total=12, players_downed=10,
                                   squad_downs=[sq_down()] * 11)) for i in range(10)])

    assert run(FirstDown(), fights(3))[1] == []  # chance: 3 of 10 each fight
    assert run(FirstDown(), fights(9))[1] == ["me_first_down"]
    small = views([row(i, facts(downs=[down()], first_rank=1, downs_total=5,
                                squad_downs=[sq_down()] * 4)) for i in range(10)])
    out, keys = run(FirstDown(), small)  # fights with fewer than 6 squad downs don't count
    assert keys == [] and "has 0" in out.gates[0]["need"]


# ---- play -----------------------------------------------------------------------------------


def test_far_from_tag_in_most_fights_and_not_when_leading():
    def fights(far, commander=False):
        return views([row(i, facts(peers={"dist_tag": [600 if i < far else 210, 200, 3, 200]}),
                          commander=commander) for i in range(10)])

    assert run(FarFromTag(), fights(5))[1] == []
    assert run(FarFromTag(), fights(7))[1] == ["me_far_from_tag"]
    out, keys = run(FarFromTag(), fights(10, commander=True))
    assert keys == [] and "has 0" in out.gates[0]["need"]


def _output(ratios, job="strips", n_peers=3, rows_job=None):
    return views([row(i, facts(job=rows_job[i] if rows_job else job, spec="Reaper",
                               peers={"strips": [10 * r, 10, n_peers, 5]},
                               spec_peers={job: [n_peers, 10.0, 40.0, 0.5]}))
                  for i, r in enumerate(ratios)])


def test_low_output_against_same_spec_same_job_peers():
    assert run(LowOutput(), _output([1.0] * 8))[1] == []
    _, keys = run(LowOutput(), _output([0.5] * 8))
    assert keys == ["me_low_output"]
    _, keys = run(LowOutput(), _output([1.6] * 8))
    assert keys == ["me_top_output"]
    out, keys = run(LowOutput(), _output([0.5] * 8, n_peers=1))  # fewer than 2 peers
    assert keys == [] and out.gates[0]["spec"] == "Reaper"


def test_low_output_counts_the_fights_where_a_row_got_another_job():
    # Main job strips (5 of 8 fights); in the 3 others the row came out as damage because
    # its strips were low. They still count, against that fight's strip Reapers.
    jobs = ["strips"] * 5 + ["damage"] * 3
    out, keys = run(LowOutput(), _output([1.0, 1.0, 0.5, 0.5, 0.5, 0.4, 0.4, 0.4],
                                         rows_job=jobs))
    assert keys == ["me_low_output"] and out.advice[0].evidence["peer_fights"] == 8
    assert out.advice[0].evidence["off_job"] == 3


def test_output_needs_a_clear_main_job():
    out, keys = run(LowOutput(), _output([0.5] * 8, rows_job=["strips", "damage"] * 4))
    assert keys == [] and out.gates[0]["need"] == "no clear main job on Reaper"


def test_low_activity():
    def fights(cast):
        return views([row(i, facts(cast=cast, spec_peers={"damage": [3, 1.0, 40.0, 0.5]}))
                      for i in range(8)])

    assert run(LowActivity(), fights(40.0))[1] == []
    assert run(LowActivity(), fights(20.0))[1] == ["me_low_activity"]
    assert run(LowActivity(), fights(60.0))[1] == ["me_active"]


def test_cc_taken_needs_low_stability_too():
    def fights(stab_up):
        return views([row(i, facts(peers={"cc_taken": [3.0, 1.0, 3, 1.0],
                                          "stab_up": [stab_up, 50, 3, 50]}, party_stab_up=50))
                      for i in range(8)])

    assert run(CcTaken(), fights(50))[1] == []
    assert run(CcTaken(), fights(20))[1] == ["me_cc_taken"]


def test_no_food():
    def fights(missing):
        return views([row(i, facts(utility=i >= missing)) for i in range(8)])

    assert run(NoFood(), fights(1))[1] == []
    out, keys = run(NoFood(), fights(4))
    assert keys == ["me_no_food"] and out.advice[0].evidence["no_utility"] == 4


# ---- views, review, trend --------------------------------------------------------------------


def test_same_fight_twice_keeps_the_players_own_log():
    f = facts(downs=[down()])
    rows = [row(0, f, active=500), row(1, facts(), pov=True, active=400)]
    fights = {0: {"start": "2026-11-17 20:00:00 +01:00", "dur_s": 600},
              1: {"start": "2026-11-17 20:00:05 +01:00", "dur_s": 590},
              2: {"start": "2026-11-17 20:30:00 +01:00", "dur_s": 600}}
    vs = build_views(rows + [row(2, facts())], fights)
    assert [v.fight_id for v in vs] == [1, 2]


def test_split_rows_are_one_player_in_one_fight():
    a = facts(downs=[down(t=20)], active=400)
    b = facts(downs=[down(t=50)], active=100, spec="Scourge")
    vs = views([row(0, a), row(0, b, key=ME + "#2")])
    assert len(vs) == 1
    v = vs[0]
    assert v.active_s == 500 and [d["t"] for d in v.downs] == [20, 50]
    assert v.main["key"] == ME and set(v.specs) == {"Firebrand", "Scourge"}


def test_trend_compares_the_latest_third_with_the_rest():
    rows = [row(i, facts(downs=[down()] * (1 if i < 10 else 3),
                         squad_downs=[sq_down()] * 10)) for i in range(15)]
    assert trend(DownRate(), views(rows)) == "worse"
    rows = [row(i, facts(downs=[down()] * (3 if i < 10 else 0),
                         squad_downs=[sq_down()] * 10)) for i in range(15)]
    assert trend(DownRate(), views(rows)) == "better"
    rows = [row(i, facts(downs=[down()], squad_downs=[sq_down()] * 10)) for i in range(15)]
    assert trend(DownRate(), views(rows)) == "same"
    assert trend(DownRate(), views(rows[:4])) is None  # parts below the gate


def test_nothing_stands_out_is_a_result():
    rows = [row(i, facts(downs=[down()], squad_downs=[sq_down()] * 10)) for i in range(10)]
    out = run_rules(views(rows))
    assert out["work"] == [] and out["nothing"]["title"] == "Nothing stands out in 10 fights"


def test_review_ranks_by_impact_and_names_the_cause():
    rows = [row(i, facts(downs=[down(t=j, stab=0) for j in range(3)], utility=False,
                         squad_downs=[sq_down()] * 10)) for i in range(10)]
    out = run_rules(views(rows), overrides=ALL_ON)
    keys = [a["key"] for a in out["work"] + out["more"]]
    assert keys[0] == "me_deaths" and "me_down_no_stab" in keys and "me_no_food" in keys
    deaths = out["work"][0]
    assert "downs without stability" in deaths["cause"]
    assert deaths["trend"] == "same" and deaths["examples"][0]["fightId"] == 9
    assert out["nothing"] is None


def test_weak_rules_are_off_by_default_but_still_name_the_cause():
    rows = [row(i, facts(downs=[down(t=j, stab=0) for j in range(3)],
                         squad_downs=[sq_down()] * 10)) for i in range(10)]
    out = run_rules(views(rows))
    keys = [a["key"] for a in out["work"] + out["more"]]
    assert keys == ["me_deaths"]
    assert "downs without stability" in out["work"][0]["cause"]
    on = {r.name for r in RULES if r().enabled}
    assert on == {"me_deaths", "me_low_output", "me_low_activity", "me_no_food"}


def test_overrides_cover_the_rules():
    ok = detector_registry.check_overrides({"me_deaths": {"ratio": 2, "enabled": False}})
    assert ok == {"me_deaths": {"ratio": 2, "enabled": False}}
    with pytest.raises(ValueError):
        detector_registry.check_overrides({"me_deaths": {"nope": 1}})
    rows = [row(i, facts(downs=[down()] * 2, squad_downs=[sq_down()] * 10)) for i in range(10)]
    assert "me_deaths" in [a["key"] for a in run_rules(views(rows))["work"]]
    off = run_rules(views(rows), overrides={"me_deaths": {"enabled": False}})
    assert "me_deaths" not in [a["key"] for a in off["work"]]


def _all_advice():
    """One advice for every template key a rule can produce."""
    out = []
    out += run(DownRate(), _rate_fights(10, 2, 10))[0].advice
    out += run(DownRate(), _rate_fights(10, 0, 10))[0].advice
    out += _test_spec_down()
    for rule, kw in ((DownNoStab(), {"stab": 0}), (DownFar(), {"dist_tag": 1500}),
                     (CaughtAlone(), {"near": 0})):
        rows = [row(i, facts(downs=[down(**{**{"near": 4}, **kw})],
                             squad_downs=[sq_down()] * 10)) for i in range(10)]
        out += run(rule, views(rows))[0].advice
    out += run(FirstDown(), views([row(i, facts(downs=[down()], first_rank=1, downs_total=12,
                                                squad_downs=[sq_down()] * 11))
                                   for i in range(10)]))[0].advice
    out += run(FarFromTag(), views([row(i, facts(peers={"dist_tag": [600, 200, 3, 200]}))
                                    for i in range(8)]))[0].advice
    out += run(LowOutput(), _output([0.5] * 8))[0].advice
    out += run(LowOutput(), _output([1.6] * 8))[0].advice
    for cast in (20.0, 60.0):
        out += run(LowActivity(), views([row(i, facts(
            cast=cast, spec_peers={"damage": [3, 1.0, 40.0, 0.5]})) for i in range(8)]))[0].advice
    out += run(CcTaken(), views([row(i, facts(peers={"cc_taken": [3.0, 1.0, 3, 1.0],
                                                     "stab_up": [20, 50, 3, 50]}))
                                 for i in range(8)]))[0].advice
    out += run(NoFood(), views([row(i, facts(food=False)) for i in range(8)]))[0].advice
    return out


def _test_spec_down():
    rows = [row(i, facts(spec="Reaper", squad_downs=[sq_down()] * 10)) for i in range(20)]
    rows += [row(20 + i, facts(spec="Chronomancer", downs=[down(t=j) for j in range(3)],
                               squad_downs=[sq_down()] * 10)) for i in range(10)]
    return run(DownRate(), views(rows))[0].advice


def test_every_personal_template_has_its_placeholders_in_the_evidence():
    advice = _all_advice()
    produced = {a.key for a in advice}
    keys = {k for k in templates() if k.startswith("me_") and k != "me_nothing"
            and not k.startswith("me_hint_")}
    assert keys == produced, keys ^ produced
    rules = {r.name for r in RULES}
    for a in advice:
        assert a.detector in rules
        tpl = templates()[a.key]
        for part in ("title", "cause", "fix"):
            for _, field, _, _ in string.Formatter().parse(tpl.get(part, "")):
                if field:
                    assert field in a.evidence, (a.key, part, field)
    assert all(f in ("scope_txt", "fights") for _, f, _, _ in
               string.Formatter().parse(templates()["me_nothing"]["title"]) if f)


# ---- review fixes (2026-11-25) ----------------------------------------------------------------


def test_tails_stay_exact_on_long_profiles():
    from wvw_analyzer.coach.stats import binom_sf, poisson_cdf, poisson_sf

    # Plain floats overflowed (math.comb of 1,000+ downs) or underflowed (exp(-mu), mu > 745).
    assert 0 < binom_sf(309, 1030, 0.2) < 1e-10
    assert 0 < poisson_sf(1200, 760) < 1e-40
    assert poisson_sf(600, 760) == pytest.approx(1.0)
    assert 0 < poisson_cdf(600, 760) < 1e-8
    # Small cases keep their values.
    assert poisson_sf(10, 3) == pytest.approx(0.0011025, rel=1e-4)
    assert binom_sf(3, 10, 0.2) == pytest.approx(0.3222005, rel=1e-6)


def test_a_long_profile_fires_and_names_its_causes():
    # 400 fights, 4 downs each without stability, against a squad rate of 2 per fight: the
    # squad's rate predicts 800 downs (exp(-800) underflowed), and 1,600 downs overflowed
    # the binomial tail of the cause check (a 500 for the whole review).
    rows = [row(i, facts(downs=[down(t=j, stab=0) for j in range(4)],
                         squad_downs=[sq_down()] * 20)) for i in range(400)]
    out = run_rules(views(rows))
    assert [a["key"] for a in out["work"]] == ["me_deaths"]
    assert "downs without stability" in out["work"][0]["cause"]


def test_down_hints_use_the_rules_thresholds():
    from wvw_analyzer.coach.report import _cause_rules, down_hint

    d = {**down(dist_tag=1200, near=4), "t": 30.0}
    assert down_hint(d)["key"] == "me_hint_far"
    assert down_hint(d, _cause_rules({"me_down_far": {"far_tag": 1500}}))["key"] == "me_hint_bomb"
    unknown = {**down(stab=0, near=4), "party_stab": None, "t": 30.0}
    assert down_hint(unknown)["key"] == "me_hint_bomb"  # no party stability known: no claim
