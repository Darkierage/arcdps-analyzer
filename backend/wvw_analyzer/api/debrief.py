"""Stored LLM debrief text helpers shared by the fight page and the in-game overlay."""

from __future__ import annotations

import json


def split_debrief(text: str | None) -> tuple[str | None, list[str]]:
    """Stored debrief -> (text, unverified numbers). The check result is appended as JSON."""
    if not text:
        return None, []
    body, sep, tail = text.rpartition("\n\n")
    if sep and tail.startswith('{"unverified"'):
        try:
            return body, json.loads(tail)["unverified"]
        except (json.JSONDecodeError, KeyError):
            pass
    return text, []
