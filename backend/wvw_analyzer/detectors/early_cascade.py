"""The opening exchange was lost: several squad downs before the enemy lost anyone."""

from __future__ import annotations

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .util import down_weight, fmt_time


class EarlyCascade(Detector):
    name = "early_cascade"
    label = "Lost the opening"
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
        tl = m.timeline
        downs = tl.squad_downs
        n = self.cfg["min_downs"]
        if len(downs) < n:
            return []
        t_first = downs[0]["t"]
        t_nth = downs[n - 1]["t"]
        if t_nth - t_first > self.cfg["window_s"]:
            return []
        enemy_before = sum(1 for t in tl.enemy_downs if t <= t_nth)
        if enemy_before > self.cfg["max_enemy_downs"]:
            return []
        early = [e for e in downs if e["t"] <= t_nth]
        s = m.summary
        severity = "critical" if s["result"] == "loss" else "major"
        stab_ok = sum(1 for e in early if e["stab"] > 0)
        return [self.finding(
            severity,
            impact=sum(down_weight(e) for e in early) * (1.5 if s["result"] == "loss" else 1.0),
            window=(max(t_first - 3, 0.0), t_nth),
            subjects=sorted({f"Party {e['group']}" for e in early}),
            evidence={
                "time": fmt_time(t_first),
                "downs": len(early),
                "seconds": round(t_nth - t_first, 1),
                "enemy_downs": enemy_before,
                "with_stab": stab_ok,
                "since_engage": round(t_first - tl.engage_start, 1),
                "players": ", ".join(dict.fromkeys(e["player"] for e in early[:6])),
            },
        )]
