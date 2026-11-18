"""Players far below others of the same profession in that profession's main job."""

from __future__ import annotations

import statistics
from collections import defaultdict

from ..metrics.summary import Metrics
from .base import Detector, Finding

# Metrics compared within a profession; the one where the profession's median is strongest
# relative to the squad's median is treated as that profession's job in this fight.
CANDIDATES = {
    "damage": "damage",
    "strips": "strips",
    "cleanses": "cleanses",
    "healing": "healing",
    "gen_squadBuffs_1122": "stability given",
}
# Minimum profession median (per engagement minute; stab generation is already a rate) for a
# metric to count as that profession's job.
MIN_MEDIAN_PER_MIN = {
    "damage": 40_000,
    "strips": 8,
    "cleanses": 15,
    "healing": 60_000,
    "gen_squadBuffs_1122": 0.15,
}


class PlayerOutliers(Detector):
    name = "player_outliers"
    label = "Underperforming in role"
    description = (
        "Compares each player with others of the same profession on that profession's main "
        "output in this fight, plus distance to the tag."
    )
    defaults = {
        "min_squad": 10,
        "min_same_prof": 2,
        "below_median": 0.35,  # below this share of the profession median
        "min_active_share": 0.5,  # ignore players present less than this share of the fight
        "far_factor": 2.5,  # distance to tag above this multiple of the squad median ...
        "min_far_dist": 900,  # ... and above this many inches
        "max_listed": 6,
    }

    def detect(self, m: Metrics) -> list[Finding]:
        dur = max(m.summary["durationS"], 1)
        engage = m.summary["engage"]
        engage_min = max((engage[1] - engage[0]) / 60.0, 0.25)
        rows = [
            r for r in m.active_players
            if not r["is_commander"] and r["active_s"] >= self.cfg["min_active_share"] * dur
        ]
        if len(rows) < self.cfg["min_squad"]:
            return []
        by_prof: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_prof[r["profession"]].append(r)
        squad_med = {k: statistics.median([r[k] for r in rows]) if rows else 0
                     for k in CANDIDATES}
        flagged: list[str] = []
        for prof, members in by_prof.items():
            if len(members) < self.cfg["min_same_prof"]:
                continue
            best_key, best_rel = None, 0.0
            for k in CANDIDATES:
                med = statistics.median([r[k] for r in members])
                if med < MIN_MEDIAN_PER_MIN[k] * (1 if k.startswith("gen_") else engage_min):
                    continue  # too little output for this to be the profession's job here
                rel = med / squad_med[k] if squad_med[k] else 10.0
                if rel > best_rel:
                    best_key, best_rel = k, rel
            if not best_key:
                continue
            med = statistics.median([r[best_key] for r in members])
            for r in members:
                if r[best_key] < self.cfg["below_median"] * med:
                    flagged.append(
                        f"{r['name']} ({prof}): {CANDIDATES[best_key]} {_short(r[best_key])} "
                        f"vs {_short(med)} median"
                    )
        # Distance to tag while alive during the engagement (not EI's whole-log average, which
        # includes running back from spawn).
        dists = [r["fight_dist_tag"] for r in rows if r.get("fight_dist_tag")]
        if dists:
            dmed = statistics.median(dists)
            for r in rows:
                d = r.get("fight_dist_tag")
                if d and d > self.cfg["far_factor"] * dmed and d > self.cfg["min_far_dist"]:
                    flagged.append(f"{r['name']} ({r['profession']}): usually {int(d)} from "
                                   f"tag vs {int(dmed)} squad median")
        if not flagged:
            return []
        return [self.finding(
            "minor",
            impact=min(len(flagged) * 0.3, 2.0),
            subjects=[f.split(" (")[0] for f in flagged],
            evidence={"count": len(flagged),
                      "count_txt": "1 player was" if len(flagged) == 1
                      else f"{len(flagged)} players were",
                      "players": "; ".join(flagged[: self.cfg["max_listed"]])},
        )]


def _short(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 10_000:
        return f"{v / 1000:.0f}k"
    if v < 10 and v != int(v):
        return f"{v:.2f}"
    return f"{int(v)}"
