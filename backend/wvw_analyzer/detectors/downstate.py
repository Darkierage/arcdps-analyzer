"""Downstate play: allied downs not rallied/ressed, enemy downs not finished."""

from __future__ import annotations

from ..metrics.summary import Metrics
from .base import Detector, Finding


class Downstate(Detector):
    name = "downstate"
    label = "Downstate play"
    description = (
        "How many of our downs turned into deaths (rez / rally) and how many enemy downs we "
        "converted into kills (cleaving downs)."
    )
    defaults = {
        "min_downs": 5,
        "max_own_death_rate": 0.8,  # our deaths / our downs above this = downs not picked up
        "min_enemy_conversion": 0.6,  # enemy deaths / enemy downs below this = downs escaped
        "good_conversion": 0.85,
    }

    def detect(self, m: Metrics) -> list[Finding]:
        s = m.summary
        out: list[Finding] = []
        res = int(sum(r["resurrects"] for r in m.players))
        downed_heal = int(sum(r["downed_healing"] for r in m.players))
        if s["squadDowns"] >= self.cfg["min_downs"]:
            rate = s["squadDeaths"] / s["squadDowns"]
            if rate >= self.cfg["max_own_death_rate"]:
                died = sum(1 for e in m.timeline.squad_downs if e["died"])
                out.append(self.finding(
                    "major" if s["squadDowns"] >= 10 and res <= 0.2 * s["squadDowns"] else "minor",
                    key="downstate_own",
                    impact=died * 0.15,  # often a consequence of a lost bomb, not the cause
                    evidence={"downs": s["squadDowns"], "deaths": s["squadDeaths"],
                              "rate": round(100 * rate), "resurrects": res,
                              "downed_healing": downed_heal},
                ))
        if s["enemyDowns"] >= self.cfg["min_downs"]:
            conv = s["enemyDeaths"] / s["enemyDowns"]
            cleave = sum(r["against_downed"] for r in m.players)
            ev = {"enemy_downs": s["enemyDowns"], "enemy_deaths": s["enemyDeaths"],
                  "conversion": round(100 * conv), "escaped": s["enemyDowns"] - s["enemyDeaths"],
                  "against_downed": int(cleave),
                  "cleave_share": round(100 * cleave / s["squadDamage"]) if s["squadDamage"] else 0}
            if conv < self.cfg["min_enemy_conversion"]:
                out.append(self.finding(
                    "major" if ev["escaped"] >= 5 else "minor",
                    key="downstate_enemy",
                    impact=ev["escaped"] * 0.4,
                    evidence=ev,
                ))
            elif conv >= self.cfg["good_conversion"]:
                out.append(self.finding("positive", key="downstate_enemy_good", impact=1.0,
                                        evidence=ev))
        return out
