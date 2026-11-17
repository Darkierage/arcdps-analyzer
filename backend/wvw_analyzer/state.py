"""Wires the long-lived services together."""

from __future__ import annotations

import json
import logging
import threading
import time

from .config import ConfigStore
from .events import EventBus
from .ingest.processor import Processor
from .ingest.recorder import Recorder
from .llm.manager import LlmService
from .store.db import Database

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, config: ConfigStore | None = None, db: Database | None = None):
        self.config = config or ConfigStore()
        self.db = db or Database()
        self.bus = EventBus()
        self.processor = Processor(self.db, self.config, self.bus)
        self.recorder = Recorder(self.db, self.config, self.bus, self.processor)
        self.llm = LlmService(self.config, self.bus)
        self._stop = threading.Event()

    def start(self) -> None:
        self.db.close_open_sessions()
        self.processor.start()
        self.recorder.start_auto_watch()
        threading.Thread(target=self._auto_debrief_loop, name="auto-debrief", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self.recorder.recording:
            self.recorder.stop()
        self.processor.stop()
        self.llm.shutdown()

    def write_debrief(self, fight_id: int) -> dict:
        fight = self.db.fight(fight_id)
        analysis = self.db.analysis(fight_id)
        if not fight or not analysis or fight["status"] != "done":
            raise ValueError("Fight is not analyzed")
        result = self.llm.debrief(fight["summary"], analysis["notes"])
        stored = result["text"]
        if result["unverified"]:
            stored += "\n\n" + json.dumps({"unverified": result["unverified"]})
        self.db.save_debrief(fight_id, stored)
        self.bus.publish({"type": "debrief", "fightId": fight_id})
        return result

    def _auto_debrief_loop(self) -> None:
        """Write debriefs once the raid is quiet (no new logs for quiet_minutes)."""
        while not self._stop.wait(30):
            s = self.config.settings.llm
            if not (s.enabled and s.auto_debrief) or self.llm.busy:
                continue
            last = self.processor.last_done_at
            if not last or time.time() - last < s.quiet_minutes * 60:
                continue
            if self.processor.state()["pending"]:
                continue
            for f in self.db.fights(include_skipped=False, limit=50):
                if f["status"] != "done":
                    continue
                a = self.db.analysis(f["id"])
                if a and not a["debrief"]:
                    try:
                        self.write_debrief(f["id"])
                    except Exception:
                        log.exception("auto debrief failed for fight %s", f["id"])
                        break
                    if self.processor.state()["pending"]:
                        break  # new fight arrived, back off
