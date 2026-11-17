"""Numbers context: how outnumbered the squad was."""

from __future__ import annotations

from ..metrics.summary import Metrics
from .base import Detector, Finding


class Outnumbered(Detector):
    name = "outnumbered"
    label = "Outnumbered"
    description = "Enemy count vs squad + allies, as seen in the log."
    defaults = {"ratio": 1.3, "hard_ratio": 1.7}

    def detect(self, m: Metrics) -> list[Finding]:
        s = m.summary
        ratio = s["outnumberRatio"]
        if not ratio or ratio < self.cfg["ratio"]:
            return []
        hard = ratio >= self.cfg["hard_ratio"]
        severity = "major" if hard and s["result"] == "loss" else "info"
        return [self.finding(
            severity,
            impact=(3.0 if hard else 1.0) if s["result"] in ("loss", "even") else 0.5,
            evidence={"enemies": s["enemyCount"], "squad": s["squadCount"],
                      "allies": s["allyCount"], "ratio": ratio},
        )]
