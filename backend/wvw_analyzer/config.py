"""User settings, persisted as YAML in the data directory."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from . import paths


class FilterSettings(BaseModel):
    """Logs that don't look like a real zerg fight are stored as 'skipped'."""

    min_duration_s: float = 20
    min_enemies: int = 5
    min_squad: int = 5


class RecordingSettings(BaseModel):
    poll_interval_s: float = 2.0
    stable_s: float = 3.0
    auto_record: bool = False  # start/stop with the Gw2-64.exe process (Windows only)


FightMode = Literal["zerg", "gvg"]


class GvgSettings(BaseModel):
    """GvG rounds end with an agreed call-off; these tune how rounds and call-offs are found."""

    round_gap_s: float = 25  # a damage lull this long inside a log starts a new round
    calloff_grace_s: float = 3  # kills this soon after the last damage still count


class LlmSettings(BaseModel):
    enabled: bool = False
    server_path: str | None = None  # llama-server executable; default: bin/llama/llama-server(.exe)
    model_file: str = "Qwen3-4B-Q4_K_M.gguf"
    threads: int = 2
    gpu_layers: int = 0
    ctx_size: int = 4096
    max_tokens: int = 450
    # Prompt variant (llm/prompts.py), tuned with scripts/llm_bench.py against Claude references.
    prompt: str = "v8_header"
    temperature: float = 0.1
    idle_timeout_s: int = 300
    # Write debriefs automatically once no new log arrived for quiet_minutes.
    auto_debrief: bool = False
    quiet_minutes: float = 5


class Settings(BaseModel):
    onboarded: bool = False  # first-run setup screen completed
    log_dir: str | None = None
    ei_path: str | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    filters: FilterSettings = Field(default_factory=FilterSettings)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    # Mode for newly added fights; each fight stores its own mode (it can be changed per fight).
    fight_mode: FightMode = "zerg"
    gvg: GvgSettings = Field(default_factory=GvgSettings)
    # Per-detector overrides, e.g. {"stab_gap_deaths": {"enabled": true, "min_downs": 3}}
    detectors: dict[str, dict[str, Any]] = Field(default_factory=dict)

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
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            # Installs from before the setup screen existed are already set up.
            raw.setdefault("onboarded", True)
            return Settings.model_validate(raw)
        settings = Settings()
        if settings.log_dir is None and (d := paths.default_log_dir()):
            settings.log_dir = str(d)
        self._write(settings)
        return settings

    def _write(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = settings.model_dump(mode="json")
        self.path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

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


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
