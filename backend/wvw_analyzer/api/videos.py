"""Video routes: link recordings, list them per fight / session, serve the files to the page."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import paths
from .. import videos as vid

if TYPE_CHECKING:
    from ..state import AppState

log = logging.getLogger(__name__)


class VideoAdd(BaseModel):
    path: str
    label: str | None = None


class VideoPatch(BaseModel):
    label: str | None = Field(None, max_length=80)
    offsetMs: int | None = Field(None, ge=-86_400_000, le=86_400_000)
    durationMs: int | None = Field(None, ge=0)
    manual: bool = False  # the offset was set by hand: the sync is no longer approximate


def mark_videos(rows: list[dict[str, Any]], videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set `hasVideo` on fight rows a linked video covers (the camera icon in fight lists)."""
    live = [v for v in videos if v.get("path") or v.get("end_ms") is None]
    for r in rows:
        span = vid.fight_span(r)
        r["hasVideo"] = bool(span) and any(vid.covers(v, span) for v in live)  # type: ignore[arg-type]
    return rows


def router(state: AppState) -> APIRouter:
    r = APIRouter()

    def _folders() -> list[Path]:
        configured = [Path(f) for f in state.config.settings.videos.folders if f.strip()]
        return configured or paths.default_video_dirs()

    def _get(video_id: int) -> dict[str, Any]:
        v = state.db.video(video_id)
        if not v:
            raise HTTPException(404, "Video not found")
        return v

    @r.get("/api/fights/{fight_id}/videos")
    def fight_videos(fight_id: int) -> dict[str, Any]:
        f = state.db.fight(fight_id)
        if not f:
            raise HTTPException(404, "Fight not found")
        span = vid.fight_span(f)
        rows = [vid.api_row(v, [fight_id]) for v in state.db.videos()
                if span and vid.covers(v, span) and v.get("path")]
        return {"fightStartMs": span[0] if span else None,
                "leadInS": state.config.settings.videos.lead_in_s, "videos": rows}

    @r.get("/api/sessions/{session_id}/videos")
    def session_videos(session_id: int) -> dict[str, Any]:
        if not state.db.session(session_id):
            raise HTTPException(404, "Session not found")
        fights = [f for f in state.db.fights(session_id=session_id, include_skipped=False,
                                             limit=10_000)]
        all_videos = state.db.videos()
        rows = []
        for v in all_videos:
            ids = vid.covered_fights(v, fights)
            if ids:
                rows.append(vid.api_row(v, ids))
        linked = {v["path"] for v in all_videos if v.get("path")}
        folders = _folders()
        return {"videos": rows, "suggestions": vid.suggestions(folders, fights, linked),
                "folders": [str(f) for f in folders]}

    @r.post("/api/videos")
    def add_video(body: VideoAdd) -> dict[str, Any]:
        path = Path(body.path.strip().strip('"'))
        if not vid.is_video(path):
            kinds = ", ".join(vid.VIDEO_EXTENSIONS)
            raise HTTPException(400, f"Not a video file the app can play ({kinds})")
        if not path.is_file():
            raise HTTPException(400, f"File not found: {path}")
        path = path.resolve()
        if state.db.video_by_path(str(path)):
            raise HTTPException(409, "This video is already linked")
        try:
            timing = vid.file_timing(path)
        except OSError as e:
            raise HTTPException(400, f"Could not read the file: {e}") from e
        vid_id = state.db.add_video(path=str(path), label=(body.label or "").strip(), **timing)
        log.info("linked video %s (%s)", path.name, timing["sync_source"])
        return vid.api_row(_get(vid_id))

    @r.patch("/api/videos/{video_id}")
    def update_video(video_id: int, body: VideoPatch) -> dict[str, Any]:
        v = _get(video_id)
        fields: dict[str, Any] = {}
        if body.label is not None:
            fields["label"] = body.label.strip()
        if body.offsetMs is not None:
            fields["offset_ms"] = body.offsetMs
            if body.manual:
                fields["approximate"] = False
                fields["sync_source"] = "manual"
        if body.durationMs is not None and v["sync_source"] != "obs":
            paused = sum(b - a for a, b in v["pauses"])
            if v["sync_source"] == "filetime" and v["approximate"] and v.get("end_ms"):
                # Only the last write time was known: the first frame is one length before it.
                fields["start_ms"] = v["end_ms"] - body.durationMs - paused
            else:
                fields["end_ms"] = v["start_ms"] + body.durationMs + paused
        state.db.update_video(video_id, **fields)
        return vid.api_row(_get(video_id))

    @r.delete("/api/videos/{video_id}")
    def delete_video(video_id: int) -> dict[str, bool]:
        """Removes the link only; the file stays where it is."""
        _get(video_id)
        state.db.delete_video(video_id)
        return {"ok": True}

    @r.get("/api/videos/{video_id}/file")
    def video_file(video_id: int) -> FileResponse:
        """The video, by id only (with Range requests, so the page can seek)."""
        v = _get(video_id)
        path = Path(v["path"]) if v.get("path") else None
        if path is None or not path.is_file() or not vid.is_video(path):
            raise HTTPException(404, "Video file not found")
        # no-cache: the browser must check before reusing a copy. A video id can come back
        # for another file (unlinking the newest video frees its id), and the window then
        # played the old file from its cache.
        return FileResponse(path, media_type=vid.media_type(path),
                            headers={"Cache-Control": "no-cache"})

    return r
