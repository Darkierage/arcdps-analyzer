"""Recording sessions: watch the arcdps folder and queue every new, completed log.

A log counts as complete once its size and mtime stopped changing for ``stable_s`` seconds and
it can be opened for reading. Polling is used instead of filesystem events because it works the
same on Windows, WSL (/mnt/c) and network folders, and the folder is small.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..config import ConfigStore
from ..events import EventBus
from ..store.db import Database
from .evtc import is_wvw_log
from .processor import Processor

log = logging.getLogger(__name__)

LOG_EXTS = (".zevtc", ".evtc", ".evtc.zip")
GW2_PROCESS = "gw2-64.exe"


def iter_logs(root: Path, since: float | None = None, until: float | None = None):
    """Yield (path, stat) of arcdps logs under root (recursive), optionally by mtime range."""
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
                    elif e.name.lower().endswith(LOG_EXTS):
                        st = e.stat()
                        if since is not None and st.st_mtime < since:
                            continue
                        if until is not None and st.st_mtime > until:
                            continue
                        yield Path(e.path), st
        except OSError as err:
            log.debug("scan %s failed: %s", d, err)


def _readable(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            fh.read(16)
        return True
    except OSError:
        return False


class Recorder:
    def __init__(self, db: Database, config: ConfigStore, bus: EventBus, processor: Processor):
        self.db = db
        self.config = config
        self.bus = bus
        self.processor = processor
        self.session_id: int | None = None
        self.started_at: float | None = None
        self.fights_queued = 0
        self.auto_started = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._watch: threading.Thread | None = None
        self._index: tuple[float, dict[str, tuple[Path, int]]] | None = None

    # ---- recording ---------------------------------------------------------------------
    @property
    def recording(self) -> bool:
        return self.session_id is not None

    def state(self) -> dict[str, Any]:
        log_dir = self.config.settings.resolved_log_dir()
        return {
            "recording": self.recording,
            "sessionId": self.session_id,
            "startedAt": self.started_at,
            "fights": self.fights_queued,
            "autoStarted": self.auto_started,
            "logDir": str(log_dir) if log_dir else None,
            "logDirOk": bool(log_dir and log_dir.is_dir()),
        }

    def start(self, name: str | None = None, auto: bool = False) -> dict[str, Any]:
        with self._lock:
            if self.recording:
                return self.state()
            log_dir = self.config.settings.resolved_log_dir()
            if not log_dir or not log_dir.is_dir():
                raise RuntimeError("arcdps log folder not found - set it in Settings")
            name = name or f"Raid {datetime.now():%Y-%m-%d %H:%M}"
            self.session_id = self.db.create_session(name, "recording")
            self.started_at = time.time()
            self.fights_queued = 0
            self.auto_started = auto
            self._stop.clear()
            self._thread = threading.Thread(target=self._scan_loop, args=(log_dir,),
                                            name="recorder", daemon=True)
            self._thread.start()
        log.info("recording started (session %s) watching %s", self.session_id, log_dir)
        self._emit()
        return self.state()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self.recording:
                return self.state()
            self._stop.set()
            sid = self.session_id
            self.session_id = None
            self.started_at = None
            self.auto_started = False
        if self._thread:
            self._thread.join(timeout=5)
        if sid is not None:
            self.db.end_session(sid)
        log.info("recording stopped (session %s)", sid)
        self._emit()
        return self.state()

    def _emit(self) -> None:
        self.bus.publish({"type": "recording", "recording": self.state()})

    def _scan_loop(self, log_dir: Path) -> None:
        cfg = self.config.settings.recording
        since = (self.started_at or time.time()) - 2.0
        known = self.db.known_paths()
        candidates: dict[str, tuple[int, float, float]] = {}  # path -> (size, mtime, stable_since)
        while not self._stop.wait(cfg.poll_interval_s):
            now = time.time()
            for path, st in iter_logs(log_dir, since=since):
                key = str(path)
                if key in known:
                    continue
                prev = candidates.get(key)
                sig = (st.st_size, st.st_mtime)
                if prev is None or (prev[0], prev[1]) != sig:
                    candidates[key] = (st.st_size, st.st_mtime, now)
                    continue
                if now - prev[2] < cfg.stable_s or st.st_size == 0 or not _readable(path):
                    continue
                candidates.pop(key, None)
                known.add(key)
                fid = self.db.add_fight(key, self.session_id, st.st_mtime)
                if fid is not None:
                    self.fights_queued += 1
                    log.info("new log %s -> fight %s", path.name, fid)
                    self.processor.enqueue(fid)
                    self._emit()

    # ---- manual import -----------------------------------------------------------------
    def import_logs(self, folder: Path | None = None, since: float | None = None,
                    until: float | None = None, files: list[str] | None = None) -> dict[str, int]:
        """Queue existing logs; sessions are grouped by the log's date (one per raid day)."""
        if files:
            items = [(Path(f), Path(f).stat()) for f in files if Path(f).is_file()]
        else:
            root = folder or self.config.settings.resolved_log_dir()
            if not root or not root.is_dir():
                raise RuntimeError(f"Folder not found: {root}")
            items = list(iter_logs(root, since=since, until=until))
        known = self.db.known_paths()
        added = skipped = 0
        fight_ids: list[int] = []
        sessions: dict[str, int] = {}
        for path, st in sorted(items, key=lambda x: x[1].st_mtime):
            if str(path) in known:
                skipped += 1
                existing_fight = self.db.fight_by_path(str(path))
                if existing_fight:
                    fight_ids.append(existing_fight["id"])
                continue
            day = _log_day(path, st.st_mtime)
            if day not in sessions:
                name = f"Import {day}"
                existing = self.db.session_by_name(name, "import")
                sessions[day] = existing["id"] if existing else self.db.create_session(
                    name, "import")
            fid = self.db.add_fight(str(path), sessions[day], st.st_mtime)
            if fid is not None:
                added += 1
                fight_ids.append(fid)
                self.processor.enqueue(fid, cancellable=True)
        for sid in sessions.values():
            self.db.end_session(sid)
        return {"added": added, "alreadyKnown": skipped, "fightIds": fight_ids}

    def store_upload(self, filename: str, data: bytes) -> Path | None:
        """Place an uploaded log where import can read it; None if it isn't a WvW log.

        If the same log already sits in the arcdps folder (same name and size), that original
        path is used so the fight isn't imported twice; otherwise it's saved under data/uploads.
        """
        name = Path(filename).name
        if not name.lower().endswith(LOG_EXTS):
            raise ValueError(f"Not an arcdps log: {name} (expected .zevtc or .evtc)")
        if not data:
            raise ValueError(f"{name} is empty")
        if is_wvw_log(data) is False:
            return None
        original = self._log_index().get(name)
        if original and original[1] == len(data):
            return original[0]
        uploads = paths.data_dir() / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        dest = uploads / name
        if dest.exists() and dest.stat().st_size != len(data):
            dest = uploads / f"{dest.stem}-{int(time.time())}{dest.suffix}"
        if not dest.exists():
            dest.write_bytes(data)
        return dest

    def _log_index(self) -> dict[str, tuple[Path, int]]:
        """name -> (path, size) of logs in the arcdps folder, cached briefly for bulk uploads."""
        now = time.time()
        if self._index is not None and now - self._index[0] < 30:
            return self._index[1]
        index: dict[str, tuple[Path, int]] = {}
        log_dir = self.config.settings.resolved_log_dir()
        if log_dir and log_dir.is_dir():
            for path, st in iter_logs(log_dir):
                index[path.name] = (path, st.st_size)
        self._index = (now, index)
        return index

    # ---- auto record with the game ------------------------------------------------------
    def start_auto_watch(self) -> None:
        if sys.platform != "win32" or self._watch is not None:
            return
        self._watch = threading.Thread(target=self._game_watch, name="gw2-watch", daemon=True)
        self._watch.start()

    def _game_watch(self) -> None:
        import psutil

        while True:
            time.sleep(10)
            if not self.config.settings.recording.auto_record:
                continue
            running = any((p.info.get("name") or "").lower() == GW2_PROCESS
                          for p in psutil.process_iter(["name"]))
            try:
                if running and not self.recording:
                    self.start(auto=True)
                elif not running and self.recording and self.auto_started:
                    self.stop()
            except Exception:
                log.exception("auto record toggle failed")


def _log_day(path: Path, mtime: float) -> str:
    m = re.match(r"(\d{4})(\d{2})(\d{2})-", path.name)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
