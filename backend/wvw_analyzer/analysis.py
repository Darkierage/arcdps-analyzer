"""EI JSON -> metrics -> findings -> ranked notes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import FilterSettings, Settings
from .detectors import registry
from .ingest.loader import is_wvw, load_fight, read_ei_json
from .metrics.summary import Metrics, compute_metrics
from .model.fight import Fight
from .notes import ranker
from .notes.templates import render

ANALYZER_VERSION = 1


class Skipped(Exception):
    """The log is valid but not a fight worth analyzing (PvE, too short, too small)."""

    def __init__(self, reason: str, summary: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.summary = summary


@dataclass
class Analysis:
    summary: dict[str, Any]
    stats: dict[str, Any]
    notes: dict[str, Any]


def skip_reason(fight: Fight, f: FilterSettings) -> str | None:
    if fight.duration_s < f.min_duration_s:
        return f"too short ({fight.duration_s:.0f}s < {f.min_duration_s:.0f}s)"
    if len(fight.enemies) < f.min_enemies:
        return f"too few enemies ({len(fight.enemies)} < {f.min_enemies})"
    if len(fight.squad) < f.min_squad:
        return f"squad too small ({len(fight.squad)} < {f.min_squad})"
    return None


def notes_for(m: Metrics, settings: Settings) -> dict[str, Any]:
    findings = registry.run_all(m, registry.build(settings.detectors))
    for f in findings:
        render(f)
    ranked = ranker.rank(findings)
    return {k: [f.model_dump(mode="json") for f in v] for k, v in ranked.items()}


def analyze_ei(data: dict[str, Any], log_id: str, settings: Settings) -> Analysis:
    if not is_wvw(data):
        raise Skipped("not a WvW log", {"map": data.get("fightName"),
                                        "start": data.get("timeStartStd")})
    fight = load_fight(data, log_id=log_id)
    reason = skip_reason(fight, settings.filters)
    if reason:
        raise Skipped(reason, {
            "logId": log_id, "map": fight.map_name, "start": fight.start_time,
            "durationS": round(fight.duration_s, 1), "squadCount": len(fight.squad),
            "enemyCount": len(fight.enemies),
        })
    m = compute_metrics(fight)
    notes = notes_for(m, settings)
    summary = dict(m.summary)
    top = notes["issues"][0] if notes["issues"] else None
    summary["topIssue"] = top["title"] if top else None
    summary["topSeverity"] = top["severity"] if top else None
    summary["analyzerVersion"] = ANALYZER_VERSION
    return Analysis(summary=summary, stats=m.stats_json(), notes=notes)


def analyze_file(path: Path, settings: Settings) -> Analysis:
    return analyze_ei(read_ei_json(path), path.name.split("_")[0], settings)
