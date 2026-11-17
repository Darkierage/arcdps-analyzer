"""Party composition: parties without stability / cleanse / healing sources."""

from __future__ import annotations

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .util import pct, window_mean


class CompAudit(Detector):
    name = "comp_audit"
    label = "Party composition gaps"
    description = (
        "Flags parties whose members had almost no stability, cleanses or healing - usually a "
        "party without its support - and players left in tiny parties."
    )
    defaults = {
        "low_stab_coverage": 0.25,
        "min_party_size": 3,  # parties smaller than this count as 'unsupported'
        "low_cleanse_share": 0.25,  # party cleanses vs the average party
    }

    def detect(self, m: Metrics) -> list[Finding]:
        tl = m.timeline
        out: list[Finding] = []
        e0, e1 = tl.engage_start, tl.engage_end
        big = [p for p in m.active_parties if p["members"] >= self.cfg["min_party_size"]]
        avg_cleanse = (sum(p["cleanses"] for p in big) / len(big)) if big else 0
        gaps = []
        for p in big:
            g = p["group"]
            cov = window_mean(tl.parties.get(g, {}).get("stab"), e0, e1)
            missing = []
            if cov is not None and cov < self.cfg["low_stab_coverage"]:
                missing.append(f"little stability ({pct(cov)}% coverage)")
            if avg_cleanse and p["cleanses"] < self.cfg["low_cleanse_share"] * avg_cleanse:
                missing.append(f"low cleanses ({int(p['cleanses'])} vs {int(avg_cleanse)} avg)")
            if m.summary["hasHealData"] and p["healing"] <= 0:
                missing.append("no healing")
            if missing:
                downs = sum(1 for e in tl.squad_downs if e["group"] == g)
                gaps.append((g, missing, downs, p["professions"]))
        if gaps:
            gaps.sort(key=lambda x: -x[2])
            lines = "; ".join(f"Party {g}: {', '.join(miss)}" for g, miss, _, _ in gaps)
            out.append(self.finding(
                "major" if any(d >= 6 for _, _, d, _ in gaps) else "minor",
                impact=sum(d for _, _, d, _ in gaps) * 0.25,
                subjects=[f"Party {g}" for g, *_ in gaps],
                evidence={"gaps": lines, "parties": ", ".join(str(g) for g, *_ in gaps),
                          "downs": sum(d for _, _, d, _ in gaps),
                          "professions": " | ".join(
                              f"{g}: {', '.join(pr)}" for g, _, _, pr in gaps)},
            ))
        small = [p for p in m.active_parties if p["members"] < self.cfg["min_party_size"]]
        loners = sum(p["members"] for p in small)
        if loners >= 2 and len(m.active_players) >= 10:
            out.append(self.finding(
                "minor", key="comp_audit_loners", impact=loners * 0.2,
                subjects=[f"Party {p['group']}" for p in small],
                evidence={"players": loners,
                          "parties": ", ".join(str(p["group"]) for p in small)},
            ))
        return out
