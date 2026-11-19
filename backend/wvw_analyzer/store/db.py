"""SQLite persistence: sessions, fights and their analyses."""

from __future__ import annotations

import json
import sqlite3
import threading
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'recording',      -- recording | import
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS fights (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    log_path TEXT NOT NULL UNIQUE,
    log_name TEXT NOT NULL,
    log_mtime REAL,
    status TEXT NOT NULL,                       -- queued|parsing|analyzing|done|skipped|failed
    error TEXT,
    ei_json TEXT,
    fight_start TEXT,
    result TEXT,
    summary TEXT,                               -- JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fights_session ON fights(session_id);
CREATE INDEX IF NOT EXISTS fights_start ON fights(fight_start);
CREATE TABLE IF NOT EXISTS analyses (
    fight_id INTEGER PRIMARY KEY REFERENCES fights(id) ON DELETE CASCADE,
    stats BLOB,                                 -- zlib(JSON)
    notes TEXT,                                 -- JSON
    players TEXT,                               -- JSON (rows only, for session aggregation)
    debrief TEXT,
    debrief_at TEXT
);
"""

ACTIVE_STATUSES = ("queued", "parsing", "analyzing")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_default(o: Any) -> Any:
    """Serialize numpy scalars/arrays that may slip into analysis results."""
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=_json_default)


def _pack(obj: Any) -> bytes:
    return zlib.compress(_dumps(obj).encode(), 6)


def _unpack(blob: bytes | None) -> Any:
    return json.loads(zlib.decompress(blob)) if blob else None


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "wvw_analyzer.db")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(fights)")}
        if "mode" not in cols:
            # Fights from before GvG mode existed were all analyzed as zerg fights.
            self._conn.execute("ALTER TABLE fights ADD COLUMN mode TEXT NOT NULL DEFAULT 'zerg'")

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    # ---- sessions -------------------------------------------------------------------------
    def create_session(self, name: str, kind: str = "recording") -> int:
        cur = self._exec("INSERT INTO sessions(name, kind, started_at) VALUES (?,?,?)",
                         (name, kind, _now()))
        return int(cur.lastrowid)

    def end_session(self, session_id: int) -> None:
        self._exec("UPDATE sessions SET ended_at=? WHERE id=? AND ended_at IS NULL",
                   (_now(), session_id))

    def close_open_sessions(self) -> None:
        self._exec("UPDATE sessions SET ended_at=? WHERE ended_at IS NULL", (_now(),))

    def rename_session(self, session_id: int, name: str) -> None:
        self._exec("UPDATE sessions SET name=? WHERE id=?", (name, session_id))

    def delete_session(self, session_id: int) -> list[dict[str, Any]]:
        """Delete a session and its fights; returns the removed fight rows (for file cleanup)."""
        with self._lock:
            rows = self._all("SELECT id, log_path, ei_json FROM fights WHERE session_id=?",
                             (session_id,))
            self._exec("DELETE FROM fights WHERE session_id=?", (session_id,))
            self._exec("DELETE FROM sessions WHERE id=?", (session_id,))
        return rows

    def session(self, session_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM sessions WHERE id=?", (session_id,))

    def session_by_name(self, name: str, kind: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM sessions WHERE name=? AND kind=?", (name, kind))

    def sessions(self) -> list[dict[str, Any]]:
        rows = self._all(
            """SELECT s.*,
                 COUNT(f.id) AS fights,
                 SUM(f.status='done') AS analyzed,
                 SUM(f.result='win') AS wins,
                 SUM(f.result='loss') AS losses,
                 SUM(f.result='even') AS evens,
                 MIN(f.fight_start) AS first_fight,
                 MAX(f.fight_start) AS last_fight
               FROM sessions s LEFT JOIN fights f ON f.session_id = s.id
               GROUP BY s.id ORDER BY COALESCE(MAX(f.fight_start), s.started_at) DESC""")
        return rows

    # ---- fights ---------------------------------------------------------------------------
    def add_fight(self, log_path: str, session_id: int | None, mtime: float | None,
                  mode: str = "zerg") -> int | None:
        """Insert a queued fight; returns None if the log is already known."""
        with self._lock:
            try:
                cur = self._conn.execute(
                    """INSERT INTO fights(session_id, log_path, log_name, log_mtime, status,
                       mode, created_at, updated_at) VALUES (?,?,?,?, 'queued', ?, ?, ?)""",
                    (session_id, log_path, Path(log_path).name, mtime, mode, _now(), _now()))
                self._conn.commit()
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                return None

    def fight_by_path(self, log_path: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM fights WHERE log_path=?", (log_path,))

    def known_paths(self) -> set[str]:
        return {r["log_path"] for r in self._all("SELECT log_path FROM fights")}

    def set_status(self, fight_id: int, status: str, error: str | None = None) -> None:
        self._exec("UPDATE fights SET status=?, error=?, updated_at=? WHERE id=?",
                   (status, error, _now(), fight_id))

    def set_ei_json(self, fight_id: int, ei_json: str) -> None:
        self._exec("UPDATE fights SET ei_json=?, updated_at=? WHERE id=?",
                   (ei_json, _now(), fight_id))

    def set_skipped(self, fight_id: int, reason: str, summary: dict[str, Any] | None) -> None:
        self._exec(
            """UPDATE fights SET status='skipped', error=?, summary=?, fight_start=COALESCE(?,
               fight_start), updated_at=? WHERE id=?""",
            (reason, _dumps(summary) if summary else None,
             (summary or {}).get("start"), _now(), fight_id))
        self._exec("DELETE FROM analyses WHERE fight_id=?", (fight_id,))

    def save_analysis(self, fight_id: int, summary: dict[str, Any], stats: dict[str, Any],
                      notes: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE fights SET status='done', error=NULL, fight_start=?, result=?,
                   summary=?, updated_at=? WHERE id=?""",
                (summary.get("start"), summary.get("result"), _dumps(summary), _now(),
                 fight_id))
            self._conn.execute(
                """INSERT INTO analyses(fight_id, stats, notes, players) VALUES (?,?,?,?)
                   ON CONFLICT(fight_id) DO UPDATE SET stats=excluded.stats,
                   notes=excluded.notes, players=excluded.players""",
                (fight_id, _pack(stats), _dumps(notes), _dumps(stats.get("players"))))
            self._conn.commit()

    def set_mode(self, fight_ids: list[int], mode: str) -> None:
        """Change the analysis mode; the old debrief no longer matches, so it is dropped."""
        with self._lock:
            for fid in fight_ids:
                self._conn.execute("UPDATE fights SET mode=?, updated_at=? WHERE id=?",
                                   (mode, _now(), fid))
                self._conn.execute(
                    "UPDATE analyses SET debrief=NULL, debrief_at=NULL WHERE fight_id=?", (fid,))
            self._conn.commit()

    def session_fight_ids(self, session_id: int) -> list[int]:
        return [r["id"] for r in self._all("SELECT id FROM fights WHERE session_id=?",
                                           (session_id,))]

    def save_debrief(self, fight_id: int, text: str) -> None:
        self._exec("UPDATE analyses SET debrief=?, debrief_at=? WHERE fight_id=?",
                   (text, _now(), fight_id))

    @staticmethod
    def _fight_row(r: dict[str, Any]) -> dict[str, Any]:
        r["summary"] = json.loads(r["summary"]) if r.get("summary") else None
        return r

    def fight(self, fight_id: int) -> dict[str, Any] | None:
        r = self._one("SELECT * FROM fights WHERE id=?", (fight_id,))
        return self._fight_row(r) if r else None

    def fights(self, session_id: int | None = None, include_skipped: bool = True,
               limit: int = 500) -> list[dict[str, Any]]:
        where, args = [], []
        if session_id is not None:
            where.append("session_id=?")
            args.append(session_id)
        if not include_skipped:
            where.append("status != 'skipped'")
        sql = "SELECT * FROM fights"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(fight_start, created_at) DESC, id DESC LIMIT ?"
        args.append(limit)
        return [self._fight_row(r) for r in self._all(sql, tuple(args))]

    def active_fights(self) -> list[dict[str, Any]]:
        q = ",".join("?" * len(ACTIVE_STATUSES))
        return self._all(f"SELECT * FROM fights WHERE status IN ({q}) ORDER BY id",
                         ACTIVE_STATUSES)

    def analysis(self, fight_id: int) -> dict[str, Any] | None:
        r = self._one("SELECT * FROM analyses WHERE fight_id=?", (fight_id,))
        if not r:
            return None
        return {
            "stats": _unpack(r["stats"]),
            "notes": json.loads(r["notes"]) if r["notes"] else None,
            "debrief": r["debrief"],
            "debriefAt": r["debrief_at"],
        }

    def session_analyses(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._all(
            """SELECT f.id, f.summary, a.notes, a.players FROM fights f
               JOIN analyses a ON a.fight_id = f.id
               WHERE f.session_id=? AND f.status='done' ORDER BY f.fight_start""",
            (session_id,))
        return [{"id": r["id"], "summary": json.loads(r["summary"]),
                 "notes": json.loads(r["notes"]), "players": json.loads(r["players"])}
                for r in rows]

    def delete_empty_sessions(self, kind: str) -> None:
        self._exec("""DELETE FROM sessions WHERE kind=? AND ended_at IS NOT NULL AND id NOT IN
                      (SELECT DISTINCT session_id FROM fights WHERE session_id IS NOT NULL)""",
                   (kind,))

    def fights_by_names(self, names: list[str]) -> dict[str, int]:
        """log_name -> fight id for logs that are already imported."""
        out: dict[str, int] = {}
        for i in range(0, len(names), 500):
            chunk = names[i:i + 500]
            q = ",".join("?" * len(chunk))
            for r in self._all(f"SELECT id, log_name FROM fights WHERE log_name IN ({q})",
                               tuple(chunk)):
                out[r["log_name"]] = r["id"]
        return out

    def delete_fight(self, fight_id: int) -> list[dict[str, Any]]:
        """Delete a fight; returns the removed row (for file cleanup)."""
        with self._lock:
            rows = self._all("SELECT id, log_path, ei_json FROM fights WHERE id=?", (fight_id,))
            self._exec("DELETE FROM fights WHERE id=?", (fight_id,))
        return rows

    def stale_fight_ids(self, version: int) -> list[int]:
        """Analyzed fights whose stored analysis came from a different analyzer version."""
        out = []
        for r in self._all("SELECT id, summary FROM fights WHERE status='done'"):
            summary = json.loads(r["summary"]) if r["summary"] else {}
            if summary.get("analyzerVersion") != version:
                out.append(r["id"])
        return out

    def fights_needing_debrief(self, limit: int = 20) -> list[int]:
        """Analyzed fights of the most recent recording session that have no debrief yet."""
        row = self._one("SELECT id FROM sessions WHERE kind='recording' "
                        "ORDER BY started_at DESC, id DESC LIMIT 1")
        if not row:
            return []
        return [r["id"] for r in self._all(
            """SELECT f.id FROM fights f JOIN analyses a ON a.fight_id = f.id
               WHERE f.session_id=? AND f.status='done' AND a.debrief IS NULL
               ORDER BY f.fight_start LIMIT ?""", (row["id"], limit))]

    def referenced_files(self) -> set[str]:
        """Every EI JSON and log path still used by a fight."""
        out: set[str] = set()
        for r in self._all("SELECT log_path, ei_json FROM fights"):
            out.update(v for v in (r["log_path"], r["ei_json"]) if v)
        return out

    def all_fight_ids(self, statuses: tuple[str, ...] = ("done", "skipped", "failed")
                      ) -> list[int]:
        q = ",".join("?" * len(statuses))
        return [r["id"] for r in self._all(f"SELECT id FROM fights WHERE status IN ({q})",
                                           statuses)]
