"""GvG rounds and call-offs.

A GvG round ends when one commander calls it off: both sides stop fighting, walk away and rez
everyone, downed enemies included. Downs still open at that moment were left on purpose, and
kills after it are not part of the fight. In zerg mode there is one round and nothing is left.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Round:
    start: float  # first second with meaningful damage
    calloff: float  # last second with meaningful damage (the call-off in GvG)
    end: float  # last second that still belongs to this round (grace included)

    def json(self) -> dict[str, float]:
        return {"start": self.start, "calloff": self.calloff, "end": self.end}


def split_rounds(active: np.ndarray, t: np.ndarray, gap_s: float, grace_s: float) -> list[Round]:
    """Rounds from the per-second "meaningful activity" mask: a lull of ``gap_s`` splits."""
    idx = np.nonzero(active)[0]
    if not len(idx):
        return [Round(0.0, float(t[-1]), float(t[-1]))] if len(t) else []
    out: list[Round] = []
    start = prev = idx[0]
    for i in idx[1:]:
        if t[i] - t[prev] >= gap_s:
            out.append(Round(float(t[start]), float(t[prev]), float(t[prev]) + grace_s))
            start = i
        prev = i
    out.append(Round(float(t[start]), float(t[prev]), float(t[prev]) + grace_s))
    return out


def round_of(ts: float, rounds: list[Round]) -> int | None:
    """Index of the round an event at ``ts`` belongs to, None if it is after a call-off."""
    for i, r in enumerate(rounds):
        if ts <= r.end:
            return i
    return None


def down_left(start_s: float, end_s: float, rounds: list[Round]) -> bool:
    """A down that was still open when its round was called off (left on purpose)."""
    i = round_of(start_s, rounds)
    return i is not None and end_s > rounds[i].end
