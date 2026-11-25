"""Rank findings, merge overlapping ones and pick the notes shown to the user."""

from __future__ import annotations

from ..detectors.base import SEVERITY_ORDER, Finding

MAX_ISSUES = 5
MAX_POSITIVES = 2


def _overlaps(a: Finding, b: Finding) -> bool:
    if a.window is None or b.window is None:
        return False
    return a.window[0] <= b.window[1] + 2 and b.window[0] <= a.window[1] + 2


def _shares_subject(a: Finding, b: Finding) -> bool:
    return bool(set(a.subjects) & set(b.subjects)) or not a.subjects or not b.subjects


def rank(findings: list[Finding]) -> dict[str, list[Finding]]:
    positives = sorted((f for f in findings if f.severity == "positive"), key=lambda f: -f.impact)
    issues = sorted(
        (f for f in findings if f.severity != "positive"),
        key=lambda f: (-f.impact, SEVERITY_ORDER[f.severity]),
    )
    kept: list[Finding] = []
    for f in issues:
        host = next((k for k in kept if _overlaps(k, f) and _shares_subject(k, f)), None)
        if host is not None:
            host.related.append(f.title)
            host.impact += 0.25 * f.impact  # supporting evidence strengthens the main finding
            continue
        kept.append(f)
    # Severity first (critical, major, minor, context), then impact: a big minor note never
    # sits above a critical one, nor a context note above a minor one.
    kept.sort(key=lambda f: (SEVERITY_ORDER[f.severity], -f.impact))
    return {
        "issues": kept[:MAX_ISSUES],
        "more": kept[MAX_ISSUES:],
        "positives": positives[:MAX_POSITIVES],
    }
