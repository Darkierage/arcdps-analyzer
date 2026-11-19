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
        gvg = m.timeline.gvg
        out: list[Finding] = []
        res = int(sum(r["resurrects"] for r in m.players))
        downed_heal = int(sum(r["downed_healing"] for r in m.players))
        # GvG: downs still open at the call-off were left by agreement, and kills after it are
        # not part of the fight, so both are taken out before judging downstate play.
        downs = s["squadDowns"] - s["squadDownsLeft"] - s["squadDownsLate"]
        deaths = s["squadDeaths"] - s["squadDeathsLate"]
        enemy_downs = s["enemyDowns"] - s["enemyDownsLeft"] - s["enemyDownsLate"]
        enemy_deaths = s["enemyDeaths"] - s["enemyDeathsLate"]
        if downs >= self.cfg["min_downs"]:
            rate = deaths / downs
            if rate >= self.cfg["max_own_death_rate"]:
                died = sum(1 for e in m.timeline.squad_downs
                           if e["died"] and not e["left"] and e["round"] is not None)
                # After a call-off both sides rez everyone, so the log's resurrect totals say
                # nothing about the fight itself; GvG notes leave them out.
                major = downs >= 10 and (gvg or res <= 0.2 * downs)
                out.append(self.finding(
                    "major" if major else "minor",
                    key="downstate_own_gvg" if gvg else "downstate_own",
                    impact=died * 0.15,  # often a consequence of a lost bomb, not the cause
                    evidence={"downs": downs, "deaths": deaths,
                              "rate": round(100 * rate), "resurrects": res,
                              "downed_healing": downed_heal,
                              "left": s["squadDownsLeft"], "left_note": _left_note(
                                  s["squadDownsLeft"], "of our downs")},
                ))
        if enemy_downs >= self.cfg["min_downs"]:
            conv = enemy_deaths / enemy_downs
            cleave = sum(r["against_downed"] for r in m.players)
            ev = {"enemy_downs": enemy_downs, "enemy_deaths": enemy_deaths,
                  "conversion": round(100 * conv), "escaped": enemy_downs - enemy_deaths,
                  "against_downed": int(cleave),
                  "cleave_share": round(100 * cleave / s["squadDamage"]) if s["squadDamage"] else 0,
                  "left": s["enemyDownsLeft"],
                  "left_note": _left_note(s["enemyDownsLeft"], "enemy downs")}
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


def _left_note(n: int, what: str) -> str:
    """GvG: say what was not counted ("" in zerg fights, where nothing is left)."""
    return f" {n} {what} left at the call-off are not counted." if n else ""
