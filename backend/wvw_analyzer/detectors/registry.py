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


def check_overrides(overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validated detector overrides from Settings: known detectors and keys only, numbers of
    the default's type, never negative, and counts that default to 1 or more stay at least 1
    (a cleared field must not silently become 0). Raises ValueError with a readable message."""
    from ..coach.registry import RULES  # personal rules share the overrides (`me_*` names)

    by_name: dict[str, Any] = {cls.name: cls for cls in DETECTORS}
    by_name.update({cls.name: cls for cls in RULES})
    out: dict[str, dict[str, Any]] = {}
    for name, values in (overrides or {}).items():
        cls = by_name.get(name)
        if cls is None or not isinstance(values, dict):
            raise ValueError(f"unknown detector or rule {name!r}")
        clean: dict[str, Any] = {}
        for key, v in values.items():
            if key == "enabled":
                if not isinstance(v, bool):
                    raise ValueError(f"{name}.enabled must be true or false")
                clean[key] = v
                continue
            if key not in cls.defaults:
                raise ValueError(f"{name} has no setting {key!r}")
            default = cls.defaults[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                raise ValueError(f"{name}.{key} must be a number")
            if v < 0 or (isinstance(default, int) and default >= 1 and v < 1):
                raise ValueError(f"{name}.{key} is out of range ({v})")
            clean[key] = int(v) if isinstance(default, int) and float(v).is_integer() else v
        out[name] = clean
    return out


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


def focus_map() -> dict[str, dict[str, str]]:
    """Finding key -> {"tab", "column"} of the stat behind it (static detector metadata)."""
    return {k: v for cls in DETECTORS for k, v in cls.focus.items()}


def add_focus(notes: dict[str, Any] | None) -> dict[str, Any] | None:
    """Attach the focus stat to stored findings when serving them (no re-analysis needed)."""
    if not notes:
        return notes
    fm = focus_map()
    for bucket in ("issues", "more", "positives"):
        for f in notes.get(bucket) or []:
            f["focus"] = fm.get(f.get("key") or f.get("detector"))
    return notes


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
