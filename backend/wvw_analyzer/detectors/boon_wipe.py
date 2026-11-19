"""Sudden squad-wide boon loss (enemy strip / corrupt bomb) followed by downs."""

from __future__ import annotations

import numpy as np

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .util import LOG_WARMUP_S, down_weight, fmt_time


class BoonWipe(Detector):
    name = "boon_wipe"
    label = "Enemy strip bomb"
    focus = {"boon_wipe": {"tab": "defense", "column": "incoming_strips"}}
    description = (
        "Detects moments where the squad's average boon count collapsed within seconds and downs "
        "followed (enemy strips/corrupts landing)."
    )
    defaults = {
        "drop_window_s": 2,  # boons compared against this many seconds earlier
        "min_drop": 0.4,  # relative drop of average boons per player
        "min_boons_before": 4.0,  # ignore drops from an already boonless squad
        "followup_s": 5.0,  # downs counted within this time after the drop
        "min_followup_downs": 2,
    }

    def detect(self, m: Metrics) -> list[Finding]:
        tl = m.timeline
        boons = tl.squad.get("boons")
        if boons is None or len(boons) < 4:
            return []
        w = int(self.cfg["drop_window_s"])
        events = []
        last_t = -1e9
        for i in range(w, len(boons)):
            before, after = boons[i - w], boons[i]
            if not (np.isfinite(before) and np.isfinite(after)):
                continue
            if before < self.cfg["min_boons_before"] or tl.t[i - w] < LOG_WARMUP_S:
                continue
            drop = (before - after) / before
            if drop < self.cfg["min_drop"] or tl.t[i] - last_t < self.cfg["followup_s"]:
                continue
            t = float(tl.t[i])
            downs = [e for e in tl.squad_downs if t - w <= e["t"] <= t + self.cfg["followup_s"]]
            if len(downs) < self.cfg["min_followup_downs"]:
                continue
            last_t = t
            events.append({"t": t, "before": float(before), "after": float(after),
                           "downs": downs, "impact": sum(down_weight(e) for e in downs)})
        if not events:
            return []
        worst = max(events, key=lambda e: e["impact"])
        s = m.summary
        return [self.finding(
            "major" if worst["impact"] >= 3 else "minor",
            impact=sum(e["impact"] for e in events) * 0.8,  # overlaps with stab gaps
            window=(worst["t"] - w, worst["t"] + self.cfg["followup_s"]),
            evidence={
                "time": fmt_time(worst["t"]),
                "before": round(worst["before"], 1),
                "after": round(worst["after"], 1),
                "downs": len(worst["downs"]),
                "count": len(events),
                "times": ", ".join(fmt_time(e["t"]) for e in events),
                "boons_lost": int(s["squadBoonsLost"]),
                "strips": int(s["squadStrips"]),
            },
        )]
