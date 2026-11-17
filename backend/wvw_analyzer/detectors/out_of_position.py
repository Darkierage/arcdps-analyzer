"""Downs that happened far away from the commander / squad stack."""

from __future__ import annotations

from collections import Counter

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .util import down_weight


class OutOfPosition(Detector):
    name = "out_of_position"
    label = "Caught out of position"
    description = "Downs far from the tag or the squad's center (stragglers, backline caught)."
    defaults = {
        "far_tag": 1000,  # inches from the commander
        "far_stack": 800,  # inches from the squad's median position
        "min_downs": 2,
        "min_share": 0.2,  # share of all squad downs
    }

    def detect(self, m: Metrics) -> list[Finding]:
        downs = m.timeline.squad_downs
        if not downs:
            return []
        far = [
            e for e in downs
            if (e["dist_tag"] is not None and e["dist_tag"] > self.cfg["far_tag"])
            or (e["dist_stack"] is not None and e["dist_stack"] > self.cfg["far_stack"])
        ]
        if len(far) < self.cfg["min_downs"] or len(far) / len(downs) < self.cfg["min_share"]:
            return []
        who = Counter(e["player"] for e in far)
        repeat = [f"{n} ({c}x)" if c > 1 else n for n, c in who.most_common(5)]
        dists = sorted(max(e["dist_tag"] or 0, e["dist_stack"] or 0) for e in far)
        profs = Counter(e["profession"] for e in far).most_common(3)
        impact = sum(down_weight(e) for e in far)
        return [self.finding(
            "major" if len(far) / len(downs) >= 0.35 and len(far) >= 4 else "minor",
            impact=impact,
            subjects=list(who),
            evidence={
                "far_downs": len(far),
                "downs": len(downs),
                "share": round(100 * len(far) / len(downs)),
                "median_dist": int(dists[len(dists) // 2]),
                "players": ", ".join(repeat),
                "professions": ", ".join(p for p, _ in profs),
                "far_tag": self.cfg["far_tag"],
            },
        )]
