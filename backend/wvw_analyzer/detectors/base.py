"""Detector interface and the Finding schema."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..metrics.summary import Metrics

Severity = Literal["critical", "major", "minor", "positive", "info"]
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3, "positive": 4}


class Finding(BaseModel):
    detector: str
    key: str = ""  # template key, defaults to detector name
    severity: Severity
    impact: float = 0.0  # roughly "downs/deaths explained"; used for ranking
    window: tuple[float, float] | None = None  # fight seconds
    subjects: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    cause: str = ""
    fix: str = ""
    short: str = ""  # one-line fact for chat / the LLM debrief
    fix_short: str = ""
    related: list[str] = Field(default_factory=list)  # titles of merged findings


class Detector:
    """Subclasses implement ``detect``; must be pure and deterministic."""

    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    defaults: ClassVar[dict[str, Any]] = {}
    # Template key -> the fight-page stat that best shows the evidence: {"tab", "column"} and
    # optionally "sort": "asc" when the lowest values matter (default: highest first).
    focus: ClassVar[dict[str, dict[str, str]]] = {}

    def __init__(self, overrides: dict[str, Any] | None = None):
        overrides = overrides or {}
        self.enabled: bool = bool(overrides.get("enabled", True))
        self.cfg: dict[str, Any] = {
            **self.defaults,
            **{k: v for k, v in overrides.items() if k != "enabled"},
        }

    def detect(self, m: Metrics) -> list[Finding]:  # pragma: no cover - interface
        raise NotImplementedError

    def finding(self, severity: Severity, key: str | None = None, **kw: Any) -> Finding:
        return Finding(detector=self.name, key=key or self.name, severity=severity, **kw)

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "label": cls.label,
            "description": cls.description,
            "defaults": cls.defaults,
        }
