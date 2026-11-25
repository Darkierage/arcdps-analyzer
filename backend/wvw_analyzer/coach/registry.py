"""All personal rules, in a stable order, configured from the Settings overrides.

The rules share `Settings.detectors` with the fight detectors (their names start with `me_`),
so the same validation and the same Settings list cover both.
"""

from __future__ import annotations

from typing import Any

from .base import Rule
from .rules import (
    CaughtAlone,
    CcTaken,
    DownFar,
    DownNoStab,
    DownRate,
    FarFromTag,
    FirstDown,
    LowActivity,
    LowOutput,
    NoFood,
)

RULES: list[type[Rule]] = [
    DownRate,
    DownNoStab,
    DownFar,
    CaughtAlone,
    FirstDown,
    FarFromTag,
    LowOutput,
    LowActivity,
    CcTaken,
    NoFood,
]


def build(overrides: dict[str, dict[str, Any]] | None = None) -> list[Rule]:
    overrides = overrides or {}
    return [cls(overrides.get(cls.name)) for cls in RULES]


def describe(overrides: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = []
    for rule in build(overrides):
        d = rule.describe()
        d["enabled"] = rule.enabled
        d["config"] = rule.cfg
        out.append(d)
    return out
