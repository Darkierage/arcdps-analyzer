"""Render finding text from YAML templates (user overrides in the data dir)."""

from __future__ import annotations

import string
from functools import cache
from pathlib import Path

import yaml

from .. import paths
from ..detectors.base import Finding

DEFAULT_FILE = Path(__file__).with_name("templates.yaml")


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "?"


def _pretty(v: object) -> object:
    if v is None:
        return "?"
    if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 10_000:
        return f"{v / 1_000_000:.1f}M" if abs(v) >= 1_000_000 else f"{v / 1000:.0f}k"
    return v


def _format(text: str, evidence: dict) -> str:
    values = _Safe({k: _pretty(v) for k, v in evidence.items()})
    return string.Formatter().vformat(text, (), values).strip()


@cache
def _load(user_file: Path | None) -> dict[str, dict[str, str]]:
    data = yaml.safe_load(DEFAULT_FILE.read_text(encoding="utf-8")) or {}
    if user_file and user_file.exists():
        for key, tpl in (yaml.safe_load(user_file.read_text(encoding="utf-8")) or {}).items():
            data.setdefault(key, {}).update(tpl or {})
    return data


def templates() -> dict[str, dict[str, str]]:
    return _load(paths.data_dir() / "templates.yaml")


def reload() -> None:
    _load.cache_clear()


def render(f: Finding) -> Finding:
    tpl = templates().get(f.key) or templates().get(f.detector) or {}
    f.title = _format(tpl.get("title", f.detector), f.evidence)
    f.cause = _format(tpl.get("cause", ""), f.evidence)
    f.fix = _format(tpl.get("fix", ""), f.evidence)
    f.short = _format(tpl.get("short", ""), f.evidence)
    f.fix_short = _format(tpl.get("fix_short", ""), f.evidence)
    return f
