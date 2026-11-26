"""Filesystem locations for app resources, tools and user data."""

from __future__ import annotations

import os
import platform
import sys
from functools import cache
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def is_wsl() -> bool:
    return sys.platform == "linux" and "microsoft" in platform.uname().release.lower()


@cache
def app_root() -> Path:
    """Directory holding bundled resources (bin/, frontend build, default config)."""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """Read-only files bundled inside the package (PyInstaller puts them in _MEIPASS)."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", app_root()))
    return app_root()


@cache
def data_dir() -> Path:
    """Writable user data: config, database, parsed EI JSON cache, models."""
    env = os.environ.get("WVW_DATA_DIR")
    if env:
        path = Path(env)
    elif FROZEN and sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "WvWAnalyzer"
    else:
        path = app_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bin_dir() -> Path:
    return app_root() / "bin"


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def frontend_dir() -> Path:
    if FROZEN:
        return resource_dir() / "frontend"
    return app_root() / "frontend" / "build"


def default_ei_exe() -> Path:
    return bin_dir() / "GW2EI" / "GuildWars2EliteInsights-CLI.exe"


def default_log_dir() -> Path | None:
    """Best guess of the arcdps log folder (Windows native or WSL)."""
    rel = Path("Guild Wars 2") / "addons" / "arcdps" / "arcdps.cbtlogs"
    candidates: list[Path] = []
    if sys.platform == "win32":
        home = Path.home()
        candidates += [home / "Documents" / rel, home / "OneDrive" / "Documents" / rel]
    elif is_wsl():
        users = Path("/mnt/c/Users")
        if users.is_dir():
            for user in sorted(users.iterdir()):
                candidates += [user / "Documents" / rel, user / "OneDrive" / "Documents" / rel]
    for c in candidates:
        try:
            if c.is_dir():
                return c
        except OSError:
            continue
    return None


def default_video_dirs() -> list[Path]:
    """Where screen recorders save by default: the user's Videos folder (OBS, Game Bar's
    Captures and NVIDIA's per-game folders sit inside it)."""
    home = Path.home()
    return [d for d in (home / "Videos", home / "OneDrive" / "Videos") if d.is_dir()]
