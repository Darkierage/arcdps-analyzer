"""Personal rules: interface, scope and the Advice schema.

A rule reads one player's fight views (`coach/data.py`) for a scope and returns advice. Rules
are pure and deterministic; their wording comes from `notes/templates.yaml` (`me_*` keys) and
their thresholds from `defaults`, overridable in Settings like the fight detectors'. They read
stored facts only, so changing a threshold needs no re-analysis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import Field

from ..detectors.base import Finding
from .data import FightView

# A session is judged with lower gates than a profile (scaled by this share, rounded up), and
# says "this session" instead of "in N fights".
SESSION_GATE = 0.5


@dataclass(frozen=True)
class Scope:
    kind: Literal["session", "profile"] = "profile"

    @property
    def gate_share(self) -> float:
        return 1.0 if self.kind == "profile" else SESSION_GATE

    def txt(self, fights: int) -> str:
        n = f"{fights} fight" + ("" if fights == 1 else "s")
        return f"this session ({n})" if self.kind == "session" else f"in {n}"


class Advice(Finding):
    """A finding about one player, with what the page needs around it."""

    area: Literal["survival", "play"] = "survival"
    spec: str | None = None
    sample: str = ""  # "14 of 31 downs, squad: 6 of 31"
    examples: list[dict[str, Any]] = Field(default_factory=list)  # {"fightId", "t"}
    trend: Literal["better", "same", "worse"] | None = None


@dataclass
class Outcome:
    advice: list[Advice] = field(default_factory=list)
    # Why the rule stayed silent: {"rule", "spec", "need"} ("needs 6 downs, has 2").
    gates: list[dict[str, Any]] = field(default_factory=list)


class Rule:
    """Subclasses implement `run` and `measure`; both must be pure and deterministic."""

    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    area: ClassVar[Literal["survival", "play"]] = "survival"
    per_spec: ClassVar[bool] = False
    # The trend compares `measure` on the latest third of the scope with the rest.
    lower_is_better: ClassVar[bool] = True
    trend_margin: ClassVar[float] = 0.1
    defaults: ClassVar[dict[str, Any]] = {}
    # Off unless turned on in Settings: the rules that, in the step 2 calibration, fired for
    # almost nobody or no more often than chance (see docs/DECISIONS.md).
    enabled_by_default: ClassVar[bool] = True

    def __init__(self, overrides: dict[str, Any] | None = None):
        overrides = overrides or {}
        self.enabled: bool = bool(overrides.get("enabled", self.enabled_by_default))
        self.cfg: dict[str, Any] = {**self.defaults,
                                    **{k: v for k, v in overrides.items() if k != "enabled"}}

    def gate(self, key: str, scope: Scope) -> int:
        return max(1, math.ceil(self.cfg[key] * scope.gate_share))

    def run(self, views: list[FightView], scope: Scope) -> Outcome:  # pragma: no cover
        raise NotImplementedError

    def measure(self, views: list[FightView], scope: Scope,
                spec: str | None = None) -> float | None:  # pragma: no cover
        """The rule's main number for a trend, or None when `views` don't pass its gate."""
        raise NotImplementedError

    def advice(self, key: str, severity: str, views: list[FightView], scope: Scope, *,
               impact: float, evidence: dict[str, Any], sample: str,
               examples: list[dict[str, Any]] | None = None,
               spec: str | None = None) -> Advice:
        return Advice(detector=self.name, key=key, severity=severity, impact=round(impact, 2),
                      area=self.area, spec=spec, sample=sample,
                      examples=(examples or [])[:EXAMPLES],
                      evidence={"scope_txt": scope.txt(len(views)),
                                "scope_cap": scope.txt(len(views)).capitalize(),
                                "fights": len(views),
                                "spec": spec or "", **evidence})

    def silent(self, need: str, spec: str | None = None) -> Outcome:
        return Outcome(gates=[{"rule": self.name, "label": self.label, "spec": spec,
                               "need": need}])

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {"name": cls.name, "label": cls.label, "description": cls.description,
                "defaults": cls.defaults, "personal": True,
                "enabledByDefault": cls.enabled_by_default}


EXAMPLES = 8  # example fights listed per advice


def pct(x: float) -> int:
    return int(round(100 * x))
