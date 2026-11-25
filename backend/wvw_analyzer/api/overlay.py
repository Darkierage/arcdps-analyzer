"""Payload for the in-game overlay (the Nexus addon in `addon/`).

The addon only lays out what this module sends: every string is written here, from the stored
analysis, so wording or analysis changes never need an addon update. Bump `SCHEMA` only for
changes the addon must understand (renamed or removed fields); added fields are ignored by it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from .. import __version__, addon_install
from ..detectors.base import SEVERITY_ORDER
from ..llm.prompts import framing_line, result_line
from ..metrics.aggregate import aggregate_session
from ..state import AppState
from .debrief import split_debrief

SCHEMA = 1
MAX_PROBLEMS = 5
MAX_STRENGTHS = 3
RESULT_LETTER = {"win": "W", "loss": "L", "even": "E", "skirmish": "S"}
RESULT_WORD = {"win": "WIN", "loss": "LOSS", "even": "EVEN", "skirmish": "SKIRMISH"}
# The same wording as the app's fight page.
ISSUES_TITLE = {"loss": "Why this fight was lost", "win": "What to improve"}


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


def _plural(count: Any, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _counted(s: dict[str, Any], key: str) -> int:
    """GvG counts only kills and deaths inside a round, as its result line does (zerg: all)."""
    return int(s.get(key) or 0) - int(s.get(f"{key}Late") or 0)


def _fight_header(s: dict[str, Any]) -> dict[str, Any]:
    """The result block and the small panel's lines, all written here."""
    if not s:
        return {}
    gvg = s.get("mode") == "gvg"
    result = s.get("result")
    rounds = s.get("rounds") or []
    wins, losses = s.get("roundWins", 0), s.get("roundLosses", 0)
    badge = RESULT_WORD.get(result or "", "")
    if gvg and len(rounds) > 1 and badge:
        badge += f" {wins}-{losses}"
    kills, deaths = _counted(s, "enemyDeaths"), _counted(s, "squadDeaths")
    squad = s.get("squadInFight") or s.get("squadCount") or 0
    allies = s.get("allyCount") or 0
    ally_note = f"+{_plural(allies, 'ally').replace('allys', 'allies')}" if allies else ""
    enemies = s.get("enemyCount") or 0
    if gvg:
        facts = [
            {"label": "Rounds", "value": f"{wins}-{losses}", "note": "",
             "tone": "good" if wins > losses else "bad" if losses > wins else ""},
            {"label": "Kills", "value": str(kills), "note": "", "tone": "good"},
            {"label": "Deaths", "value": str(deaths), "note": "", "tone": "bad"},
            {"label": "Players", "value": f"{squad} vs {enemies}", "note": ally_note,
             "tone": ""},
        ]
    else:
        facts = [
            {"label": "Kills", "value": str(kills), "note": "", "tone": "good"},
            {"label": "Deaths", "value": str(deaths), "note": "", "tone": "bad"},
            {"label": "Squad", "value": str(squad), "note": ally_note, "tone": ""},
            {"label": "Enemies", "value": str(enemies), "note": "", "tone": ""},
        ]
    length = s.get("fightS") if gvg else s.get("durationS")
    return {
        "badge": badge,
        "heading": s.get("map") or "WvW",
        "meta": f"{_clock(s.get('start'))} · {_mmss(length or s.get('durationS'))} long",
        "facts": facts,
        "headline": f"{_plural(kills, 'kill')} for {_plural(deaths, 'death')}",
        "numbers": f"{squad}{f'+{allies}' if allies else ''} vs {enemies}",
        "issuesTitle": ISSUES_TITLE.get(result or "", "Key issues"),
    }


def _worst(occurrences: list[dict[str, Any]], fallback: str) -> str:
    """The most severe severity a recurring problem had in any of its fights."""
    seen = [o["severity"] for o in occurrences if o.get("severity") in SEVERITY_ORDER]
    return min(seen, key=SEVERITY_ORDER.__getitem__) if seen else fallback


def _session_id(state: AppState) -> int | None:
    """The recording session, else the session with the most recent fight."""
    if state.recorder.session_id is not None:
        return state.recorder.session_id
    sessions = state.db.sessions()
    return sessions[0]["id"] if sessions else None


def _done_fights(state: AppState, session_id: int) -> list[dict[str, Any]]:
    """Analyzed fights of a session, newest first."""
    return [r for r in state.db.fights(session_id=session_id, include_skipped=False)
            if r["status"] == "done"]


def _fight_block(state: AppState, fight_id: int, done: list[dict[str, Any]]) -> dict[str, Any]:
    f = state.db.fight(fight_id) or {}
    s = f.get("summary") or {}
    a = state.db.analysis_notes(fight_id) or {}
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
        **_fight_header(s),
        "issues": [_note(n) for n in notes.get("issues", [])],
        "moreCount": len(notes.get("more", [])),
        "positives": [_note(n) for n in notes.get("positives", [])],
        "debrief": [ln for ln in (debrief or "").splitlines() if ln.strip()],
        "debriefUnverified": len(unverified),
        "index": len(ids) - i if i >= 0 else None,  # 1 = first fight of the session
        "count": len(ids),
        "prevId": ids[i + 1] if 0 <= i < len(ids) - 1 else None,  # older
        "nextId": ids[i - 1] if i > 0 else None,  # newer
    }


def _session_block(state: AppState, session_id: int,
                   done: list[dict[str, Any]]) -> dict[str, Any]:
    sess = state.db.session(session_id) or {}
    agg = aggregate_session(state.db.session_analyses(session_id, players=False), detail=False)
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
        "problems": [{"title": p["title"], "severity": _worst(p["occurrences"], p["severity"]),
                      "count": p["count"], "losses": p["losses"]}
                     for p in agg["recurringIssues"][:MAX_PROBLEMS]],
        "strengths": [{"title": p["title"], "count": p["count"]}
                      for p in agg["positives"][:MAX_STRENGTHS]],
        # Every analyzed fight, oldest first: the addon draws one square per fight.
        "strip": [{"id": r["id"], "result": r.get("result"),
                   "letter": RESULT_LETTER.get(r.get("result") or "", "?")}
                  for r in reversed(done)],
    }


def build_overlay(state: AppState, fight_id: int | None = None) -> dict[str, Any]:
    rec = state.recorder.state()
    queue = state.processor.state()
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "version": __version__,
        "recording": {"active": rec["recording"], "logDirOk": rec["logDirOk"]},
        "queue": {"pending": queue["pending"], "busy": queue["current"] is not None},
        "latest": None,
        "session": None,
        "fight": None,
    }
    current = _session_id(state)
    current_done = _done_fights(state, current) if current is not None else []
    if current_done:
        # The current session's newest fight, whatever fight is being browsed: the addon goes
        # back to it ("Latest") and opens itself when `addedAt` moves forward. `addedAt` (when
        # the log was picked up) doesn't change on a re-analysis, unlike the fight's status.
        payload["latest"] = {"id": current_done[0]["id"],
                             "addedAt": max(r["created_at"] for r in current_done)}
    if fight_id is not None:
        row = state.db.fight(fight_id)
        if not row or row.get("status") != "done":
            raise HTTPException(404, "Fight not found")
        session_id = row.get("session_id")
    else:
        session_id = current
    if session_id is None:
        return payload
    done = current_done if session_id == current else _done_fights(state, session_id)
    payload["session"] = _session_block(state, session_id, done)
    payload["session"]["recording"] = rec["sessionId"] == session_id
    # Newest fight of this session (addons from 0.5.0 used it; newer ones read `latest`).
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
    # Plain `def` handlers: FastAPI runs them in its thread pool, so the folder checks (slow on
    # a /mnt/c path) never block the event loop.
    def _override() -> str | None:
        return state.config.settings.gw2_dir

    def _gw2_dir(body: AddonInstall | None) -> Path:
        """The folder typed in Settings (stored, like the main Save would), else the saved or
        detected one."""
        if body and body.gw2Dir is not None:
            folder = body.gw2Dir.strip() or None
            if folder and addon_install.find_gw2_dir(folder) is None:
                raise HTTPException(400, f"{addon_install.GW2_EXE} not found in {folder}")
            state.config.update({"gw2_dir": folder})
        gw2 = addon_install.find_gw2_dir(_override())
        if gw2 is None:
            raise HTTPException(400, "Guild Wars 2 folder not found - choose it first")
        return gw2

    @r.get("/api/overlay-addon")
    def addon_status() -> dict[str, Any]:
        return addon_install.status(_override())

    @r.post("/api/overlay-addon/install")
    def addon_install_(body: AddonInstall | None = None) -> dict[str, Any]:
        try:
            addon_install.install(_gw2_dir(body))
        except (RuntimeError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        return addon_install.status(_override())

    @r.post("/api/overlay-addon/uninstall")
    def addon_uninstall(body: AddonInstall | None = None) -> dict[str, Any]:
        try:
            addon_install.uninstall(_gw2_dir(body))
        except (RuntimeError, OSError) as e:
            raise HTTPException(400, str(e)) from e
        return addon_install.status(_override())

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
