"""User settings, persisted as YAML in the data directory."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from . import paths

log = logging.getLogger(__name__)

# The API only listens on loopback (see api/app.py); a LAN address would expose it.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class FilterSettings(BaseModel):
    """Logs that don't look like a real zerg fight are stored as 'skipped'."""

    min_duration_s: float = Field(20, ge=0)
    min_enemies: int = Field(5, ge=0)
    min_squad: int = Field(5, ge=0)


class RecordingSettings(BaseModel):
    poll_interval_s: float = Field(2.0, ge=0.1, le=60)  # 0 would rescan the folder nonstop
    stable_s: float = Field(3.0, ge=0.5, le=120)
    auto_record: bool = False  # start/stop with the Gw2-64.exe process (Windows only)


FightMode = Literal["zerg", "gvg"]


class GvgSettings(BaseModel):
    """GvG rounds end with an agreed call-off; these tune how rounds and call-offs are found."""

    round_gap_s: float = Field(25, ge=5)  # a damage lull this long inside a log starts a new round
    calloff_grace_s: float = Field(3, ge=0)  # kills this soon after the last damage still count

    @model_validator(mode="after")
    def _grace_inside_gap(self) -> GvgSettings:
        # Otherwise a round's call-off window would overlap the next round.
        if self.calloff_grace_s >= self.round_gap_s:
            raise ValueError("calloff_grace_s must be shorter than round_gap_s")
        return self


class LlmSettings(BaseModel):
    enabled: bool = False
    server_path: str | None = None  # llama-server executable; default: bin/llama/llama-server(.exe)
    model_file: str = "Qwen3-4B-Q4_K_M.gguf"
    threads: int = Field(2, ge=1)
    gpu_layers: int = Field(0, ge=0)
    ctx_size: int = Field(4096, ge=1024)
    max_tokens: int = Field(450, ge=32)
    # Prompt variant (llm/prompts.py), tuned with scripts/llm_bench.py against Claude references.
    prompt: str = "v8_header"
    temperature: float = Field(0.1, ge=0, le=2)
    idle_timeout_s: int = Field(300, ge=30)
    # Write debriefs automatically once no new log arrived for quiet_minutes.
    auto_debrief: bool = False
    quiet_minutes: float = Field(5, ge=0.5)


class VideoSettings(BaseModel):
    # Folders searched for recordings to suggest on a session's Videos tab; empty: the user's
    # Videos folder (and its subfolders one level down).
    folders: list[str] = Field(default_factory=list)
    lead_in_s: float = Field(3, ge=0, le=30)  # a jump into the replay starts this much earlier


class ObsSettings(BaseModel):
    """Optional OBS connection (OBS WebSocket, built into OBS 28+). Always 127.0.0.1."""

    enabled: bool = False
    port: int = Field(4455, ge=1, le=65535)
    password: str = ""  # never returned by the API (see api/app.py)
    control_recording: bool = True  # start/stop OBS recording with the app's recording
    auto_link: bool = True  # link OBS recordings to the fights they cover
    # Warn when OBS writes at least this many GB per hour of recording; 0: never (plan 19).
    warn_gb_per_hour: float = Field(10, ge=0, le=1000)

    @field_validator("warn_gb_per_hour", mode="before")
    @classmethod
    def _empty_limit_is_off(cls, v: Any) -> Any:
        # The Settings field cleared: no limit, as 0 (a number field sends null when empty).
        return 0 if v is None or v == "" else v


class Settings(BaseModel):
    onboarded: bool = False  # first-run setup screen completed
    log_dir: str | None = None
    ei_path: str | None = None
    gw2_dir: str | None = None  # Guild Wars 2 folder for the in-game overlay; None = detect
    host: str = "127.0.0.1"  # loopback only
    port: int = Field(8765, ge=1024, le=65535)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    # Mode for newly added fights; each fight stores its own mode (it can be changed per fight).
    fight_mode: FightMode = "zerg"
    gvg: GvgSettings = Field(default_factory=GvgSettings)
    # Per-detector overrides, e.g. {"stab_gap_deaths": {"enabled": true, "min_downs": 3}}; the
    # personal rules ("My play", names starting with me_) are set here too.
    detectors: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # The account "My play" opens on; None: the account that recorded the most fights.
    my_account: str | None = None
    videos: VideoSettings = Field(default_factory=VideoSettings)
    obs: ObsSettings = Field(default_factory=ObsSettings)
    # Ask GitHub for a newer release at start and once a day (plan 17).
    check_updates: bool = True
    skipped_update: str | None = None  # "Skip this version": no banner for this version

    @field_validator("host")
    @classmethod
    def _loopback(cls, v: str) -> str:
        if v.strip().lower() not in LOOPBACK_HOSTS:
            raise ValueError(f"host must be one of {', '.join(LOOPBACK_HOSTS)}")
        return v.strip()

    def resolved_log_dir(self) -> Path | None:
        if self.log_dir:
            return Path(self.log_dir)
        return paths.default_log_dir()

    def resolved_ei_path(self) -> Path:
        return Path(self.ei_path) if self.ei_path else paths.default_ei_exe()


class ConfigStore:
    """Thread-safe holder of the current settings with YAML persistence."""

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "config.yaml")
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if self.path.exists():
            try:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict):
                    raise ValueError("not a mapping")
                # Installs from before the setup screen existed are already set up.
                raw.setdefault("onboarded", True)
                return _validate_lenient(raw)
            except (OSError, UnicodeError, yaml.YAMLError, ValueError) as e:
                # Never refuse to start over a damaged file (the windowed app has no console):
                # keep a copy for the user and start from the defaults with the setup screen.
                stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
                backup = self.path.with_name(f"{self.path.name}.broken-{stamp}")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    backup = None
                log.warning("config %s is unreadable (%s); starting with defaults, old file: %s",
                            self.path, e, backup)
        settings = Settings()
        if settings.log_dir is None and (d := paths.default_log_dir()):
            settings.log_dir = str(d)
        self._write(settings)
        return settings

    def _write(self, settings: Settings) -> None:
        """Write to a temp file and rename it over the config, so a crash mid-save can't leave
        a truncated file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = settings.model_dump(mode="json")
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def settings(self) -> Settings:
        with self._lock:
            return self._settings

    def update(self, patch: dict[str, Any]) -> Settings:
        with self._lock:
            merged = _deep_merge(self._settings.model_dump(mode="json"), patch)
            if "detectors" in patch:
                # The UI sends the complete set of overrides; replacing (not merging) is what
                # lets a detector be re-enabled or reset to its defaults.
                merged["detectors"] = patch["detectors"] or {}
            self._settings = Settings.model_validate(merged)
            self._write(self._settings)
            return self._settings


def _validate_lenient(raw: dict[str, Any]) -> Settings:
    """Validate a stored config, dropping only the values that are invalid (they fall back to
    their defaults), e.g. one set before a range check existed."""
    for _ in range(50):
        try:
            return Settings.model_validate(raw)
        except ValidationError as e:
            dropped = False
            for err in e.errors():
                *parents, last = err["loc"] or ("",)
                node: Any = raw
                for k in parents:
                    node = node.get(k) if isinstance(node, dict) else None
                if not isinstance(node, dict):
                    continue
                if last in node:
                    log.warning("config: invalid %s=%r dropped (%s)",
                                ".".join(map(str, err["loc"])), node[last], err["msg"])
                    del node[last]  # a section-level error (GvG grace vs gap) drops the section
                    dropped = True
            if not dropped:
                raise ValueError(str(e)) from e
    raise ValueError("config could not be repaired")


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
