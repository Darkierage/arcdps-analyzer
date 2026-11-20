"""Installing the in-game overlay addon into a (fake) Guild Wars 2 folder."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wvw_analyzer import addon_install
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database


@pytest.fixture
def bundled(tmp_path: Path, monkeypatch) -> Path:
    dll = tmp_path / "app" / "bin" / "addon" / addon_install.ADDON_DLL
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"MZ v1")
    monkeypatch.setattr(addon_install, "bundled_dll", lambda: dll)
    monkeypatch.setattr(addon_install, "candidate_dirs", lambda: [])
    return dll


def gw2(tmp_path: Path, nexus: bool = True) -> Path:
    d = tmp_path / "Guild Wars 2"
    (d / "addons").mkdir(parents=True)
    (d / addon_install.GW2_EXE).write_bytes(b"")
    (d / "addons" / "Other.dll").write_bytes(b"other addon")
    if nexus:
        (d / "addons" / "Nexus").mkdir()
    return d


def test_install_update_uninstall(tmp_path: Path, bundled: Path):
    d = gw2(tmp_path)
    s = addon_install.status(str(d))
    assert s["gw2Dir"] == str(d) and s["nexus"] and s["bundled"] and not s["installed"]

    addon_install.install(d)
    target = d / "addons" / addon_install.ADDON_DLL
    assert target.read_bytes() == b"MZ v1"
    assert not (d / "addons" / (addon_install.ADDON_DLL + ".part")).exists()
    assert addon_install.status(str(d))["upToDate"]
    addon_install.install(d)  # idempotent

    bundled.write_bytes(b"MZ v2")  # app upgrade
    s = addon_install.status(str(d))
    assert s["installed"] and not s["upToDate"]
    addon_install.install(d)
    assert target.read_bytes() == b"MZ v2"

    (d / "addons" / addon_install.ADDON_DIR).mkdir()
    (d / "addons" / addon_install.ADDON_DIR / "settings.json").write_text("{}")
    addon_install.uninstall(d)
    assert not target.exists() and not (d / "addons" / addon_install.ADDON_DIR).exists()
    # Nothing else is touched.
    assert (d / "addons" / "Other.dll").read_bytes() == b"other addon"
    assert (d / "addons" / "Nexus").is_dir()
    addon_install.uninstall(d)  # nothing to remove: fine


def test_needs_nexus_and_a_gw2_folder(tmp_path: Path, bundled: Path):
    d = gw2(tmp_path, nexus=False)
    assert not addon_install.status(str(d))["nexus"]
    with pytest.raises(RuntimeError, match="Nexus"):
        addon_install.install(d)
    assert not (d / "addons" / addon_install.ADDON_DLL).exists()
    assert addon_install.find_gw2_dir(str(tmp_path)) is None
    with pytest.raises(RuntimeError, match="not found"):
        addon_install.install(tmp_path)


def test_missing_bundle(tmp_path: Path, bundled: Path):
    bundled.unlink()
    with pytest.raises(RuntimeError, match="bundled"):
        addon_install.install(gw2(tmp_path))


def test_locked_dll_gives_a_clear_error(tmp_path: Path, bundled: Path, monkeypatch):
    d = gw2(tmp_path)
    addon_install.install(d)

    def locked(*_a, **_k):
        raise PermissionError("in use")

    monkeypatch.setattr(addon_install.os, "replace", locked)
    monkeypatch.setattr(addon_install, "game_running", lambda: True)
    with pytest.raises(RuntimeError, match="Close the game"):
        addon_install.install(d)
    assert not (d / "addons" / (addon_install.ADDON_DLL + ".part")).exists()


def test_auto_update_only_when_installed_and_game_closed(tmp_path: Path, bundled: Path,
                                                         monkeypatch):
    d = gw2(tmp_path)
    monkeypatch.setattr(addon_install.sys, "platform", "win32")
    monkeypatch.setattr(addon_install, "game_running", lambda: False)
    assert not addon_install.auto_update(str(d))  # not installed: leave it alone
    addon_install.install(d)
    bundled.write_bytes(b"MZ v2")
    monkeypatch.setattr(addon_install, "game_running", lambda: True)
    assert not addon_install.auto_update(str(d))
    monkeypatch.setattr(addon_install, "game_running", lambda: False)
    assert addon_install.auto_update(str(d))
    assert (d / "addons" / addon_install.ADDON_DLL).read_bytes() == b"MZ v2"


def test_api(tmp_path: Path, bundled: Path):
    d = gw2(tmp_path)
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    client = TestClient(create_app(state))
    with client:
        assert client.get("/api/overlay-addon").json()["gw2Dir"] is None
        bad = client.post("/api/overlay-addon/install", json={"gw2Dir": str(tmp_path)})
        assert bad.status_code == 400
        r = client.post("/api/overlay-addon/install", json={"gw2Dir": str(d)})
        assert r.status_code == 200 and r.json()["installed"]
        assert state.config.settings.gw2_dir == str(d)
        r = client.post("/api/overlay-addon/uninstall")
        assert r.status_code == 200 and not r.json()["installed"]
        evil = client.post("/api/overlay-addon/install", headers={"Origin": "https://x.example"})
        assert evil.status_code == 403
