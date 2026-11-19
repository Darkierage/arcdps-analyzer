"""Strip war: boons we removed from enemies vs boons they removed from us."""

from __future__ import annotations

from ..metrics.summary import Metrics
from .base import Detector, Finding


class StripBalance(Detector):
    name = "strip_balance"
    label = "Losing the strip war"
    description = (
        "Compares outgoing strips with boons stripped from the squad, and how concentrated the "
        "stripping was."
    )
    defaults = {
        "min_enemies": 10,
        "lost_ratio": 1.3,  # boons lost / strips above this = losing the strip war
        "win_ratio": 1.5,  # strips / boons lost above this = positive
        "stripper_share": 0.2,  # a 'stripper' does >= this share of the top stripper's strips
        "min_strips_per_enemy_min": 4.0,  # strips per enemy per minute of engagement
    }

    def detect(self, m: Metrics) -> list[Finding]:
        s = m.summary
        if s["enemyCount"] < self.cfg["min_enemies"]:
            return []
        strips, lost = s["squadStrips"], s["squadBoonsLost"]
        engage_min = max(s["fightS"] / 60.0, 0.25)
        per_enemy_min = strips / (s["enemyCount"] * engage_min)
        top = max((r["strips"] for r in m.players), default=0)
        strippers = sorted(
            (r for r in m.players if top and r["strips"] >= self.cfg["stripper_share"] * top),
            key=lambda r: -r["strips"],
        )
        ev = {
            "strips": int(strips),
            "boons_lost": int(lost),
            "ratio": round(lost / strips, 1) if strips else None,
            "per_enemy_min": round(per_enemy_min, 1),
            "strippers": len(strippers),
            "top_strippers": ", ".join(f"{r['name']} ({int(r['strips'])})" for r in strippers[:3]),
        }
        losing = (strips == 0 and lost > 20) or (strips and lost / strips >= self.cfg["lost_ratio"])
        low = per_enemy_min < self.cfg["min_strips_per_enemy_min"]
        if losing or (low and s["result"] in ("loss", "even")):
            impact = min(s["squadDowns"] * 0.25, 6.0) * (1.0 if losing else 0.6)
            return [self.finding("major" if losing else "minor", impact=impact,
                                 subjects=[r["name"] for r in strippers[:3]], evidence=ev)]
        if strips and strips / max(lost, 1) >= self.cfg["win_ratio"]:
            return [self.finding("positive", key="strip_balance_good", impact=1.0, evidence=ev)]
        return []
