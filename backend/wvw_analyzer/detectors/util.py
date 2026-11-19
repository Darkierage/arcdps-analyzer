"""Shared helpers for detectors."""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np


def window_mean(series: np.ndarray | None, t0: float, t1: float) -> float | None:
    """Mean of a per-second series over [t0, t1] seconds (NaN-safe)."""
    if series is None or len(series) == 0:
        return None
    i0 = int(max(0, np.floor(t0)))
    i1 = int(min(len(series) - 1, np.ceil(t1)))
    if i1 < i0:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        v = float(np.nanmean(series[i0 : i1 + 1]))
    return None if np.isnan(v) else v


def clusters(
    events: list[dict[str, Any]], gap_s: float, max_span_s: float = 8.0
) -> list[list[dict[str, Any]]]:
    """Group time-sorted events whose consecutive gap is <= gap_s, each spanning <= max_span_s."""
    out: list[list[dict[str, Any]]] = []
    for e in sorted(events, key=lambda x: x["t"]):
        if out and e["t"] - out[-1][-1]["t"] <= gap_s and e["t"] - out[-1][0]["t"] <= max_span_s:
            out[-1].append(e)
        else:
            out.append([e])
    return out


# Boon states before this point are unreliable: arcdps can't see boons applied before the log
# started, so every player appears boonless for the first moments of a log.
LOG_WARMUP_S = 3.0


def fmt_time(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


def pct(x: float | None) -> int:
    return 0 if x is None else int(round(x * 100))


def round_note(hit: int, total: int) -> str:
    """Suffix for GvG notes about how many rounds showed the problem ("" for one round)."""
    return f" This happened in {hit} of {total} rounds." if total > 1 else ""


def down_weight(e: dict[str, Any]) -> float:
    """Impact weight of a down event: deaths count fully, rallied downs half."""
    return 1.0 if e.get("died") else 0.5
