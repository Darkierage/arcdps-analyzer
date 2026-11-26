"""Wires the long-lived services together."""

from __future__ import annotations

import json
import logging
import threading
import time

from . import addon_install
from .analysis import ANALYZER_VERSION
from .config import ConfigStore
from .events import EventBus
from .ingest.processor import Processor
from .ingest.recorder import Recorder
from .llm.manager import LlmService
from .obs import ObsService
from .store.db import Database
from .store.files import cleanup_orphans

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, config: ConfigStore | None = None, db: Database | None = None):
        self.config = config or ConfigStore()
        self.db = db or Database()
        self.data_dir = self.db.path.parent  # app files (log, crash records) live next to the DB
        self.bus = EventBus()
        self.processor = Processor(self.db, self.config, self.bus)
        self.recorder = Recorder(self.db, self.config, self.bus, self.processor)
        self.llm = LlmService(self.config, self.bus)
        self.obs = ObsService(self.config, self.db, self.bus, self.recorder)
        self.recorder.on_change.append(self.obs.on_recording)
        self._stop = threading.Event()
        self._started_at = time.time()

    def start(self) -> None:
        self._started_at = time.time()
        self.db.close_open_sessions()
        cleanup_orphans(self.db)  # parsed files left behind by deleted fights
        self.processor.start()
        # Fights analyzed by an older version of the analyzer get re-analyzed (from the cached
        # Elite Insights JSON), so new stats columns and detector fixes apply everywhere.
        stale = self.db.stale_fight_ids(ANALYZER_VERSION)
        if stale:
            log.info("re-analyzing %d fights from an older analyzer version", len(stale))
            for fid in stale:
                self.processor.enqueue(fid)
        self.recorder.start_auto_watch()
        self.obs.start()
        threading.Thread(target=addon_install.auto_update, args=(self.config.settings.gw2_dir,),
                         name="addon-update", daemon=True).start()
        threading.Thread(target=self._auto_debrief_loop, name="auto-debrief", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self.recorder.recording:
            self.recorder.stop(wait=True)
        self.obs.stop()  # after the recorder: an OBS recording the app started is stopped first
        self.processor.stop()
        self.llm.shutdown(final=True)

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
        """Write debriefs for the latest recorded raid once it's quiet (no new log for a while).

        Only fights of the most recent *recording* session are considered (not imported
        history), the check is a cheap query, and failures back off instead of retrying every
        poll.
        """
        backoff_until = 0.0
        failures = 0
        while not self._stop.wait(30):
            s = self.config.settings.llm
            if not (s.enabled and s.auto_debrief) or self.llm.busy:
                continue
            now = time.time()
            if now < backoff_until or self.processor.state()["pending"]:
                continue
            last = self.processor.last_done_at or self._started_at
            if now - last < s.quiet_minutes * 60:
                continue
            for fid in self.db.fights_needing_debrief(limit=20):
                try:
                    self.write_debrief(fid)
                    failures = 0
                except Exception as e:
                    failures += 1
                    delay = min(60 * 2 ** failures, 3600)
                    backoff_until = time.time() + delay
                    log.warning("auto debrief failed for fight %s (%s); retrying in %d min",
                                fid, e, delay // 60)
                    break
                if self.processor.state()["pending"]:
                    break  # a new fight arrived - the raid is not quiet any more
