"""Install, update and remove the in-game overlay (a Raidcore Nexus addon, built from `addon/`).

The app only ever touches its own two entries in `<GW2>/addons`: `WvWAnalyzer.dll` and the
addon's settings folder `WvWAnalyzer/`. It never installs or changes Nexus or arcdps.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)

ADDON_DLL = "WvWAnalyzer.dll"
ADDON_DIR = "WvWAnalyzer"  # created by Nexus for the addon's settings
GW2_EXE = "Gw2-64.exe"
NEXUS_URL = "https://raidcore.gg/Nexus"
LOCKED = "Guild Wars 2 is using the addon. Close the game, then try again."


def bundled_dll() -> Path:
    return paths.bin_dir() / "addon" / ADDON_DLL


def _is_gw2_dir(d: Path) -> bool:
    try:
        return (d / GW2_EXE).is_file()
    except OSError:
        return False


def _running_gw2_dirs() -> list[Path]:
    """Folder of a running Gw2-64.exe (Windows only; WSL can't see Windows processes)."""
    if sys.platform != "win32":
        return []
    try:
        import psutil
    except ImportError:
        return []
    out = []
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info.get("name") or "").lower() == GW2_EXE.lower() and p.info.get("exe"):
            out.append(Path(p.info["exe"]).parent)
    return out


def game_running() -> bool | None:
    """True/False on Windows; None where the game's process can't be seen (WSL)."""
    if sys.platform != "win32":
        return None
    try:
        import psutil
    except ImportError:
        return None
    return any((p.info.get("name") or "").lower() == GW2_EXE.lower()
               for p in psutil.process_iter(["name"]))


def candidate_dirs() -> list[Path]:
    out = _running_gw2_dirs()
    if sys.platform == "win32":
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(var):
                out.append(Path(os.environ[var]) / "Guild Wars 2")
    elif paths.is_wsl():
        out += [Path("/mnt/c/Program Files/Guild Wars 2"),
                Path("/mnt/c/Program Files (x86)/Guild Wars 2")]
    return out


def find_gw2_dir(override: str | None) -> Path | None:
    if override:
        d = Path(override)
        return d if _is_gw2_dir(d) else None
    return next((d for d in candidate_dirs() if _is_gw2_dir(d)), None)


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def status(override: str | None) -> dict[str, Any]:
    gw2 = find_gw2_dir(override)
    addons = gw2 / "addons" if gw2 else None
    bundled = bundled_dll()
    installed = addons / ADDON_DLL if addons else None
    installed_hash = _sha256(installed) if installed else None
    return {
        "gw2Dir": str(gw2) if gw2 else None,
        "override": override,
        "nexus": bool(addons and (addons / "Nexus").is_dir()),
        "arcdps": bool(addons and ((addons / "arcdps").is_dir()
                                   or (addons / "ArcDPS.dll").is_file())),
        "bundled": bundled.is_file(),
        "installed": installed_hash is not None,
        "upToDate": installed_hash is not None and installed_hash == _sha256(bundled),
        "gameRunning": game_running(),
        "nexusUrl": NEXUS_URL,
    }


def _addons_dir(gw2_dir: Path) -> Path:
    if not _is_gw2_dir(gw2_dir):
        raise RuntimeError(f"{GW2_EXE} not found in {gw2_dir}")
    addons = gw2_dir / "addons"
    if not (addons / "Nexus").is_dir():
        raise RuntimeError("Raidcore Nexus isn't installed in this Guild Wars 2 folder. "
                           f"The overlay is a Nexus addon: install Nexus first ({NEXUS_URL}).")
    return addons


def install(gw2_dir: Path) -> None:
    """Copy the bundled DLL into addons/ (atomic replace, so Nexus never sees half a file)."""
    src = bundled_dll()
    if not src.is_file():
        raise RuntimeError(f"The addon isn't bundled with this build ({src} is missing).")
    addons = _addons_dir(gw2_dir)
    target = addons / ADDON_DLL
    part = addons / (ADDON_DLL + ".part")  # not a .dll, so Nexus ignores it
    try:
        shutil.copyfile(src, part)
        os.replace(part, target)
    except PermissionError as e:
        part.unlink(missing_ok=True)
        if target.exists() and game_running() is not False:
            raise RuntimeError(LOCKED) from e
        raise RuntimeError(f"Can't write to {addons}: {e}") from e
    except OSError:
        part.unlink(missing_ok=True)
        raise
    log.info("installed the in-game overlay to %s", target)


def uninstall(gw2_dir: Path) -> None:
    """Remove only our DLL and our settings folder."""
    addons = gw2_dir / "addons"
    try:
        (addons / ADDON_DLL).unlink(missing_ok=True)
    except PermissionError as e:
        raise RuntimeError(LOCKED) from e
    own = addons / ADDON_DIR
    if own.is_dir() and not own.is_symlink():
        shutil.rmtree(own)
    log.info("removed the in-game overlay from %s", addons)


def auto_update(override: str | None) -> bool:
    """After an app upgrade: refresh an installed, outdated addon while the game is closed."""
    if sys.platform != "win32":
        return False
    s = status(override)
    if not (s["installed"] and s["bundled"] and not s["upToDate"] and s["gw2Dir"]):
        return False
    if s["gameRunning"] is not False:
        return False
    try:
        install(Path(s["gw2Dir"]))
        return True
    except (RuntimeError, OSError):
        log.exception("in-game overlay update failed")
        return False
