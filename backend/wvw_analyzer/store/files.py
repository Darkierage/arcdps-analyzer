"""Files the app owns: parsed Elite Insights JSON and copies of uploaded logs.

Original arcdps logs are never deleted - only files inside the app's data folder.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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
            if _owned(path, db) and path.is_file():
                try:
                    path.unlink()
                    removed += 1
                except OSError as e:
                    log.warning("could not delete %s: %s", path, e)
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
            if str(f.resolve()) in used or now - f.stat().st_mtime < min_age_s:
                continue
            try:
                f.unlink()
                removed += 1
            except OSError as e:
                log.warning("could not delete %s: %s", f, e)
    if removed:
        log.info("removed %d unused parsed/uploaded files", removed)
    return removed
