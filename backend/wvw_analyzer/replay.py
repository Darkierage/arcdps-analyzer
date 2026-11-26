"""Combat replay: a compact copy of Elite Insights' replay data for the Replay tab.

The EI JSON already holds every actor's positions (at the polling rate, in the replay map's
pixel space), facing, and down / dead / disconnected intervals. The page needs only those, so
they are extracted once per fight and cached as a small gzip file next to the EI JSON
(`<name>.replay.json.gz`). Nothing here is part of the analysis: no detector reads it.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from . import tools
from .ingest.loader import read_ei_json

log = logging.getLogger(__name__)

# Bump when the payload shape changes: older caches are rebuilt on the next open.
REPLAY_VERSION = 1
CACHE_SUFFIX = ".replay.json.gz"
_EI_SUFFIXES = (".json.gz", ".json")
_MS_MAX = 2 ** 53  # EI marks open-ended intervals with int64 extremes

_build_lock = threading.Lock()


def cache_path(ei_json: Path) -> Path:
    name = ei_json.name
    for suf in _EI_SUFFIXES:
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    return ei_json.with_name(name + CACHE_SUFFIX)


def sources_for(cache: Path) -> list[Path]:
    """The EI JSON files a replay cache can have been made from."""
    stem = cache.name[: -len(CACHE_SUFFIX)]
    return [cache.with_name(stem + suf) for suf in _EI_SUFFIXES]


def _intervals(raw: Any, end_ms: int) -> list[list[int]]:
    """[[start, end], ...] in ms, clipped to the fight (EI uses int64 extremes for open ends)."""
    out = []
    for iv in raw or []:
        if not isinstance(iv, (list, tuple)) or len(iv) < 2:
            continue
        a = max(0, min(int(iv[0]), end_ms))
        b = max(0, min(int(iv[1]), end_ms)) if abs(iv[1]) < _MS_MAX else end_ms
        if b > a:
            out.append([a, b])
    return out


def _actor(raw: dict[str, Any], kind: str, end_ms: int) -> dict[str, Any] | None:
    cr = raw.get("combatReplayData") or {}
    pos = cr.get("positions") or []
    if not pos:
        return None
    flat: list[float] = []
    for p in pos:
        flat.append(round(float(p[0]), 1))
        flat.append(round(float(p[1]), 1))
    ori = [round(float(o)) for o in (cr.get("orientations") or [])]
    name = str(raw.get("name") or "?")
    a: dict[str, Any] = {
        "kind": kind,
        "start": int(cr.get("start") or 0),
        "end": int(cr.get("end") or end_ms),
        "p": flat,
        "o": ori if len(ori) == len(pos) else [],
        "down": _intervals(cr.get("down"), end_ms),
        "dead": _intervals(cr.get("dead"), end_ms),
        "dc": _intervals(cr.get("dc"), end_ms),
    }
    if kind == "enemy":
        # Enemies are anonymized as "<Spec> pl-1234": show the spec only.
        a["name"] = name.split(" pl-")[0]
        a["profession"] = a["name"]
        a["team"] = int(raw.get("teamID") or 0)
    else:
        a["name"] = name
        a["account"] = raw.get("account") or ""
        a["profession"] = raw.get("profession") or "?"
        a["group"] = int(raw.get("group") or 0)
        a["commander"] = bool(raw.get("hasCommanderTag"))
    return a


def build_replay(data: dict[str, Any]) -> dict[str, Any]:
    """The Replay tab's payload from an EI JSON document."""
    meta = data.get("combatReplayMetaData") or {}
    end_ms = int(data.get("durationMS") or 0)
    actors = []
    for p in data.get("players") or []:
        if p.get("isFake") or p.get("friendlyNPC"):
            continue
        a = _actor(p, "ally" if p.get("notInSquad") else "squad", end_ms)
        if a:
            actors.append(a)
    for t in data.get("targets") or []:
        if not t.get("enemyPlayer") or t.get("isFake"):
            continue
        a = _actor(t, "enemy", end_ms)
        if a:
            actors.append(a)
    maps = meta.get("maps") or []
    url = maps[0].get("url") if maps and isinstance(maps[0], dict) else None
    sizes = meta.get("sizes") or [0, 0]
    return {
        "version": REPLAY_VERSION,
        "durationMs": end_ms,
        "start": data.get("timeStartStd") or data.get("timeStart") or "",
        "pollingMs": float(meta.get("pollingRate") or 150),
        "inchToPixel": float(meta.get("inchToPixel") or 1.0),
        "size": [float(sizes[0]), float(sizes[1])] if len(sizes) >= 2 else [0.0, 0.0],
        "map": {"key": tools.map_key_for_url(url), "hasImage": bool(url)},
        "actors": actors,
    }


def replay_job(ei_path: str) -> dict[str, Any]:
    """Worker entry point: read one EI JSON and build its replay (picklable result)."""
    return build_replay(read_ei_json(Path(ei_path)))


def _source_stamp(ei_json: Path) -> list[float]:
    st = ei_json.stat()
    return [st.st_size, round(st.st_mtime, 3)]


def _read_cache(cache: Path, stamp: list[float]) -> bytes | None:
    try:
        raw = cache.read_bytes()
        head = json.loads(gzip.decompress(raw))
    except (OSError, ValueError, EOFError):
        return None
    if head.get("version") != REPLAY_VERSION or head.get("source") != stamp:
        return None
    return raw


def replay_gz(ei_json: Path, build: Any = None) -> bytes:
    """The gzip-compressed replay JSON of a fight, from the cache or built now.

    ``build(ei_path) -> dict`` builds it (the API runs `replay_job` in a worker process; the EI
    JSON is tens of MB unpacked and the main process should not hold it)."""
    cache = cache_path(ei_json)
    stamp = _source_stamp(ei_json)
    cached = _read_cache(cache, stamp)
    if cached is not None:
        return cached
    with _build_lock:  # two tabs opening the same fight build it once
        cached = _read_cache(cache, stamp)
        if cached is not None:
            return cached
        payload = (build or replay_job)(str(ei_json))
        payload["source"] = stamp
        raw = gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), 6)
        tmp = cache.with_name(cache.name + ".tmp")
        try:
            tmp.write_bytes(raw)
            os.replace(tmp, cache)
        except OSError as e:  # a read-only folder: serve it without caching
            log.warning("could not cache the replay of %s: %s", ei_json.name, e)
        return raw
