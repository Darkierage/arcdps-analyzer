"""The opening exchange was lost: several squad downs before the enemy lost anyone."""

from __future__ import annotations

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .util import down_weight, fmt_time, round_note


class EarlyCascade(Detector):
    name = "early_cascade"
    label = "Lost the opening"
    focus = {"early_cascade": {"tab": "defense", "column": "downs"}}
    description = (
        "Checks whether the squad suffered several downs early in the engagement before the "
        "enemy took any losses, which usually snowballs."
    )
    defaults = {
        "min_downs": 4,  # squad downs that define a lost opening
        "max_enemy_downs": 1,  # ... while the enemy had at most this many downs
        "window_s": 20.0,  # ... within this many seconds of the first squad down
    }

    def detect(self, m: Metrics) -> list[Finding]:
        # Every GvG round has its own opening; a zerg fight is one round.
        tl = m.timeline
        hits = [f for i in range(len(tl.rounds)) if (f := self._round(m, i)) is not None]
        if not hits:
            return []
        worst = max(hits, key=lambda f: f.impact)
        worst.evidence["round_note"] = round_note(len(hits), len(tl.rounds))
        return [worst]

    def _round(self, m: Metrics, i: int) -> Finding | None:
        tl = m.timeline
        downs = [e for e in tl.squad_downs if e["round"] == i]
        n = self.cfg["min_downs"]
        if len(downs) < n:
            return None
        t_first = downs[0]["t"]
        t_nth = downs[n - 1]["t"]
        if t_nth - t_first > self.cfg["window_s"]:
            return None
        enemy_before = sum(1 for e in tl.enemy_down_events if e["round"] == i and e["t"] <= t_nth)
        if enemy_before > self.cfg["max_enemy_downs"]:
            return None
        early = [e for e in downs if e["t"] <= t_nth]
        s = m.summary
        result = s["rounds"][i]["result"] if tl.gvg else s["result"]
        severity = "critical" if result == "loss" else "major"
        stab_ok = sum(1 for e in early if e["stab"] > 0)
        return self.finding(
            severity,
            impact=sum(down_weight(e) for e in early) * (1.5 if result == "loss" else 1.0),
            window=(max(t_first - 3, 0.0), t_nth),
            subjects=sorted({f"Party {e['group']}" for e in early}),
            evidence={
                "time": fmt_time(t_first),
                "downs": len(early),
                "seconds": round(t_nth - t_first, 1),
                "enemy_downs": enemy_before,
                "with_stab": stab_ok,
                "since_engage": round(t_first - tl.rounds[i].start, 1),
                "players": ", ".join(dict.fromkeys(e["player"] for e in early[:6])),
            },
        )
