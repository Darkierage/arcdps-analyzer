"""Files the app owns: parsed Elite Insights JSON, their replay caches and copies of uploaded
logs.

Original arcdps logs are never deleted - only files inside the app's data folder.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..replay import CACHE_SUFFIX, cache_path, sources_for
from .db import Database

log = logging.getLogger(__name__)

EI_SUFFIXES = (".json", ".json.gz")


def _owned_dirs(db: Database) -> list[Path]:
    """App-owned folders next to this database (never the global data folder of another DB)."""
    root = db.path.resolve().parent
    return [(root / "ei").resolve(), (root / "uploads").resolve()]


def _owned(path: Path, db: Database) -> bool:
    p = path.resolve()
    return any(p.is_relative_to(d) for d in _owned_dirs(db))


def remove_fight_files(rows: Iterable[dict[str, Any]], db: Database) -> int:
    """Delete parsed JSON / uploaded copies of removed fights unless another fight uses them."""
    still_used = db.referenced_files()
    removed = 0
    for r in rows:
        for value in (r.get("ei_json"), r.get("log_path")):
            if not value or value in still_used:
                continue
            path = Path(value)
            targets = [path]
            if value == r.get("ei_json"):
                targets.append(cache_path(path))  # the replay made from it goes with it
            for t in targets:
                if _owned(t, db) and t.is_file():
                    try:
                        t.unlink()
                        removed += 1
                    except OSError as e:
                        log.warning("could not delete %s: %s", t, e)
    return removed


def cleanup_orphans(db: Database, min_age_s: float = 60) -> int:
    """Delete parsed JSON and uploads that no fight references (e.g. left by older versions)."""
    used = {str(Path(v).resolve()) for v in db.referenced_files()}
    now = time.time()
    removed = 0
    for d in _owned_dirs(db):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file() or f.name.endswith(".conf"):
                continue
            if d.name == "ei" and not f.name.endswith(EI_SUFFIXES):
                continue
            if d.name == "ei" and f.name.endswith(CACHE_SUFFIX):
                # A replay cache lives as long as the EI JSON it was made from is used.
                keep = any(str(src.resolve()) in used for src in sources_for(f))
            else:
                keep = str(f.resolve()) in used
            if keep or now - f.stat().st_mtime < min_age_s:
                continue
            try:
                f.unlink()
                removed += 1
            except OSError as e:
                log.warning("could not delete %s: %s", f, e)
    if removed:
        log.info("removed %d unused parsed/uploaded files", removed)
    return removed
