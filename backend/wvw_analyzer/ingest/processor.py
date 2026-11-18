"""Single-worker processing queue: EI parse -> analysis -> store -> live event."""

from __future__ import annotations

import logging
import multiprocessing
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from ..analysis import analysis_job
from ..config import ConfigStore
from ..events import EventBus
from ..store.db import Database
from ..store.files import remove_fight_files
from .ei_runner import EIError, EIRunner
from .evtc import is_wvw_log

log = logging.getLogger(__name__)


class Processor:
    def __init__(self, db: Database, config: ConfigStore, bus: EventBus):
        self.db = db
        self.config = config
        self.bus = bus
        self._q: queue.Queue[tuple[int, bool]] = queue.Queue()
        self._pending: set[int] = set()
        self._cancellable: set[int] = set()  # queued imports (recording fights are never cancelled)
        self._cancelled: set[int] = set()
        self._lock = threading.Lock()
        self._current: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="processor", daemon=True)
        self.on_done: list[Callable[[int], None]] = []
        self.use_worker = True  # tests may analyze in-process
        self.last_done_at: float | None = None

    def start(self) -> None:
        # Resume work interrupted by a previous shutdown.
        for f in self.db.active_fights():
            self.enqueue(f["id"])
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put((-1, False))

    def enqueue(self, fight_id: int, reparse: bool = False, cancellable: bool = False) -> None:
        with self._lock:
            if fight_id in self._pending:
                return
            self._pending.add(fight_id)
            self._cancelled.discard(fight_id)
            if cancellable:
                self._cancellable.add(fight_id)
        self.db.set_status(fight_id, "queued")
        self._emit(fight_id)
        self._q.put((fight_id, reparse))

    def cancel_pending(self) -> int:
        """Drop queued imports that haven't started; they can simply be imported again later."""
        with self._lock:
            ids = [i for i in self._cancellable if i in self._pending and i != self._current]
            for i in ids:
                self._pending.discard(i)
                self._cancellable.discard(i)
                self._cancelled.add(i)
        for i in ids:
            remove_fight_files(self.db.delete_fight(i), self.db)
        self.db.delete_empty_sessions("import")
        log.info("cancelled %d queued imports", len(ids))
        self.bus.publish({"type": "queue", "queue": self.state()})
        self.bus.publish({"type": "cancelled", "fightIds": ids})
        return len(ids)

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {"pending": len(self._pending), "current": self._current,
                    "cancellable": len(self._cancellable & self._pending)}

    def _analyze(self, ei_json: Path) -> dict[str, Any]:
        """Analyze in a fresh worker process (memory is returned to the OS afterwards)."""
        settings = self.config.settings.model_dump(mode="json")
        if not self.use_worker:
            return analysis_job(str(ei_json), settings)
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
            return pool.submit(analysis_job, str(ei_json), settings).result()

    def runner(self) -> EIRunner:
        return EIRunner(self.config.settings.resolved_ei_path())

    def _emit(self, fight_id: int) -> None:
        row = self.db.fight(fight_id)
        if row:
            self.bus.publish({"type": "fight", "fight": row})
        self.bus.publish({"type": "queue", "queue": self.state()})

    def _run(self) -> None:
        while not self._stop.is_set():
            fight_id, reparse = self._q.get()
            if fight_id < 0:
                break
            with self._lock:
                if fight_id in self._cancelled:
                    self._cancelled.discard(fight_id)
                    continue
                self._current = fight_id
            try:
                self._process(fight_id, reparse)
            except Exception as e:  # keep the worker alive whatever happens
                log.exception("processing fight %s failed", fight_id)
                self.db.set_status(fight_id, "failed", f"{type(e).__name__}: {e}")
            finally:
                with self._lock:
                    self._pending.discard(fight_id)
                    self._cancellable.discard(fight_id)
                    self._current = None
                self._emit(fight_id)

    def _process(self, fight_id: int, reparse: bool) -> None:
        row = self.db.fight(fight_id)
        if not row:
            return
        ei_json = Path(row["ei_json"]) if row.get("ei_json") else None
        if reparse or ei_json is None or not ei_json.exists():
            log_path = Path(row["log_path"])
            if not log_path.exists():
                self.db.set_status(fight_id, "failed", f"Log file not found: {log_path}")
                return
            if is_wvw_log(log_path) is False:  # PvE / golem log: skip without running EI
                self.db.set_skipped(fight_id, "not a WvW log", None)
                return
            self.db.set_status(fight_id, "parsing")
            self._emit(fight_id)
            try:
                ei_json = self.runner().parse(log_path)
            except EIError as e:
                self.db.set_status(fight_id, "failed", str(e))
                return
            self.db.set_ei_json(fight_id, str(ei_json))

        self.db.set_status(fight_id, "analyzing")
        self._emit(fight_id)
        t0 = time.perf_counter()
        result = self._analyze(ei_json)
        if result["kind"] == "skipped":
            self.db.set_skipped(fight_id, result["reason"], result["summary"])
            return
        self.db.save_analysis(fight_id, result["summary"], result["stats"], result["notes"])
        log.info("analyzed fight %s in %.2fs", fight_id, time.perf_counter() - t0)
        self.last_done_at = time.time()
        for cb in self.on_done:
            try:
                cb(fight_id)
            except Exception:
                log.exception("on_done callback failed")
