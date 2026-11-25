"""The personal review as the API serves it: a scope of one player's fights, the advice, the
numbers next to the peers' and the squad's, and the player's downs.

- `fight`: what happened to you here. No habits from one fight: each down gets the hint that
  matches it, and this fight's numbers sit next to the peers' and the squad's.
- `session`: the rules with the session's lower gates.
- `profile`: several sessions or all fights, full gates and a trend per advice.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ..notes.templates import render
from .base import Advice, Rule
from .data import FightView, build_views
from .registry import build
from .review import run_rules
from .rules import CaughtAlone, DownFar, DownNoStab

# The numbers table: metric (in the facts' peers), label, unit, higher is better (None: no
# direction). Per-minute metrics are per minute of the player's time in the fight.
NUMBERS: list[tuple[str, str, str, bool | None]] = [
    ("damage", "Damage", "/min", True),
    ("down_contribution", "Down contribution", "/min", True),
    ("strips", "Strips", "/min", True),
    ("cleanses", "Cleanses", "/min", True),
    ("healing", "Healing", "/min", True),
    ("stab", "Stability given (squad)", "stacks", True),
    ("stab_up", "Stability uptime", "%", True),
    ("cast", "Cast time without auto-attacks", "%", True),
    ("cancel_s", "Cancelled casts", "s/min", False),
    ("damage_taken", "Damage taken", "/min", False),
    ("cc_taken", "CC received", "/min", False),
    ("dodges", "Dodges", "/min", None),
    ("deaths", "Deaths", "/min", False),
    ("dist_tag", "Distance to tag", "", False),
]
RECENT_DOWNS = 12
TREND_CHANGE = 0.1  # a number's latest third differs from the rest by this share


def _cause_rules(overrides: dict[str, dict[str, Any]] | None) -> dict[str, Rule]:
    """The down-cause rules with the Settings' thresholds (on or off as advice, the split and
    the hints use their definitions)."""
    return {r.name: r for r in build(overrides)
            if r.name in (DownNoStab.name, DownFar.name, CaughtAlone.name)}


def down_hint(d: dict[str, Any], rules: dict[str, Rule] | None = None) -> dict[str, Any]:
    """The one hint that matches a down, most specific first. Never a claim about a habit.
    `rules` carry the thresholds (the defaults when left out)."""
    rules = rules or _cause_rules(None)
    if d.get("left") or d.get("after_calloff"):
        key = "me_hint_calloff"
    elif rules[DownNoStab.name].counts(d) and rules[DownNoStab.name].hit(d):
        key = "me_hint_no_stab"
    elif rules[DownFar.name].counts(d) and rules[DownFar.name].hit(d):
        key = "me_hint_far"
    elif rules[CaughtAlone.name].hit(d):
        key = "me_hint_alone"
    elif d.get("hp_before") is not None and d["hp_before"] < 50:
        key = "me_hint_low_hp"
    elif d["near"] >= 3:
        key = "me_hint_bomb"
    else:
        key = "me_hint_burst"
    ev = {"time": _clock(d["t"]), "stab": d["stab"], "near": d["near"],
          "party_stab": "?" if d.get("party_stab") is None else d["party_stab"],
          "dist_tag": "?" if d.get("dist_tag") is None else d["dist_tag"],
          "hp_before": "?" if d.get("hp_before") is None else d["hp_before"]}
    a = render(Advice(detector="me_hint", key=key, severity="info", evidence=ev))
    return {"key": key, "title": a.title, "cause": a.cause, "fix": a.fix}


def _clock(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


def _wmean(pairs: list[tuple[float | None, float]]) -> float | None:
    known = [(v, w) for v, w in pairs if v is not None and w > 0]
    total = sum(w for _, w in known)
    return sum(v * w for v, w in known) / total if total else None


def numbers(views: list[FightView], with_trend: bool = False) -> list[dict[str, Any]]:
    """You, your peers (same spec and job) and the squad, weighted by your time in each fight;
    peers only over fights that had any."""
    out = []
    cut = len(views) - math.ceil(len(views) / 3)
    for key, label, unit, better in NUMBERS:
        you = _wmean([(v.facts["peers"][key][0], v.active_s) for v in views])
        peer_views = [v for v in views if v.facts["peers"][key][2]]
        item: dict[str, Any] = {
            "key": key, "label": label, "unit": unit, "higherIsBetter": better,
            "you": _round(you),
            "peers": _round(_wmean([(v.facts["peers"][key][1], v.active_s)
                                    for v in peer_views])),
            "peerFights": len(peer_views),
            "squad": _round(_wmean([(v.facts["peers"][key][3], v.active_s) for v in views])),
            "trend": None,
        }
        if with_trend and len(views) >= 6 and better is not None:
            old = _wmean([(v.facts["peers"][key][0], v.active_s) for v in views[:cut]])
            new = _wmean([(v.facts["peers"][key][0], v.active_s) for v in views[cut:]])
            if old is not None and new is not None and (old or new):
                change = (new - old) / max(abs(old), 1e-9)
                item["trend"] = ("same" if abs(change) < TREND_CHANGE else
                                 "better" if (change > 0) == better else "worse")
        if you is not None or item["squad"] is not None:
            out.append(item)
    return out


def _round(v: float | None) -> float | None:
    if v is None:
        return None
    return round(v, 2) if abs(v) < 10 else round(v, 1) if abs(v) < 100 else round(v)


def down_split(views: list[FightView], rules: dict[str, Rule] | None = None
               ) -> list[dict[str, Any]]:
    """How your downs split next to the rest of the squad's split in the same fights."""
    rules = rules or _cause_rules(None)
    out = []
    far = rules[DownFar.name]
    alone = rules[CaughtAlone.name]
    for rule, label in (
            (rules[DownNoStab.name], "no stability while the party had it"),
            (far, f"over {far.cfg['far_tag']} from the tag"),
            (alone, f"at most {alone.cfg['max_near']} other squad down(s) within 4 s")):
        c = rule._counts(views)
        out.append({"key": rule.name, "label": label, "you": c["k"], "of": c["n"],
                    "squadExpected": round(c["exp"], 1)})
    mine = [d for v in views for d in v.downs]
    theirs = [d for v in views for d in v.squad_downs]
    out.append({"key": "died", "label": "ended in death",
                "you": sum(1 for d in mine if d["died"]), "of": len(mine),
                "squadExpected": round(len(mine) * sum(1 for d in theirs if d["died"])
                                       / len(theirs), 1) if theirs else None})
    return out


def _down_item(v: FightView, d: dict[str, Any], rules: dict[str, Rule]) -> dict[str, Any]:
    return {"fightId": v.fight_id, "start": v.start, "map": v.map, "key": d.get("key"),
            **{k: d.get(k) for k in ("t", "stab", "party_stab", "dist_tag", "near", "died",
                                     "hp_before", "rank", "recap", "left", "after_calloff")},
            "hint": down_hint(d, rules)}


def _scope_info(views: list[FightView], kind: str) -> dict[str, Any]:
    specs = Counter(v.main["profession"] for v in views)
    starts = [v.start for v in views if v.start]
    return {"kind": kind, "fights": len(views),
            "sessions": len({v.session_id for v in views if v.session_id is not None}),
            "from": min(starts) if starts else None, "to": max(starts) if starts else None,
            "specs": [{"spec": s, "fights": n} for s, n in specs.most_common()],
            "commanderFights": sum(1 for v in views if v.commander),
            "activeS": round(sum(v.active_s for v in views))}


def select(rows: list[dict[str, Any]], fights: dict[int, dict[str, Any]], *,
           fight: int | None = None, session: int | None = None, sessions: int | None = None,
           start: str | None = None, end: str | None = None,
           profession: str | None = None) -> tuple[list[FightView], str]:
    """The fights in a scope, oldest first, and the scope's kind."""
    if fight is not None:
        views = build_views([r for r in rows if r["fight_id"] == fight], fights)
        kind = "fight"
    else:
        views = build_views(rows, fights)
        kind = "profile"
        if session is not None:
            views = [v for v in views if v.session_id == session]
            kind = "session"
        elif sessions:
            latest: dict[int, str] = {}
            for v in views:
                if v.session_id is not None:
                    latest[v.session_id] = max(latest.get(v.session_id, ""), v.start or "")
            keep = set(sorted(latest, key=lambda s: (latest[s], s), reverse=True)[:sessions])
            views = [v for v in views if v.session_id in keep]
            kind = "session" if sessions == 1 else "profile"
        if start:
            views = [v for v in views if (v.start or "") >= start]
        if end:
            views = [v for v in views if (v.start or "")[:len(end)] <= end]
    if profession:
        views = [v for v in views if v.main["profession"] == profession]
    return views, kind


def review(account: str, rows: list[dict[str, Any]], fights: dict[int, dict[str, Any]],
           overrides: dict[str, dict[str, Any]] | None = None, **scope: Any) -> dict[str, Any]:
    views, kind = select(rows, fights, **scope)
    rules = _cause_rules(overrides)
    names = Counter(r["name"] for r in rows if r["in_fight"])
    all_specs = Counter(r["profession"] for r in rows if r["in_fight"])
    out: dict[str, Any] = {
        "account": account,
        "name": names.most_common(1)[0][0] if names else account,
        "allSpecs": [s for s, _ in all_specs.most_common()],
        "scope": _scope_info(views, kind),
        "numbers": numbers(views, with_trend=kind == "profile"),
        "downSplit": down_split(views, rules),
    }
    downs = [(v, d) for v in views for d in v.downs]
    out["downCount"] = len(downs)
    out["deathCount"] = sum(1 for _, d in downs if d["died"])
    if kind == "fight":
        out["fight"] = _fight_recap(views[0], rules) if views else None
        out["advice"] = None
        out["gates"] = []
        return out
    rev = run_rules(views, kind, overrides)
    out["advice"] = {k: rev[k] for k in ("work", "more", "keep", "nothing")}
    out["gates"] = rev["gates"]
    out["recentDowns"] = [_down_item(v, d, rules) for v, d in reversed(downs[-RECENT_DOWNS:])]
    return out


def _fight_recap(v: FightView, rules: dict[str, Rule]) -> dict[str, Any]:
    main = v.main
    f = main["facts"]
    left = [{**d, "key": r["key"]} for r in v.rows for d in r["facts"].get("downs_left", [])]
    downs = sorted(v.downs + left, key=lambda d: d["t"])
    return {
        "fightId": v.fight_id, "start": v.start, "map": v.map, "result": v.result,
        "mode": v.mode, "key": main["key"], "spec": main["profession"],
        "specs": v.specs, "job": f.get("job"), "commander": v.commander, "pov": v.pov,
        "activeS": round(v.active_s), "deadS": round(v.dead_s),
        "food": v.flag("food"), "utility": v.flag("utility"),
        "cancels": sum(r["facts"].get("cancels") or 0 for r in v.rows),
        "firstRank": v.first_rank,
        "squad": {k: v.squad.get(k) for k in ("players", "downs_total", "players_downed")},
        "downs": [_down_item(v, d, rules) for d in downs],
        "dealt": f.get("dealt"), "taken": f.get("taken"),
    }
