"""Payload for the in-game overlay (the Nexus addon in `addon/`).

The addon only lays out what this module sends: every string is written here, from the stored
analysis, so wording or analysis changes never need an addon update. Bump `SCHEMA` only for
changes the addon must understand (renamed or removed fields); added fields are ignored by it.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import __version__, addon_install
from ..llm.prompts import framing_line, result_line
from ..metrics.aggregate import aggregate_session
from ..state import AppState
from .debrief import split_debrief

SCHEMA = 1
MAX_PROBLEMS = 5
MAX_STRENGTHS = 3
RESULT_LETTER = {"win": "W", "loss": "L", "even": "E", "skirmish": "S"}


def _clock(start: str | None) -> str:
    """EI's "2026-11-17 20:21:55 +01:00" -> "20:21" (the log's own local time)."""
    m = re.search(r"\b(\d{2}:\d{2}):\d{2}", start or "")
    return m.group(1) if m else "--:--"


def _mmss(seconds: float | None) -> str:
    t = round(seconds or 0)
    return f"{t // 60}:{t % 60:02d}"


def _record(results: dict[str, int]) -> str:
    parts = [f"{results[k]}{RESULT_LETTER[k]}" for k in ("win", "loss", "even", "skirmish")
             if results.get(k)]
    return " ".join(parts) or "no fights yet"


def _note(f: dict[str, Any]) -> dict[str, Any]:
    return {"severity": f["severity"], "title": f.get("title") or f["detector"],
            "short": f.get("short") or f.get("cause") or "", "fix": f.get("fix_short") or ""}


def _session_id(state: AppState) -> int | None:
    """The recording session, else the session with the most recent fight."""
    if state.recorder.session_id is not None:
        return state.recorder.session_id
    sessions = state.db.sessions()
    return sessions[0]["id"] if sessions else None


def _fight_block(state: AppState, fight_id: int, done: list[dict[str, Any]]) -> dict[str, Any]:
    f = state.db.fight(fight_id) or {}
    s = f.get("summary") or {}
    a = state.db.analysis(fight_id) or {}
    notes = a.get("notes") or {}
    debrief, unverified = split_debrief(a.get("debrief"))
    ids = [r["id"] for r in done]  # newest first
    i = ids.index(fight_id) if fight_id in ids else -1
    return {
        "id": fight_id,
        "status": f.get("status"),
        "mode": s.get("mode", "zerg"),
        "result": s.get("result"),
        "title": f"{_clock(s.get('start'))}  {s.get('map') or 'WvW'}  {_mmss(s.get('durationS'))}",
        "resultLine": result_line(s) if s else "",
        "framing": framing_line(s, notes) if s else None,
        "issues": [_note(n) for n in notes.get("issues", [])],
        "positives": [_note(n) for n in notes.get("positives", [])],
        "debrief": [ln for ln in (debrief or "").splitlines() if ln.strip()],
        "debriefUnverified": len(unverified),
        "index": len(ids) - i if i >= 0 else None,  # 1 = first fight of the session
        "count": len(ids),
        "prevId": ids[i + 1] if 0 <= i < len(ids) - 1 else None,  # older
        "nextId": ids[i - 1] if i > 0 else None,  # newer
    }


def _session_block(state: AppState, session_id: int) -> dict[str, Any]:
    sess = state.db.session(session_id) or {}
    agg = aggregate_session(state.db.session_analyses(session_id))
    t = agg["totals"]
    return {
        "id": session_id,
        "name": sess.get("name") or "",
        "fights": t["fights"],
        "record": _record(t["results"]),
        "kills": t["enemyDeaths"],
        "deaths": t["squadDeaths"],
        "kdr": t["kdr"],
        "duration": _mmss(t["durationS"]),
        "problems": [{"title": p["title"], "severity": p["severity"], "count": p["count"],
                      "losses": p["losses"]} for p in agg["recurringIssues"][:MAX_PROBLEMS]],
        "strengths": [{"title": p["title"], "count": p["count"]}
                      for p in agg["positives"][:MAX_STRENGTHS]],
    }


def build_overlay(state: AppState, fight_id: int | None = None) -> dict[str, Any]:
    rec = state.recorder.state()
    queue = state.processor.state()
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "version": __version__,
        "recording": {"active": rec["recording"], "logDirOk": rec["logDirOk"]},
        "queue": {"pending": queue["pending"], "busy": queue["current"] is not None},
        "session": None,
        "fight": None,
    }
    if fight_id is not None:
        row = state.db.fight(fight_id)
        if not row or row.get("status") != "done":
            raise HTTPException(404, "Fight not found")
        session_id = row.get("session_id")
    else:
        session_id = _session_id(state)
    if session_id is None:
        return payload
    done = [r for r in state.db.fights(session_id=session_id, include_skipped=False)
            if r["status"] == "done"]
    payload["session"] = _session_block(state, session_id)
    payload["session"]["recording"] = rec["sessionId"] == session_id
    # Lets the addon notice a new fight (auto-show) while the player browses older ones.
    payload["session"]["latestId"] = done[0]["id"] if done else None
    target = fight_id if fight_id is not None else (done[0]["id"] if done else None)
    if target is not None:
        payload["fight"] = _fight_block(state, target, done)
    return payload


class AddonInstall(BaseModel):
    gw2Dir: str | None = None  # noqa: N815 - JSON field name


def router(state: AppState) -> APIRouter:
    r = APIRouter()

    # ---- installing the addon (Settings > In-game overlay) ----------------------------
    def _override() -> str | None:
        return state.config.settings.gw2_dir

    @r.get("/api/overlay-addon")
    async def addon_status() -> dict[str, Any]:
        return await run_in_threadpool(addon_install.status, _override())

    @r.post("/api/overlay-addon/install")
    async def addon_install_(body: AddonInstall | None = None) -> dict[str, Any]:
        if body and body.gw2Dir is not None:
            folder = body.gw2Dir.strip() or None
            if folder and addon_install.find_gw2_dir(folder) is None:
                raise HTTPException(400, f"{addon_install.GW2_EXE} not found in {folder}")
            state.config.update({"gw2_dir": folder})
        gw2 = addon_install.find_gw2_dir(_override())
        if gw2 is None:
            raise HTTPException(400, "Guild Wars 2 folder not found - choose it first")
        try:
            await run_in_threadpool(addon_install.install, gw2)
        except (RuntimeError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        return await run_in_threadpool(addon_install.status, _override())

    @r.post("/api/overlay-addon/uninstall")
    async def addon_uninstall() -> dict[str, Any]:
        gw2 = addon_install.find_gw2_dir(_override())
        if gw2 is None:
            raise HTTPException(400, "Guild Wars 2 folder not found")
        try:
            await run_in_threadpool(addon_install.uninstall, gw2)
        except (RuntimeError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        return await run_in_threadpool(addon_install.status, _override())

    # ---- the overlay payload ------------------------------------------------------------

    @r.get("/api/overlay")
    def overlay(request: Request, fight: int | None = None) -> Response:
        body = json.dumps(build_overlay(state, fight), separators=(",", ":")).encode()
        etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(body, media_type="application/json", headers=headers)

    return r
