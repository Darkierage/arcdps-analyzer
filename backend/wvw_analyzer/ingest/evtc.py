"""Cheap arcdps log header checks (no Elite Insights needed).

An arcdps log starts with a 16-byte header: b"EVTC", an 8-char build date, a revision byte and
the encounter species id (uint16, little endian). WvW logs use species id 1. ``.zevtc`` and
``.evtc.zip`` are zip archives whose single entry is the raw ``.evtc``.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

WVW_SPECIES = 1


def _species_from_header(head: bytes) -> int | None:
    if len(head) < 15 or head[:4] != b"EVTC":
        return None
    return struct.unpack("<H", head[13:15])[0]


def species_id(source: Path | bytes) -> int | None:
    """Encounter species id of a log file or its bytes; None if unreadable."""
    try:
        raw = source if isinstance(source, bytes) else Path(source).read_bytes()
        if raw[:4] == b"EVTC":
            return _species_from_header(raw[:16])
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            if not names:
                return None
            with zf.open(names[0]) as fh:
                return _species_from_header(fh.read(16))
    except (OSError, zipfile.BadZipFile, struct.error):
        return None


def is_wvw_log(source: Path | bytes) -> bool | None:
    """True/False if the header says WvW or not; None if it can't be read (let EI decide)."""
    sid = species_id(source)
    return None if sid is None else sid == WVW_SPECIES
