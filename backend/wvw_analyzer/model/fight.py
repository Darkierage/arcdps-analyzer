"""Typed view over Elite Insights JSON for WvW fights.

The raw EI dicts are kept on each object (``raw``); typed fields hold what the rest of the
analyzer relies on so EI schema details live in one place (this module + loader).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Boons tracked in stats tables and detectors (EI buff ids).
BOONS: dict[int, str] = {
    1122: "Stability",
    743: "Aegis",
    717: "Protection",
    873: "Resolution",
    26980: "Resistance",
    1187: "Quickness",
    30328: "Alacrity",
    740: "Might",
    725: "Fury",
    718: "Regeneration",
    726: "Vigor",
    719: "Swiftness",
    5974: "Superspeed",
    13017: "Stealth",
}
INTENSITY_BOONS = {1122, 740}  # stacking in intensity: EI 'uptime' = avg stacks
STABILITY, AEGIS, PROTECTION, RESISTANCE, RESOLUTION = 1122, 743, 717, 26980, 873

# A step function from EI: [[time_ms, value], ...]
States = list[list[float]]


def sample_states(states: States | None, times_ms: np.ndarray, default: float = 0.0) -> np.ndarray:
    """Value of an EI step function at each time in ``times_ms``."""
    if not states:
        return np.full(times_ms.shape, default, dtype=float)
    arr = np.asarray(states, dtype=float)
    idx = np.searchsorted(arr[:, 0], times_ms, side="right") - 1
    out = np.where(idx >= 0, arr[np.clip(idx, 0, None), 1], default)
    return out.astype(float)


def interval_mask(intervals: list[list[float]] | None, times_ms: np.ndarray) -> np.ndarray:
    """True where a time falls inside any [start, end) interval."""
    mask = np.zeros(times_ms.shape, dtype=bool)
    for start, end in intervals or []:
        mask |= (times_ms >= start) & (times_ms < end)
    return mask


@dataclass
class Actor:
    name: str
    profession: str
    team_id: int
    raw: dict[str, Any] = field(repr=False)

    @property
    def replay(self) -> dict[str, Any]:
        return self.raw.get("combatReplayData") or {}

    @property
    def down_intervals(self) -> list[list[float]]:
        return self.replay.get("down") or []

    @property
    def dead_intervals(self) -> list[list[float]]:
        return self.replay.get("dead") or []

    @property
    def dc_intervals(self) -> list[list[float]]:
        return self.replay.get("dc") or []


@dataclass
class Player(Actor):
    account: str = ""
    group: int = 0
    is_commander: bool = False
    tag_ms: float = 0.0
    active_ms: float = 0.0
    has_heal_data: bool = False

    def first(self, key: str) -> dict[str, Any]:
        """First (full fight) phase entry of a per-phase stats list such as statsAll."""
        val = self.raw.get(key) or [{}]
        return val[0] if isinstance(val, list) else val

    def buff(self, buff_id: int, key: str = "buffUptimes") -> dict[str, Any] | None:
        for b in self.raw.get(key) or []:
            if b.get("id") == buff_id:
                return b
        return None

    def buff_states(self, buff_id: int) -> States | None:
        b = self.buff(buff_id)
        return b.get("states") if b else None


@dataclass
class Enemy(Actor):
    deaths: int = 0
    downs: int = 0


@dataclass
class Fight:
    log_id: str
    map_name: str
    start_time: str  # ISO-ish string from EI (timeStartStd)
    duration_ms: int
    pov_name: str
    pov_account: str
    ei_version: str
    polling_ms: float
    inch_to_pixel: float
    squad: list[Player]
    allies: list[Actor]
    enemies: list[Enemy]
    raw: dict[str, Any] = field(repr=False)

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def commander(self) -> Player | None:
        tagged = [p for p in self.squad if p.is_commander]
        return max(tagged, key=lambda p: p.tag_ms) if tagged else None

    @property
    def parties(self) -> list[int]:
        return sorted({p.group for p in self.squad})

    @property
    def has_heal_data(self) -> bool:
        return any(p.has_heal_data for p in self.squad)

    def time_grid(self) -> np.ndarray:
        """Seconds 0..N (inclusive) used for all per-second series."""
        return np.arange(0, int(np.ceil(self.duration_s)) + 1, dtype=float)
