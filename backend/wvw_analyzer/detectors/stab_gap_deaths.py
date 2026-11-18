"""Down clusters (enemy bombs) that hit parties with poor stability coverage."""

from __future__ import annotations

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .util import LOG_WARMUP_S, clusters, down_weight, fmt_time, pct, window_mean


class StabGapDeaths(Detector):
    name = "stab_gap_deaths"
    label = "Stability gap during enemy bomb"
    description = (
        "Finds bursts of squad downs and checks the stability coverage of the affected parties "
        "in the seconds before."
    )
    defaults = {
        "cluster_gap_s": 4.0,  # downs closer than this belong to the same bomb
        "max_span_s": 8.0,  # a single bomb lasts at most this long
        "min_downs": 3,  # downs in a cluster to consider it a bomb
        "lookback_s": 3.0,  # stab coverage window before the first down
        "max_coverage": 0.5,  # party stab coverage below this is a gap
        "min_nostab_share": 0.6,  # or this share of downed players had no stab
    }

    def detect(self, m: Metrics) -> list[Finding]:
        tl = m.timeline
        flagged = []
        for cl in clusters(tl.squad_downs, self.cfg["cluster_gap_s"], self.cfg["max_span_s"]):
            if len(cl) < self.cfg["min_downs"]:
                continue
            t0, t1 = cl[0]["t"], cl[-1]["t"]
            if t0 - self.cfg["lookback_s"] < LOG_WARMUP_S:
                continue  # boon states not known yet (log started mid-fight)
            parties = sorted({e["group"] for e in cl})
            party_cov = {
                g: window_mean(tl.parties[g]["stab"], t0 - self.cfg["lookback_s"], t0)
                for g in parties
                if g in tl.parties
            }
            nostab = [e for e in cl if e["stab"] <= 0]
            nostab_share = len(nostab) / len(cl)
            gap_parties = [g for g, c in party_cov.items() if c is not None
                           and c < self.cfg["max_coverage"]]
            if not gap_parties and nostab_share < self.cfg["min_nostab_share"]:
                continue
            flagged.append({
                "t0": t0, "t1": t1, "downs": len(cl), "nostab": len(nostab),
                "deaths": sum(1 for e in cl if e["died"]),
                "parties": gap_parties or parties, "party_cov": party_cov,
                "gap": bool(gap_parties),
                "impact": sum(down_weight(e) for e in nostab) + 0.5 * sum(
                    down_weight(e) for e in cl if e["stab"] > 0 and e["group"] in gap_parties),
            })
        if not flagged:
            return []
        worst = max(flagged, key=lambda c: c["impact"])
        impact = sum(c["impact"] for c in flagged)
        total_downs = max(len(tl.squad_downs), 1)
        severity = "critical" if impact >= 0.3 * total_downs and worst["downs"] >= 5 else "major"
        cov = [c for c in worst["party_cov"].values() if c is not None]
        parties = ", ".join(
            f"{g} ({pct(worst['party_cov'].get(g))}%)" for g in worst["parties"]
        )
        # Either parties really lacked stab (a coverage gap), or coverage was fine but the downed
        # players had none at that moment (stripped / ran out) - different notes.
        key = self.name if worst["gap"] else f"{self.name}_nostab"
        times = ", ".join(fmt_time(c["t0"]) for c in flagged)
        return [self.finding(
            severity,
            key=key,
            impact=impact,
            window=(max(worst["t0"] - self.cfg["lookback_s"], 0.0), worst["t1"]),
            subjects=[f"Party {g}" for g in worst["parties"]],
            evidence={
                "time": fmt_time(worst["t0"]),
                "parties": parties,
                "coverage": pct(min(cov) if cov else None),
                "downs": worst["downs"],
                "nostab": worst["nostab"],
                "deaths": worst["deaths"],
                "bombs": len(flagged),
                "bomb_times": ", ".join(fmt_time(c["t0"]) for c in flagged),
                "repeat_txt": "" if len(flagged) == 1 else
                f" It happened {len(flagged)} times ({times}).",
            },
        )]
