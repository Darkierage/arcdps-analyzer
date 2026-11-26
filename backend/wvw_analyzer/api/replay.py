"""Combat replay routes: a fight's replay data and the replay map images."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from .. import diagnostics, tools
from ..ingest.processor import run_in_worker
from ..replay import replay_gz, replay_job

if TYPE_CHECKING:
    from ..state import AppState

log = logging.getLogger(__name__)


def router(state: AppState) -> APIRouter:
    r = APIRouter()

    def _build(ei_path: str) -> dict[str, Any]:
        if not state.processor.use_worker:
            return replay_job(ei_path)
        return run_in_worker(replay_job, (ei_path,),
                             state.data_dir / diagnostics.FAULT_FILE, Path(ei_path).name)

    @r.get("/api/fights/{fight_id}/replay")
    def fight_replay(fight_id: int) -> Response:
        """Positions, facing and down/dead intervals of every actor (gzip JSON, cached)."""
        f = state.db.fight(fight_id)
        if not f:
            raise HTTPException(404, "Fight not found")
        ei = Path(f["ei_json"]) if f.get("ei_json") else None
        if ei is None or not ei.is_file():
            raise HTTPException(404, "This fight has no parsed log to replay (re-parse it)")
        try:
            raw = replay_gz(ei, _build)
        except (OSError, ValueError, RuntimeError) as e:
            log.warning("replay of fight %s failed: %s", fight_id, e)
            raise HTTPException(500, f"Could not build the replay: {e}") from e
        return Response(raw, media_type="application/json",
                        headers={"Content-Encoding": "gzip", "Cache-Control": "no-store"})

    @r.get("/api/replay-maps")
    def replay_maps() -> dict[str, Any]:
        return {"installed": tools.map_images_installed(),
                "maps": {k: tools.map_image_path(k) is not None for k in tools.MAP_IMAGES}}

    @r.post("/api/replay-maps/download")
    def download_replay_maps() -> dict[str, Any]:
        """Fetch the pinned map images (a few MB, checksummed); the only network use here."""
        try:
            tools.download_map_images()
        except (OSError, tools.ChecksumError) as e:
            raise HTTPException(502, f"Could not download the map images: {e}") from e
        return replay_maps()

    @r.get("/api/replay-maps/{key}")
    def replay_map(key: str) -> FileResponse:
        path = tools.map_image_path(key)
        if path is None:
            raise HTTPException(404, "Map image not downloaded")
        return FileResponse(path, headers={"Cache-Control": "max-age=86400"})

    return r
