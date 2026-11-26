"""HTTP API + WebSocket + static frontend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__, diagnostics, paths
from ..coach import registry as coach_registry
from ..coach import report
from ..config import FightMode
from ..detectors import registry
from ..ingest.recorder import iter_logs
from ..metrics.aggregate import aggregate_session, session_trend
from ..notes import templates
from ..state import AppState
from ..store.files import remove_fight_files
from . import obs as obs_routes
from . import overlay
from . import replay as replay_routes
from . import videos as video_routes
from .debrief import split_debrief

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


class DiagnosticsRequest(BaseModel):
    userAgent: str | None = None


class SkipBody(BaseModel):
    version: str


class ClientError(BaseModel):
    message: str = ""
    stack: str | None = None
    url: str | None = None


MAX_CLIENT_ERRORS = 50  # per run: a render loop that throws must not flood the log


def _day_ts(s: str | None, end: bool = False) -> float | None:
    if not s:
        return None
    d = datetime.strptime(s, "%Y-%m-%d")
    if end:
        d = d.replace(hour=23, minute=59, second=59)
    return d.timestamp()


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

    app.include_router(overlay.router(state))
    app.include_router(replay_routes.router(state))
    app.include_router(video_routes.router(state))
    app.include_router(obs_routes.router(state))

    # ---- status -----------------------------------------------------------------------
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        s = state.config.settings
        ei = s.resolved_ei_path()
        return {
            "app": "wvw-analyzer",  # lets the in-game addon recognize this server
            "version": __version__,
            "onboarded": s.onboarded,
            "fightMode": s.fight_mode,
            "recording": state.recorder.state(),
            "queue": state.processor.state(),
            "eiInstalled": ei.exists(),
            "eiPath": str(ei),
            "llm": state.llm.status(),
            "obs": state.obs.status(),
            "dataDir": str(state.data_dir),
            "crashes": diagnostics.pending_crashes(state.data_dir),
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
        fights = video_routes.mark_videos(state.db.fights(session_id=session_id),
                                          state.db.videos())
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

    @app.get("/api/trends")
    def trends() -> dict[str, Any]:
        """One row per session with analyzed fights, oldest first (the Trends page)."""
        return {"sessions": session_trend(state.db.trend_sessions())}

    # ---- personal review ("My play") ------------------------------------------------------
    def _default_account(players: list[dict[str, Any]]) -> str | None:
        mine = state.config.settings.my_account
        if mine and any(p["account"] == mine for p in players):
            return mine
        recorded = [p for p in players if p["povFights"]]
        best = max(recorded, key=lambda p: (p["povFights"], p["fights"]), default=None)
        return best["account"] if best else (players[0]["account"] if players else None)

    @app.get("/api/players")
    def players() -> dict[str, Any]:
        """Accounts in analyzed fights (the player picker) and the one to open on."""
        ps = state.db.players()
        return {"players": ps, "default": _default_account(ps)}

    @app.get("/api/players/{account}/review")
    def player_review(account: str, fight: int | None = None, session: int | None = None,
                      sessions: int | None = None, start: str | None = Query(None, alias="from"),
                      end: str | None = Query(None, alias="to"),
                      profession: str | None = None) -> dict[str, Any]:
        rows, fights = state.db.player_fight_rows(account)
        if not rows:
            raise HTTPException(404, "No analyzed fights for this player")
        # Only rows in the fight count (as everywhere in the review): a squad member elsewhere
        # on the map has a row but no recap.
        if fight is not None and not any(r["fight_id"] == fight and r["in_fight"]
                                         for r in rows):
            raise HTTPException(404, "This player was not in that fight")
        return report.review(account, rows, fights, state.config.settings.detectors,
                             fight=fight, session=session, sessions=sessions, start=start,
                             end=end, profession=profession)

    # ---- fights -----------------------------------------------------------------------
    @app.get("/api/fights")
    def fights(session_id: int | None = None, include_skipped: bool = False,
               limit: int = 300) -> list[dict[str, Any]]:
        return video_routes.mark_videos(
            state.db.fights(session_id=session_id, include_skipped=include_skipped, limit=limit),
            state.db.videos())

    @app.get("/api/fights/{fight_id}")
    def fight(fight_id: int) -> dict[str, Any]:
        f = state.db.fight(fight_id)
        if not f:
            raise HTTPException(404, "Fight not found")
        a = state.db.analysis(fight_id) or {}
        debrief, unverified = split_debrief(a.get("debrief"))
        notes = registry.add_focus(a.get("notes"))
        stats = a.get("stats")
        if stats and stats.get("timeline"):
            # Every player's own series is large; the page asks for one player at a time.
            stats["timeline"].pop("players", None)
        return {"fight": f, "stats": stats, "notes": notes,
                "debrief": debrief, "debriefUnverified": unverified,
                "debriefAt": a.get("debriefAt")}

    @app.get("/api/fights/{fight_id}/players/{key}/timeline")
    def player_timeline(fight_id: int, key: str) -> dict[str, Any]:
        """One squad row's own series, by its `series_key` (see `timeline.series_keys`)."""
        a = state.db.analysis(fight_id) or {}
        tl = (a.get("stats") or {}).get("timeline") or {}
        series = (tl.get("players") or {}).get(key)
        if not series:
            raise HTTPException(404, "No timeline for this player (re-analyze the fight)")
        return {"t": tl.get("t", []), **series}

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
        dumped = s.model_dump(mode="json")
        # The OBS password stays in config.yaml: the page only learns whether one is set, and
        # a save without one keeps it (see put_settings).
        dumped["obs"]["password_set"] = bool(dumped["obs"].pop("password", ""))
        return {
            "settings": dumped,
            "detectors": registry.describe(s.detectors),
            "personalRules": coach_registry.describe(s.detectors),
            "resolvedLogDir": str(s.resolved_log_dir() or ""),
            "defaultLogDir": str(paths.default_log_dir() or ""),
            "resolvedEiPath": str(s.resolved_ei_path()),
            "templatesFile": str(paths.data_dir() / "templates.yaml"),
        }

    @app.put("/api/settings")
    def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        # Where the API listens is not a page setting: a LAN address would expose it (and the
        # local-only checks would then block the app's own window).
        for key in ("host", "port"):
            if key in patch and patch[key] != getattr(state.config.settings, key):
                raise HTTPException(400, f"{key} can only be changed in config.yaml")
        if isinstance(patch.get("obs"), dict):
            obs = dict(patch["obs"])
            obs.pop("password_set", None)
            if obs.get("password") is None:  # not sent: keep the stored one
                obs.pop("password", None)
            patch = {**patch, "obs": obs}
        try:
            if "detectors" in patch:
                patch = {**patch, "detectors": registry.check_overrides(patch["detectors"])}
            old_obs = state.config.settings.obs
            state.config.update(patch)
        except Exception as e:
            raise HTTPException(400, f"Invalid settings: {e}") from e
        if state.config.settings.obs != old_obs:
            state.obs.settings_changed()
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

    # ---- updates (plan 17) ------------------------------------------------------------
    @app.get("/api/update")
    def update_status() -> dict[str, Any]:
        return state.updater.status()

    @app.post("/api/update/check")
    def update_check() -> dict[str, Any]:
        return state.updater.check()

    @app.post("/api/update/skip")
    def update_skip(body: SkipBody) -> dict[str, Any]:
        state.config.update({"skipped_update": body.version.strip()[:32] or None})
        return state.updater.status()

    @app.post("/api/update/install")
    def update_install() -> dict[str, Any]:
        # No body: only the release found by the app's own last check is ever installed.
        try:
            return state.updater.install()
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/update/retry")
    def update_retry() -> dict[str, Any]:
        try:
            return state.updater.retry_unfinished()
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    # ---- troubleshooting --------------------------------------------------------------
    @app.post("/api/diagnostics")
    def make_diagnostics(body: DiagnosticsRequest | None = None) -> dict[str, Any]:
        """Build the report a user sends when something breaks (also saved as a file)."""
        text = diagnostics.build_report(state, body.userAgent if body else None)
        try:
            path = str(diagnostics.save_report(state.data_dir, text))
        except OSError:
            log.warning("could not save the diagnostics report", exc_info=True)
            path = None
        return {"text": text, "path": path}

    @app.post("/api/diagnostics/open-folder")
    def open_data_folder() -> dict[str, Any]:
        return {"opened": diagnostics.open_folder(state.data_dir), "path": str(state.data_dir)}

    @app.post("/api/diagnostics/dismiss")
    def dismiss_crashes() -> dict[str, bool]:
        diagnostics.dismiss_crashes(state.data_dir)
        return {"ok": True}

    client_errors = {"count": 0}

    @app.post("/api/client-error")
    def client_error(body: ClientError) -> dict[str, bool]:
        """Errors from the page (the window has no console a user could open)."""
        client_errors["count"] += 1
        n = client_errors["count"]
        if n > MAX_CLIENT_ERRORS:
            return {"ok": False}
        log.error("frontend error at %s: %s%s", (body.url or "?")[:300], body.message[:2000],
                  f"\n{body.stack[:8000]}" if body.stack else "")
        if n == MAX_CLIENT_ERRORS:
            log.error("further frontend errors in this run are not logged")
        return {"ok": True}

    # ---- live events ------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        if not (_host_ok(socket.headers.get("host", ""))
                and _origin_ok(socket.headers.get("origin"))):
            await socket.close(code=1008)  # policy violation: not a local page
            return
        await socket.accept()
        q = state.bus.subscribe()

        async def send_events() -> None:
            await socket.send_json({"type": "hello", "recording": state.recorder.state(),
                                    "queue": state.processor.state()})
            while True:
                await socket.send_json(await q.get())

        async def until_closed() -> None:
            # The page sends nothing; reading is how a closed socket is noticed. uvicorn queues
            # a disconnect when the page goes away and when the server shuts down. Waiting only
            # for events left this handler in q.get() until the next one, and uvicorn waits for
            # it at shutdown with no time limit: after SIGTERM the process never exited.
            while (await socket.receive())["type"] != "websocket.disconnect":
                pass

        sender = asyncio.create_task(send_events())
        receiver = asyncio.create_task(until_closed())
        try:
            await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (sender, receiver):
                task.cancel()
            results = await asyncio.gather(sender, receiver, return_exceptions=True)
            state.bus.unsubscribe(q)
        for result in results:  # a closed socket is expected; anything else is a bug to log
            if isinstance(result, Exception) and not isinstance(
                    result, (WebSocketDisconnect, RuntimeError, OSError)):
                raise result

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
