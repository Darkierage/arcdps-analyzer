"""Healing could not keep up with incoming damage, typically late in the fight."""

from __future__ import annotations

import numpy as np

from ..metrics.summary import Metrics
from .base import Detector, Finding


class SustainDecline(Detector):
    name = "sustain_decline"
    label = "Sustain ran out"
    description = (
        "Compares healing + barrier against damage taken in the first and second half of the "
        "engagement (needs the arcdps healing addon)."
    )
    defaults = {
        "min_engage_s": 30.0,
        "drop": 0.35,  # relative drop of (heal+barrier)/damage-taken from first to second half
        "low_cover": 0.35,  # heal+barrier covering less than this share of damage overall
    }

    def detect(self, m: Metrics) -> list[Finding]:
        s = m.summary
        tl = m.timeline
        if not s["hasHealData"]:
            return []
        e0, e1 = int(tl.engage_start), int(tl.engage_end)
        if e1 - e0 < self.cfg["min_engage_s"]:
            return []
        mid = (e0 + e1) // 2
        sustain = tl.squad["healing"] + tl.squad["barrier"]
        dmg = tl.squad["dmg_in"]

        def cover(a: int, b: int) -> float | None:
            d = float(np.sum(dmg[a:b]))
            return float(np.sum(sustain[a:b])) / d if d > 0 else None

        c1, c2, call = cover(e0, mid), cover(mid, e1 + 1), cover(e0, e1 + 1)
        downs1 = sum(1 for e in tl.squad_downs if e0 <= e["t"] < mid)
        downs2 = sum(1 for e in tl.squad_downs if mid <= e["t"] <= e1 + 1)
        healers = sorted(m.players, key=lambda r: -r["healing"])[:3]
        ev = {
            "cover_first": None if c1 is None else round(100 * c1),
            "cover_second": None if c2 is None else round(100 * c2),
            "cover_all": None if call is None else round(100 * call),
            "downs_first": downs1,
            "downs_second": downs2,
            "healing": int(s["squadHealing"]),
            "top_healers": ", ".join(f"{r['name']} ({int(r['healing'] / 1000)}k)"
                                     for r in healers if r["healing"] > 0),
            "half_time": f"{mid // 60}:{mid % 60:02d}",
        }
        if c1 and c2 is not None and (c1 - c2) / c1 >= self.cfg["drop"] and downs2 > downs1:
            return [self.finding("major", impact=(downs2 - downs1) * 0.6, window=(mid, e1),
                                 evidence=ev)]
        if call is not None and call < self.cfg["low_cover"] and s["squadDowns"] >= 5:
            return [self.finding("minor", key="sustain_low", impact=s["squadDowns"] * 0.15,
                                 evidence=ev)]
        return []
