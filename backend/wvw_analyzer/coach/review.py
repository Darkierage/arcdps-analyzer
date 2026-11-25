"""Run the personal rules over one player's fights: ranked advice, gates and trends."""

from __future__ import annotations

import logging
import math
from typing import Any

from ..notes.templates import render
from .base import Advice, Rule, Scope
from .data import FightView
from .registry import build
from .rules import CAUSE_RULES, DownRate

log = logging.getLogger(__name__)

MAX_WORK = 3  # "Work on": the top 3; the rest is under "more"
MAX_KEEP = 2  # "Keep doing"
CAUSE_TXT = {
    "me_down_no_stab": "downs without stability while your party had it",
    "me_down_far": "downs far from the tag",
    "me_caught_alone": "being caught alone",
    "me_first_down": "going down among the first",
}


def run_rules(views: list[FightView], kind: str = "profile",
              overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    scope = Scope(kind)  # type: ignore[arg-type]
    every = build(overrides)
    rules = [r for r in every if r.enabled]
    advice: list[Advice] = []
    gates: list[dict[str, Any]] = []
    by_name: dict[str, Rule] = {r.name: r for r in rules}
    for rule in rules:
        try:
            out = rule.run(views, scope)
        except Exception:  # a broken rule must not break the review
            log.exception("personal rule %s failed", rule.name)
            continue
        advice += out.advice
        gates += out.gates
    _name_causes(advice, every, views, scope)
    _lead_with_the_rate(advice)
    if kind == "profile":
        for a in advice:
            a.trend = trend(by_name[a.detector], views, a.spec)
    for a in advice:
        render(a)
    work = sorted((a for a in advice if a.severity != "positive"),
                  key=lambda a: (-a.impact, a.key, a.spec or ""))
    keep = sorted((a for a in advice if a.severity == "positive"),
                  key=lambda a: (-a.impact, a.key, a.spec or ""))
    return {
        "work": [a.model_dump(mode="json") for a in work[:MAX_WORK]],
        "more": [a.model_dump(mode="json") for a in work[MAX_WORK:]],
        "keep": [a.model_dump(mode="json") for a in keep[:MAX_KEEP]],
        "gates": gates,
        "nothing": _nothing(views, scope) if not work else None,
    }


def _name_causes(advice: list[Advice], rules: list[Rule], views: list[FightView],
                 scope: Scope) -> None:
    """The down rate names whichever cause stands out in the same fights (or says none
    does): all fights, or for a spec that stands out on its own, that spec's fights."""
    # The cause rules are asked even when they are off as advice of their own (by default).
    cause_rules = [r for r in rules if r.name in CAUSE_RULES]
    for a in advice:
        if a.key != "me_deaths":
            continue
        sub = views if a.spec is None else DownRate.by_spec(views).get(a.spec, [])
        fired = []
        for r in cause_rules:
            try:
                fired += [x.key for x in r.run(sub, scope).advice]
            except Exception:  # as in run_rules: one broken rule must not break the review
                log.exception("personal rule %s failed", r.name)
        causes = [CAUSE_TXT[k] for k in fired]
        a.evidence["causes_txt"] = (
            f" What stands out: {', '.join(causes)}." if causes else
            " None of the usual causes (stability, distance to the tag, being caught alone, "
            "going down first) stands out against the squad.")


def _lead_with_the_rate(advice: list[Advice]) -> None:
    """Survival is led by one rate; the causes only explain it. When the down rate fired, a
    cause ranks right after it (a cause's own excess is against the squad's share of downs,
    a different baseline, and can look bigger than the rate's)."""
    lead = max((a.impact for a in advice if a.key == "me_deaths"), default=None)
    if lead is None:
        return
    for a in advice:
        if a.key in CAUSE_RULES and a.impact >= lead:
            a.impact = round(max(lead - 0.01, 0.0), 2)


def _nothing(views: list[FightView], scope: Scope) -> dict[str, Any]:
    a = Advice(detector="me_nothing", key="me_nothing", severity="info",
               evidence={"scope_txt": scope.txt(len(views)), "fights": len(views)})
    return render(a).model_dump(mode="json")


def trend(rule: Rule, views: list[FightView], spec: str | None = None) -> str | None:
    """The latest third of the fights against the rest, when both parts pass the rule's gate
    (at the session's lower gate)."""
    pool = [v for v in views if spec is None or spec in v.specs]
    if len(pool) < 3:
        return None
    cut = len(pool) - math.ceil(len(pool) / 3)
    part = Scope("session")
    old, new = rule.measure(pool[:cut], part, spec), rule.measure(pool[cut:], part, spec)
    if old is None or new is None:
        return None
    margin = max(rule.trend_margin, rule.trend_margin * abs(old))
    delta = new - old if rule.lower_is_better else old - new
    if delta > margin:
        return "worse"
    if delta < -margin:
        return "better"
    return "same"
