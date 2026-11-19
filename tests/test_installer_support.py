"""Tests for the pieces the Windows installer relies on."""

import socket
from pathlib import Path

from fastapi.testclient import TestClient

from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore
from wvw_analyzer.ingest.ei_runner import EIRunner
from wvw_analyzer.main import choose_port
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database


def test_ei_runs_on_private_runtime_when_bundled(tmp_path: Path, monkeypatch):
    ei = tmp_path / "GW2EI" / "GuildWars2EliteInsights-CLI.exe"
    ei.parent.mkdir()
    ei.write_bytes(b"")
    ei.with_suffix(".dll").write_bytes(b"")
    dotnet = tmp_path / "dotnet" / "dotnet.exe"
    dotnet.parent.mkdir()
    dotnet.write_bytes(b"")
    monkeypatch.setattr("wvw_analyzer.paths.is_wsl", lambda: False)
    r = EIRunner(ei, out_dir=tmp_path / "out", dotnet=dotnet)
    assert r._base_cmd() == [str(dotnet), str(ei.with_suffix(".dll"))]
    env = r._env()
    assert env["DOTNET_ROOT"] == str(dotnet.parent) and env["DOTNET_MULTILEVEL_LOOKUP"] == "0"
    plain = EIRunner(ei, out_dir=tmp_path / "out", dotnet=False)
    assert plain._base_cmd() == [str(ei)]


def test_choose_port_skips_foreign_program_and_reuses_free():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        chosen, running = choose_port("127.0.0.1", port)
        assert chosen != port and running is False
    free, running = choose_port("127.0.0.1", port)
    assert free == port and running is False


def test_onboarding_flag_new_vs_existing_install(tmp_path: Path):
    fresh = ConfigStore(tmp_path / "new" / "config.yaml")
    assert fresh.settings.onboarded is False  # new user -> setup screen
    old = tmp_path / "old" / "config.yaml"
    old.parent.mkdir()
    old.write_text("log_dir: C:/logs\n", encoding="utf-8")  # config from before the setup screen
    assert ConfigStore(old).settings.onboarded is True


def test_selftest_endpoint(tmp_path: Path):
    logs = tmp_path / "arcdps.cbtlogs" / "WvW (1)"
    logs.mkdir(parents=True)
    (logs / "20261117-200000.zevtc").write_bytes(b"x")
    cfg = ConfigStore(tmp_path / "config.yaml")
    cfg.update({"log_dir": str(logs.parent), "ei_path": str(tmp_path / "missing.exe")})
    state = AppState(cfg, Database(tmp_path / "t.db"))
    with TestClient(create_app(state)) as client:
        t = client.get("/api/selftest").json()
        assert t["onboarded"] is False
        assert t["logDir"]["ok"] is True and t["logDir"]["wvwLogs"] == 1
        assert t["elite"]["ok"] is False and t["elite"]["error"]
        assert "serverInstalled" in t["llm"]
        assert client.get("/api/status").json()["onboarded"] is False
        client.put("/api/settings", json={"onboarded": True})
        assert client.get("/api/status").json()["onboarded"] is True
