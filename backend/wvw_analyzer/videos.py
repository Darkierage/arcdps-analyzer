"""Linked video recordings: when they start and end, and which fights they cover.

All times are wall-clock UTC milliseconds. A video covers a fight when their spans overlap; the
page maps fight second `t` to video second with

    video_t = fight_start + t - video_start - paused_before(t) + offset

(`frontend/src/lib/videoSync.ts`). Video files are only read (stat, served to the page); the
app never writes, moves or deletes them.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# What the app's window can be asked to play; anything else is refused when linking, so the
# file route can never serve other files.
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm", ".m4v")

# Recorder file names with the local start time:
#   OBS (default):       2026-11-10 18-11-50.mkv
#   NVIDIA ShadowPlay:   Guild Wars 2 2026.11.10 - 18.11.50.02.DVR.mp4
#   Windows Game Bar:    Guild Wars 2 2026-11-10 18-11-50.mp4
_NAME_TIME = re.compile(
    r"(?<!\d)(\d{4})[-._](\d{2})[-._](\d{2})[ _T]*(?:-\s*)?(\d{2})[-._:](\d{2})[-._:](\d{2})(?!\d)")
SCAN_LIMIT = 2000  # files looked at per folder scan (a huge Videos folder must stay fast)


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def name_time_ms(name: str) -> int | None:
    """Start time from a recorder's file name, read as this PC's local time."""
    m = _NAME_TIME.search(name)
    if not m:
        return None
    try:
        dt = datetime(*(int(g) for g in m.groups()))  # type: ignore[misc]
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def file_timing(path: Path) -> dict[str, Any]:
    """start_ms / end_ms / sync_source / approximate for a video file, without opening it.

    The start comes from the file name; else from the file's creation time (Windows, the
    recorder creates the file when it starts); else it is unknown until the page reports the
    file's length (then start = end - length). The end is the last write."""
    st = path.stat()
    end_ms = int(st.st_mtime * 1000)
    start = name_time_ms(path.name)
    if start is not None:
        return {"start_ms": start, "end_ms": end_ms, "sync_source": "filename",
                "approximate": False}
    birth = getattr(st, "st_birthtime", None)
    if birth:
        return {"start_ms": int(birth * 1000), "end_ms": end_ms, "sync_source": "filetime",
                "approximate": False}
    return {"start_ms": end_ms, "end_ms": end_ms, "sync_source": "filetime", "approximate": True}


def parse_fight_start(text: str | None) -> int | None:
    """`timeStartStd` ("2026-11-10 18:11:50 +01:00") as UTC ms."""
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return int(datetime.strptime(text.strip(), fmt).timestamp() * 1000)
        except ValueError:
            continue
    # EI's short form "+01" (timeStart) has no minutes.
    m = re.match(r"(.+ [+-]\d{2})$", text.strip())
    if m:
        return parse_fight_start(text.strip() + ":00")
    return None


def fight_span(row: dict[str, Any]) -> tuple[int, int] | None:
    """A fight row's (start_ms, end_ms) on the wall clock, or None without a start time."""
    start = parse_fight_start(row.get("fight_start") or (row.get("summary") or {}).get("start"))
    if start is None:
        return None
    dur = (row.get("summary") or {}).get("durationS") or 0
    return start, start + int(float(dur) * 1000)


def covers(video: dict[str, Any], span: tuple[int, int]) -> bool:
    """Whether a video's span overlaps a fight's (an open end: still recording). The offset
    moves the whole video on the fight's clock: +1 s shows each moment 1 s later in the file,
    so the file's first frame belongs 1 s earlier."""
    off = video.get("offset_ms") or 0
    start = video["start_ms"] - off
    end = video.get("end_ms")
    if end is not None and end <= video["start_ms"]:
        return False  # nothing recorded (or the length is unknown): covers no fight
    return start < span[1] and (end is None or end - off > span[0])


def api_row(v: dict[str, Any], fight_ids: list[int] | None = None) -> dict[str, Any]:
    path = v.get("path")
    out = {
        "id": v["id"],
        "path": path,
        "name": Path(path).name if path else "Recording in progress (OBS)",
        "label": v.get("label") or "",
        "startMs": v["start_ms"],
        "endMs": v.get("end_ms"),
        "syncSource": v["sync_source"],
        "approximate": bool(v.get("approximate")),
        "offsetMs": v.get("offset_ms") or 0,
        "pauses": v.get("pauses") or [],
        "startedByApp": bool(v.get("started_by_app")),
        "exists": bool(path) and Path(path).is_file(),
    }
    if fight_ids is not None:
        out["fightIds"] = fight_ids
    return out


def covered_fights(video: dict[str, Any], fights: Iterable[dict[str, Any]]) -> list[int]:
    out = []
    for f in fights:
        span = fight_span(f)
        if span and covers(video, span):
            out.append(f["id"])
    return out


def scan_folders(folders: Iterable[Path]) -> list[Path]:
    """Video files in the folders and one level of subfolders (recorders keep per-game ones)."""
    out: list[Path] = []
    seen = 0
    for root in folders:
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for e in entries:
            if seen >= SCAN_LIMIT:
                return out
            seen += 1
            try:
                if e.is_file() and is_video(e):
                    out.append(e)
                elif e.is_dir() and not e.name.startswith("."):
                    for f in e.iterdir():
                        seen += 1
                        if seen >= SCAN_LIMIT:
                            return out
                        if f.is_file() and is_video(f):
                            out.append(f)
            except OSError:
                continue
    return out


def suggestions(folders: Iterable[Path], fights: list[dict[str, Any]],
                linked: set[str]) -> list[dict[str, Any]]:
    """Unlinked recordings in the folders that cover some of these fights."""
    spans = [(f["id"], s) for f in fights if (s := fight_span(f))]
    if not spans:
        return []
    lo = min(s[0] for _, s in spans)
    out = []
    for path in scan_folders(folders):
        if str(path) in linked:
            continue
        try:
            st = path.stat()
            if st.st_mtime * 1000 < lo:  # finished before the first fight: skip quickly
                continue
            timing = file_timing(path)
        except OSError:
            continue
        v = {**timing, "offset_ms": 0}
        ids = [fid for fid, s in spans if covers(v, s)]
        if ids and not timing["approximate"]:
            out.append({"path": str(path), "name": path.name, "startMs": timing["start_ms"],
                        "endMs": timing["end_ms"], "syncSource": timing["sync_source"],
                        "fightIds": ids})
    return sorted(out, key=lambda s: s["startMs"])


def media_type(path: Path) -> str:
    return {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
            ".webm": "video/webm", ".mkv": "video/x-matroska"}.get(path.suffix.lower(),
                                                                   "application/octet-stream")
