"""All detectors, in a stable order, configured from settings overrides."""

from __future__ import annotations

import logging
from typing import Any

from ..metrics.summary import Metrics
from .base import Detector, Finding
from .boon_wipe import BoonWipe
from .cleanse_pressure import CleansePressure
from .comp_audit import CompAudit
from .downstate import Downstate
from .early_cascade import EarlyCascade
from .out_of_position import OutOfPosition
from .outnumbered import Outnumbered
from .player_outliers import PlayerOutliers
from .stab_gap_deaths import StabGapDeaths
from .strip_balance import StripBalance
from .sustain_decline import SustainDecline

log = logging.getLogger(__name__)

DETECTORS: list[type[Detector]] = [
    StabGapDeaths,
    BoonWipe,
    StripBalance,
    OutOfPosition,
    EarlyCascade,
    CleansePressure,
    Downstate,
    SustainDecline,
    CompAudit,
    Outnumbered,
    PlayerOutliers,
]


def build(overrides: dict[str, dict[str, Any]] | None = None) -> list[Detector]:
    overrides = overrides or {}
    return [cls(overrides.get(cls.name)) for cls in DETECTORS]


def describe(overrides: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = []
    for det in build(overrides):
        d = det.describe()
        d["enabled"] = det.enabled
        d["config"] = det.cfg
        out.append(d)
    return out


def run_all(m: Metrics, detectors: list[Detector]) -> list[Finding]:
    findings: list[Finding] = []
    for det in detectors:
        if not det.enabled:
            continue
        try:
            findings.extend(det.detect(m))
        except Exception:  # a broken detector must not break the whole analysis
            log.exception("detector %s failed on %s", det.name, m.fight.log_id)
    return findings
