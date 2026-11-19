"""Condition pressure the squad's cleanses / resistance couldn't handle."""

from __future__ import annotations

import numpy as np

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .util import pct, window_mean

# Calibrated on real fights: up players averaged ~0.4 conditions in won fights vs ~1.4 in lost
# ones, so the defaults sit between the two.


class CleansePressure(Detector):
    name = "cleanse_pressure"
    label = "Condition pressure"
    focus = {"cleanse_pressure": {"tab": "support", "column": "cleanses"}}
    description = (
        "The squad carried many conditions during the fight and players went down covered in "
        "conditions."
    )
    defaults = {
        "high_conditions": 1.0,  # average conditions per up player during the engagement
        "down_conditions": 4,  # a down 'under condition pressure' carries at least this many
        "min_condi_downs": 3,
        "high_condi_share": 0.35,  # or: share of damage taken that was condition damage
        "min_downs": 3,  # ... but only in fights where the squad actually suffered downs
    }

    def detect(self, m: Metrics) -> list[Finding]:
        tl = m.timeline
        s = m.summary
        e0, e1 = tl.engage_start, tl.engage_end
        conds = window_mean(tl.squad.get("conditions"), e0, e1)
        resist = window_mean(tl.squad.get("resist"), e0, e1)
        if conds is None:
            return []
        series = tl.squad["conditions"]
        finite = np.isfinite(series)
        peak_i = int(np.nanargmax(series)) if finite.any() else 0
        peak = float(series[peak_i]) if finite.any() else 0.0
        condi_taken = sum(r["condi_taken"] for r in m.players)
        share = condi_taken / s["squadDamageTaken"] if s["squadDamageTaken"] else 0.0
        condi_downs = sum(1 for e in tl.squad_downs
                          if e["conditions"] >= self.cfg["down_conditions"])
        pressured = conds >= self.cfg["high_conditions"] and \
            condi_downs >= self.cfg["min_condi_downs"]
        if not pressured and (share < self.cfg["high_condi_share"]
                              or s["squadDowns"] < self.cfg["min_downs"]):
            return []
        cleansers = sorted(m.players, key=lambda r: -r["cleanses"])[:3]
        return [self.finding(
            "major" if condi_downs >= 6 or share >= 0.5 else "minor",
            impact=condi_downs * 0.5 + (1.0 if share >= self.cfg["high_condi_share"] else 0),
            window=(max(peak_i - 3, 0), peak_i + 2),
            evidence={
                "avg_conditions": round(conds, 1),
                "peak_conditions": round(peak, 1),
                "resist": pct(resist),
                "condi_share": round(100 * share),
                "cleanses": int(s["squadCleanses"]),
                "downs_high_condi": condi_downs,
                "down_conditions": self.cfg["down_conditions"],
                "top_cleansers": ", ".join(f"{r['name']} ({int(r['cleanses'])})"
                                           for r in cleansers),
            },
        )]
