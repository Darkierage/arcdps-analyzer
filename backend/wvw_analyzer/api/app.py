"""HTTP API + WebSocket + static frontend."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__, paths
from ..config import FightMode
from ..detectors import registry
from ..ingest.recorder import iter_logs
from ..metrics.aggregate import aggregate_session
from ..notes import templates
from ..state import AppState
from ..store.files import remove_fight_files

log = logging.getLogger(__name__)

MAX_UPLOAD = 200 * 1024 * 1024  # arcdps logs are a few MB; this only guards against mistakes


class RecordStart(BaseModel):
    name: str | None = None


class ImportRequest(BaseModel):
    folder: str | None = None
    since: str | None = None  # YYYY-MM-DD
    until: str | None = None
    files: list[str] | None = None


class ImportCheck(BaseModel):
    names: list[str]


class SessionPatch(BaseModel):
    name: str


class ModeBody(BaseModel):
    mode: FightMode


def _day_ts(s: str | None, end: bool = False) -> float | None:
    if not s:
        return None
    d = datetime.strptime(s, "%Y-%m-%d")
    if end:
        d = d.replace(hour=23, minute=59, second=59)
    return d.timestamp()


def _split_debrief(text: str | None) -> tuple[str | None, list[str]]:
    if not text:
        return None, []
    body, sep, tail = text.rpartition("\n\n")
    if sep and tail.startswith('{"unverified"'):
        try:
            return body, json.loads(tail)["unverified"]
        except (json.JSONDecodeError, KeyError):
            pass
    return text, []


# The API only serves this machine. Requests must address a local host name (blocks DNS
# rebinding), and state-changing requests / the WebSocket must come from a local page (blocks
# other websites in the user's browser from driving the app). Requests without an Origin header
# (the app's own window loading pages, local scripts) are allowed.
LOCAL_NAMES = {"127.0.0.1", "localhost", "::1"}
TEST_HOST = "testserver"  # starlette TestClient
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_ok(host_header: str) -> bool:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8765
        host = host[1:].split("]")[0]
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in LOCAL_NAMES or host == TEST_HOST


def _origin_ok(origin: str | None) -> bool:
    if origin is None:
        return True
    return (urlparse(origin).hostname or "") in LOCAL_NAMES


def create_app(state: AppState) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.bus.bind_loop(asyncio.get_running_loop())
        state.start()
        yield
        await run_in_threadpool(state.stop)

    app = FastAPI(title="WvW Analyzer", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if not _host_ok(request.headers.get("host", "")):
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)
        if request.method not in SAFE_METHODS and not _origin_ok(request.headers.get("origin")):
            return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
        return await call_next(request)

    # ---- status -----------------------------------------------------------------------
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        s = state.config.settings
        ei = s.resolved_ei_path()
        return {
            "version": __version__,
            "onboarded": s.onboarded,
            "fightMode": s.fight_mode,
            "recording": state.recorder.state(),
            "queue": state.processor.state(),
            "eiInstalled": ei.exists(),
            "eiPath": str(ei),
            "llm": state.llm.status(),
            "dataDir": str(paths.data_dir()),
        }

    @app.get("/api/selftest")
    def selftest() -> dict[str, Any]:
        """Checks for the first-run setup screen: log folder, Elite Insights, optional LLM."""
        s = state.config.settings
        log_dir = s.resolved_log_dir()
        wvw_logs = 0
        if log_dir and log_dir.is_dir():
            wvw_logs = sum(1 for p, _ in iter_logs(log_dir) if "wvw" in str(p.parent).lower())
        return {
            "onboarded": s.onboarded,
            "logDir": {"ok": bool(log_dir and log_dir.is_dir()),
                       "path": str(log_dir) if log_dir else None,
                       "detected": str(paths.default_log_dir() or ""),
                       "wvwLogs": wvw_logs},
            "elite": state.processor.runner().self_test(),
            "llm": state.llm.status(),
        }

    @app.post("/api/recording/start")
    def recording_start(body: RecordStart | None = None) -> dict[str, Any]:
        try:
            return state.recorder.start(body.name if body else None)
        except RuntimeError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/recording/stop")
    def recording_stop() -> dict[str, Any]:
        return state.recorder.stop()

    @app.post("/api/import")
    def import_logs(body: ImportRequest) -> dict[str, Any]:
        try:
            return state.recorder.import_logs(
                folder=Path(body.folder) if body.folder else None,
                since=_day_ts(body.since), until=_day_ts(body.until, end=True),
                files=body.files)
        except (RuntimeError, ValueError, OSError) as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/import/preview")
    def import_preview(body: ImportRequest) -> dict[str, Any]:
        """Counts for the confirmation dialog before a date-range import."""
        try:
            return state.recorder.preview_import(
                folder=Path(body.folder) if body.folder else None,
                since=_day_ts(body.since), until=_day_ts(body.until, end=True))
        except (RuntimeError, ValueError, OSError) as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/import/upload")
    async def import_upload(request: Request, filename: str) -> dict[str, Any]:
        """Import one log sent as the raw request body (from the UI's file picker)."""
        data = await request.body()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "File too large for an arcdps log")
        try:
            path = await run_in_threadpool(state.recorder.store_upload, filename, data)
            if path is None:
                return {"added": 0, "alreadyKnown": 0, "fightIds": [], "notWvw": 1, "path": None}
            result = await run_in_threadpool(state.recorder.import_logs, None, None, None,
                                             [str(path)])
        except (RuntimeError, ValueError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        return {**result, "notWvw": 0, "path": str(path)}

    @app.post("/api/import/check")
    def import_check(body: ImportCheck) -> dict[str, Any]:
        """Which of these log file names are already imported (before uploading them)."""
        return {"known": state.db.fights_by_names([n for n in body.names if n])}

    @app.post("/api/queue/cancel")
    def queue_cancel() -> dict[str, int]:
        return {"cancelled": state.processor.cancel_pending()}

    # ---- sessions ---------------------------------------------------------------------
    @app.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        return state.db.sessions()

    @app.get("/api/sessions/{session_id}")
    def session(session_id: int) -> dict[str, Any]:
        s = state.db.session(session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        agg = aggregate_session(state.db.session_analyses(session_id))
        fights = state.db.fights(session_id=session_id)
        return {"session": s, "aggregate": agg, "fights": fights,
                "recording": state.recorder.session_id == session_id}

    @app.patch("/api/sessions/{session_id}")
    def rename_session(session_id: int, body: SessionPatch) -> dict[str, Any]:
        state.db.rename_session(session_id, body.name)
        return state.db.session(session_id) or {}

    @app.put("/api/sessions/{session_id}/mode")
    def session_mode(session_id: int, body: ModeBody) -> dict[str, int]:
        if not state.db.session(session_id):
            raise HTTPException(404, "Session not found")
        return {"queued": _set_mode(state.db.session_fight_ids(session_id), body.mode)}

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: int) -> dict[str, bool]:
        if state.recorder.session_id == session_id:
            raise HTTPException(400, "Stop recording before deleting this session")
        remove_fight_files(state.db.delete_session(session_id), state.db)
        return {"ok": True}

    # ---- fights -----------------------------------------------------------------------
    @app.get("/api/fights")
    def fights(session_id: int | None = None, include_skipped: bool = False,
               limit: int = 300) -> list[dict[str, Any]]:
        return state.db.fights(session_id=session_id, include_skipped=include_skipped,
                               limit=limit)

    @app.get("/api/fights/{fight_id}")
    def fight(fight_id: int) -> dict[str, Any]:
        f = state.db.fight(fight_id)
        if not f:
            raise HTTPException(404, "Fight not found")
        a = state.db.analysis(fight_id) or {}
        debrief, unverified = _split_debrief(a.get("debrief"))
        return {"fight": f, "stats": a.get("stats"), "notes": a.get("notes"),
                "debrief": debrief, "debriefUnverified": unverified,
                "debriefAt": a.get("debriefAt")}

    @app.post("/api/fights/{fight_id}/reanalyze")
    def reanalyze(fight_id: int, reparse: bool = False) -> dict[str, bool]:
        if not state.db.fight(fight_id):
            raise HTTPException(404, "Fight not found")
        state.processor.enqueue(fight_id, reparse=reparse)
        return {"ok": True}

    @app.put("/api/fights/{fight_id}/mode")
    def fight_mode(fight_id: int, body: ModeBody) -> dict[str, int]:
        if not state.db.fight(fight_id):
            raise HTTPException(404, "Fight not found")
        return {"queued": _set_mode([fight_id], body.mode)}

    def _set_mode(ids: list[int], mode: str) -> int:
        """Store the mode and re-analyze from the cached EI JSON (failed/skipped ones too)."""
        state.db.set_mode(ids, mode)
        for fid in ids:
            state.processor.enqueue(fid)
        return len(ids)

    @app.post("/api/reanalyze-all")
    def reanalyze_all() -> dict[str, int]:
        ids = state.db.all_fight_ids()
        for fid in ids:
            state.processor.enqueue(fid)
        return {"queued": len(ids)}

    @app.delete("/api/fights/{fight_id}")
    def delete_fight(fight_id: int) -> dict[str, bool]:
        remove_fight_files(state.db.delete_fight(fight_id), state.db)
        return {"ok": True}

    @app.post("/api/fights/{fight_id}/debrief")
    async def debrief(fight_id: int) -> dict[str, Any]:
        try:
            return await run_in_threadpool(state.write_debrief, fight_id)
        except (RuntimeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            log.exception("debrief failed")
            raise HTTPException(500, f"LLM error: {e}") from e

    # ---- settings ---------------------------------------------------------------------
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        s = state.config.settings
        return {
            "settings": s.model_dump(mode="json"),
            "detectors": registry.describe(s.detectors),
            "resolvedLogDir": str(s.resolved_log_dir() or ""),
            "defaultLogDir": str(paths.default_log_dir() or ""),
            "resolvedEiPath": str(s.resolved_ei_path()),
            "templatesFile": str(paths.data_dir() / "templates.yaml"),
        }

    @app.put("/api/settings")
    def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        try:
            state.config.update(patch)
        except Exception as e:
            raise HTTPException(400, f"Invalid settings: {e}") from e
        templates.reload()
        return get_settings()

    @app.post("/api/llm/setup")
    def llm_setup() -> dict[str, Any]:
        state.llm.setup()
        return state.llm.status()

    @app.post("/api/llm/unload")
    def llm_unload() -> dict[str, Any]:
        state.llm.shutdown()
        return state.llm.status()

    # ---- live events ------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        if not (_host_ok(socket.headers.get("host", ""))
                and _origin_ok(socket.headers.get("origin"))):
            await socket.close(code=1008)  # policy violation: not a local page
            return
        await socket.accept()
        q = state.bus.subscribe()
        try:
            await socket.send_json({"type": "hello", "recording": state.recorder.state(),
                                    "queue": state.processor.state()})
            while True:
                event = await q.get()
                await socket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            state.bus.unsubscribe(q)

    # ---- frontend ---------------------------------------------------------------------
    front = paths.frontend_dir()
    if (front / "index.html").exists():
        if (front / "_app").exists():
            app.mount("/_app", StaticFiles(directory=front / "_app"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            f = (front / path).resolve()
            if path and f.is_file() and f.is_relative_to(front.resolve()):
                return FileResponse(f)
            return FileResponse(front / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_front() -> JSONResponse:
            return JSONResponse({"detail": "Frontend not built. Run `npm run build` in frontend/ "
                                           "or use the Vite dev server."})

    return app
