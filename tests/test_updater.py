"""In-app updater (plan 17): release check, signed manifest, download, install hand-off."""

from __future__ import annotations

import base64
import hashlib
import http.client
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from wvw_analyzer import main, updater
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database

API = "https://api.test/releases/latest"
DL = "https://dl.test/v{v}/{name}"
CURRENT = "0.7.0"
INSTALLER = b"MZ fake installer " * 1000


def _pub(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


KEY = Ed25519PrivateKey.generate()
OTHER_KEY = Ed25519PrivateKey.generate()


@pytest.fixture(autouse=True)
def trusted(monkeypatch):
    monkeypatch.setattr(updater, "TRUSTED_KEYS", [_pub(KEY)])
    monkeypatch.setattr(updater, "API_URL", API)
    monkeypatch.delenv(updater.ENV_API, raising=False)
    monkeypatch.delenv(updater.ENV_TEST_KEY, raising=False)


def manifest_for(version: str, data: bytes = INSTALLER, **over) -> bytes:
    m = {"schema": 1, "version": version, "installer": updater.installer_name(version),
         "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
         "published": "2026-12-01", **over}
    return json.dumps(m, indent=1).encode()


class FakeHttp(updater.Http):
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.fail = False
        self.gets: list[str] = []

    def get(self, url: str, max_bytes: int) -> bytes:
        self.gets.append(url)
        if self.fail:
            raise OSError("offline")
        if url not in self.files:
            raise OSError(f"404 {url}")
        return self.files[url]

    def download(self, url, dest, max_bytes, progress):
        data = self.files[url]
        Path(dest).write_bytes(data)
        progress(len(data), len(data))


def publish(http: FakeHttp, version: str, *, manifest: bytes | None = None,
            sig_key: Ed25519PrivateKey | None = KEY, installer: bytes = INSTALLER,
            asset_size: int | None = None, digest: str | None = "auto",
            tag: str | None = None, with_manifest: bool = True) -> None:
    """Put a release like GitHub's on the fake server."""
    name = updater.installer_name(version)
    manifest = manifest if manifest is not None else manifest_for(version)
    assets = [{"name": name, "size": len(installer) if asset_size is None else asset_size,
               "browser_download_url": DL.format(v=version, name=name),
               "digest": ("sha256:" + hashlib.sha256(installer).hexdigest())
               if digest == "auto" else digest}]
    http.files[DL.format(v=version, name=name)] = installer
    if with_manifest:
        for n, body in ((updater.MANIFEST_NAME, manifest),
                        (updater.SIG_NAME, base64.b64encode(sig_key.sign(manifest)))):
            assets.append({"name": n, "size": len(body),
                           "browser_download_url": DL.format(v=version, name=n)})
            http.files[DL.format(v=version, name=n)] = body
    http.files[API] = json.dumps({
        "tag_name": tag or f"v{version}", "body": "What's new\n<b>bold</b>",
        "html_url": f"https://github.test/releases/tag/v{version}",
        "published_at": "2026-12-01T10:00:00Z", "assets": assets}).encode()


class Harness:
    def __init__(self, tmp_path: Path, can_install: bool = True) -> None:
        self.http = FakeHttp()
        self.busy: str | None = None
        self.enabled = True
        self.skipped: str | None = None
        self.events: list[dict] = []
        self.exit = threading.Event()
        self.dir = tmp_path
        self.up = self.make(can_install)

    def make(self, can_install: bool = True, current: str = CURRENT) -> updater.Updater:
        return updater.Updater(self.dir, enabled=lambda: self.enabled,
                               skipped=lambda: self.skipped, busy=lambda: self.busy,
                               publish=self.events.append, request_exit=self.exit.set,
                               http=self.http, current=current, can_install=can_install)

    def install(self) -> dict:
        status = self.up.install()
        assert self.exit.wait(5) or self.up.status()["download"]["state"] == "failed"
        return status


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def _wait_download_done(up: updater.Updater) -> dict:
    for _ in range(200):
        d = up.status()["download"]
        if d and d["state"] in ("ready", "failed"):
            return d
        threading.Event().wait(0.02)
    raise AssertionError("download did not finish")


# ---- versions ---------------------------------------------------------------------------
def test_versions():
    assert updater.parse_version("v0.10.2") == (0, 10, 2)
    assert updater.parse_version("0.8.0-beta") is None
    assert updater.parse_version(None) is None
    assert updater.is_newer("0.10.0", "0.9.9") and not updater.is_newer("0.7.0", "0.7.0")
    assert not updater.is_newer("garbage", "0.7.0")


# ---- check ------------------------------------------------------------------------------
def test_newer_signed_release_can_be_installed(h):
    publish(h.http, "0.8.0")
    s = h.up.check()
    assert s["available"] and s["latest"]["verified"] and s["canInstall"]
    assert s["latest"]["notes"].startswith("What's new")
    assert s["blockedReason"] is None and s["error"] is None
    assert h.events[-1]["type"] == "update"
    # Survives a restart (update.json), without a new check.
    again = h.make().status()
    assert again["available"] and again["latest"]["version"] == "0.8.0"


def test_same_or_older_version_is_not_offered(h):
    publish(h.http, CURRENT)
    assert not h.up.check()["available"]
    publish(h.http, "0.6.9")
    s = h.up.check()
    assert not s["available"] and not s["canInstall"]


def test_manifest_is_fetched_only_for_a_newer_release(h):
    """Up to date: one request per check (review U4)."""
    publish(h.http, CURRENT)
    h.up.check()
    assert h.http.gets == [API]


@pytest.mark.parametrize("error", [http.client.BadStatusLine("HTTP/1.1 garbage"),
                                   http.client.IncompleteRead(b"")])
def test_malformed_reply_is_a_quiet_failure(h, error):
    """A broken reply (a proxy, a hotel login page) is not an OSError (review U5)."""
    def boom(url, max_bytes):
        raise error

    h.http.get = boom
    s = h.up.check()
    assert s["error"] == "Could not reach GitHub" and not s["checking"]


def test_check_loop_survives_an_unexpected_error(h, monkeypatch):
    calls = []

    def check():
        calls.append(1)
        raise RuntimeError("bug")

    monkeypatch.setattr(updater, "FIRST_CHECK_DELAY_S", 0)
    monkeypatch.setattr(updater, "CHECK_INTERVAL_S", 0)
    h.up.check = check
    waits = iter([False, False, True])  # first delay, one loop wait, then stop
    h.up._stop.wait = lambda t: next(waits)
    h.up._loop()
    assert len(calls) == 2  # the loop went on after the first error


def test_tag_that_is_not_a_version_is_ignored(h):
    publish(h.http, "0.8.0", tag="nightly")
    s = h.up.check()
    assert s["latest"] is None and not s["available"] and s["error"] is None


def test_network_error_is_quiet(h):
    h.http.fail = True
    s = h.up.check()
    assert s["error"] == "Could not reach GitHub" and not s["available"]


def test_release_without_manifest_only_links(h):
    publish(h.http, "0.8.0", with_manifest=False)
    s = h.up.check()
    assert s["available"] and not s["latest"]["verified"] and not s["canInstall"]
    assert "can't be verified" in s["blockedReason"]
    assert s["latest"]["url"].endswith("/v0.8.0")


@pytest.mark.parametrize("case", ["tampered", "wrong key", "version mismatch", "replayed old",
                                  "asset size", "github digest", "other installer name",
                                  "no keys in build"])
def test_bad_release_is_not_installable(h, monkeypatch, case):
    kw: dict = {}
    if case == "tampered":
        good = manifest_for("0.8.0")
        kw["manifest"] = good
        publish(h.http, "0.8.0", **kw)
        h.http.files[DL.format(v="0.8.0", name=updater.MANIFEST_NAME)] = \
            good.replace(b'"0.8.0"', b'"0.8.0" ', 1)
    elif case == "wrong key":
        publish(h.http, "0.8.0", sig_key=OTHER_KEY)
    elif case == "version mismatch":
        publish(h.http, "0.8.0", manifest=manifest_for("0.8.1"))
    elif case == "replayed old":  # a genuine old signed manifest under a new tag
        publish(h.http, "0.9.0", manifest=manifest_for("0.6.0"))
    elif case == "asset size":
        publish(h.http, "0.8.0", asset_size=len(INSTALLER) + 1)
    elif case == "github digest":
        publish(h.http, "0.8.0", digest="sha256:" + "0" * 64)
    elif case == "other installer name":
        publish(h.http, "0.8.0", manifest=manifest_for("0.8.0", installer="evil.exe"))
    elif case == "no keys in build":
        monkeypatch.setattr(updater, "TRUSTED_KEYS", [])
        publish(h.http, "0.8.0")
    s = h.up.check()
    assert not s["latest"]["verified"] and s["latest"]["verifyError"]
    assert not s["canInstall"]
    with pytest.raises(ValueError):
        h.up.install()
    assert not h.exit.is_set()


def test_test_key_needs_the_api_override(h, monkeypatch):
    publish(h.http, "0.8.0", sig_key=OTHER_KEY)
    monkeypatch.setenv(updater.ENV_TEST_KEY, _pub(OTHER_KEY))
    assert not h.up.check()["latest"]["verified"]  # test key alone: ignored
    monkeypatch.setenv(updater.ENV_API, API)
    assert h.up.check()["latest"]["verified"]


def test_skipped_version(h):
    publish(h.http, "0.8.0")
    h.skipped = "0.8.0"
    assert h.up.check()["skipped"]
    publish(h.http, "0.8.1", manifest=manifest_for("0.8.1"))
    assert not h.up.check()["skipped"]  # a newer version shows again


# ---- install ----------------------------------------------------------------------------
def test_install_downloads_verifies_and_asks_to_exit(h):
    publish(h.http, "0.8.0")
    h.up.check()
    h.install()
    assert h.exit.is_set()
    pending = h.up.take_pending()
    assert pending and pending.silent and pending.path.read_bytes() == INSTALLER
    assert pending.path.parent == h.dir / "updates"
    assert pending.sha256 == hashlib.sha256(INSTALLER).hexdigest()
    saved = json.loads((h.dir / "update.json").read_text())
    assert saved["attempt"]["version"] == "0.8.0"
    assert h.up.take_pending() is None


def test_install_refuses_when_busy_or_from_source(h, tmp_path):
    publish(h.http, "0.8.0")
    h.up.check()
    h.busy = "Stop recording first"
    assert h.up.status()["blockedReason"] == "Stop recording first"
    with pytest.raises(ValueError, match="Stop recording"):
        h.up.install()
    h.busy = None
    src = h.make(can_install=False)
    assert "installed Windows app" in src.status()["blockedReason"]
    with pytest.raises(ValueError):
        src.install()


def test_tampered_download_is_refused(h):
    publish(h.http, "0.8.0")
    h.up.check()
    url = DL.format(v="0.8.0", name=updater.installer_name("0.8.0"))
    h.http.files[url] = INSTALLER[:-1] + b"X"  # same size, other bytes
    h.up.install()
    d = _wait_download_done(h.up)
    assert d["state"] == "failed" and "signed checksum" in d["error"]
    assert not h.exit.is_set() and h.up.take_pending() is None
    assert not list((h.dir / "updates").iterdir())  # the .part file is removed


def test_cached_release_is_reverified_before_download(h):
    publish(h.http, "0.8.0")
    h.up.check()
    saved = json.loads((h.dir / "update.json").read_text())
    saved["release"]["manifest"] = saved["release"]["manifest"].replace(
        hashlib.sha256(INSTALLER).hexdigest(), "1" * 64)
    (h.dir / "update.json").write_text(json.dumps(saved))
    up = h.make()
    up.install()
    d = _wait_download_done(up)
    assert d["state"] == "failed" and "trusted key" in d["error"]


def test_busy_during_download_stops_the_install(h):
    publish(h.http, "0.8.0")
    h.up.check()
    real = h.http.download

    def slow(*a):
        h.busy = "Wait until the queued logs are analyzed"
        real(*a)

    h.http.download = slow
    h.up.install()
    d = _wait_download_done(h.up)
    assert d["state"] == "failed" and "queued logs" in d["error"]
    assert not h.exit.is_set()


# ---- unfinished update and cleanup -------------------------------------------------------
def _finished_download(h: Harness) -> updater.PendingInstall:
    publish(h.http, "0.8.0")
    h.up.check()
    h.install()
    return h.up.take_pending()


def test_unfinished_update_offers_a_retry(h):
    pending = _finished_download(h)
    (h.dir / "updates" / "old-0.6.0.exe").write_bytes(b"x")
    up = h.make()  # next start, still 0.7.0: the install did not finish
    up.cleanup()
    assert pending.path.exists() and not (h.dir / "updates" / "old-0.6.0.exe").exists()
    s = up.status()
    assert s["unfinished"] == {"version": "0.8.0", "canRetry": True}
    h.exit.clear()
    up.retry_unfinished()
    retry = up.take_pending()
    assert h.exit.is_set() and retry and not retry.silent and retry.path == pending.path


def test_retry_refuses_a_changed_installer(h):
    pending = _finished_download(h)
    pending.path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="damaged"):
        h.make().retry_unfinished()


def test_finished_update_is_forgotten_and_files_cleaned(h, monkeypatch):
    pending = _finished_download(h)
    locked = h.dir / "updates" / "in-use.exe"
    locked.write_bytes(b"x")
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name == "in-use.exe":
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    up = h.make(current="0.8.0")  # the update worked
    up.cleanup()
    assert not pending.path.exists() and locked.exists()
    assert up.status()["unfinished"] is None
    assert json.loads((h.dir / "update.json").read_text())["attempt"] is None


# ---- launching the installer ----------------------------------------------------------------
def test_launch_installer_arguments_and_environment(h, monkeypatch):
    pending = _finished_download(h)
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "x")
    monkeypatch.setenv("_MEIPASS2", "y")
    monkeypatch.delenv("PYINSTALLER_RESET_ENVIRONMENT", raising=False)
    calls = []

    def popen(args, **kw):
        import os
        calls.append((args, kw, dict(os.environ)))

    assert updater.launch_installer(pending, popen)
    args, kw, env = calls[0]
    assert args == [str(pending.path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/RELAUNCH=1"]
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not any(k.startswith(("_PYI", "_MEIPASS")) for k in env)
    assert kw["close_fds"]

    calls.clear()
    updater.launch_installer(updater.PendingInstall(pending.path, pending.sha256, silent=False),
                             popen)
    assert calls[0][0] == [str(pending.path)]  # the retry runs the normal wizard


def test_launch_installer_rechecks_the_file(h):
    pending = _finished_download(h)
    pending.path.write_bytes(INSTALLER + b"!")
    calls = []
    assert not updater.launch_installer(pending, lambda *a, **k: calls.append(a))
    assert not calls


def test_exit_request_closes_window_or_server():
    class Window:
        destroyed = threading.Event()

        def destroy(self):
            self.destroyed.set()

    class Server:
        should_exit = False

    state = type("S", (), {"exit_requested": threading.Event()})()
    api = main.WindowApi()
    api._window = Window()
    server = Server()
    t = main.close_on_exit_request(state, server, api)
    state.exit_requested.set()
    t.join(2)
    assert api._window.destroyed.is_set() and not server.should_exit

    state.exit_requested = threading.Event()
    t = main.close_on_exit_request(state, server, None)
    state.exit_requested.set()
    t.join(2)
    assert server.should_exit


@pytest.mark.parametrize("clean", [True, False])
def test_installer_runs_only_after_a_clean_shutdown(tmp_path, monkeypatch, clean):
    from wvw_analyzer import paths

    monkeypatch.setenv("WVW_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    pending = updater.PendingInstall(tmp_path / "x.exe", "0" * 64)
    launched = []
    monkeypatch.setattr(main, "choose_port", lambda host, port: (port, False))
    monkeypatch.setattr(main.updater, "launch_installer", launched.append)
    monkeypatch.setattr(main.diagnostics, "enable_native_dumps", lambda d: None)
    monkeypatch.setattr(main.diagnostics, "start_heartbeat", lambda d: None)
    monkeypatch.setattr(main.signal, "signal", lambda *a: None)

    def serve(*a):
        if not clean:
            raise RuntimeError("boom")
        return pending

    monkeypatch.setattr(main, "_serve", serve)
    try:
        if clean:
            main.main(["--no-window", "--port", "8798"])
        else:
            with pytest.raises(RuntimeError):
                main.main(["--no-window", "--port", "8798"])
    finally:
        paths.data_dir.cache_clear()
        main._file_log and main.logging.getLogger().removeHandler(main._file_log)
        main._file_log = None
    assert launched == ([pending] if clean else [])


# ---- API --------------------------------------------------------------------------------
def test_update_api(tmp_path, monkeypatch):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    http = FakeHttp()
    state.updater.http = http
    state.updater.can_install = True
    publish(http, "0.8.0")
    client = TestClient(create_app(state))
    with client:
        s = client.get("/api/update").json()
        assert s["current"] and s["enabled"] and s["latest"] is None
        s = client.post("/api/update/check").json()
        assert s["available"] and s["canInstall"]
        assert client.post("/api/update/skip", json={"version": "0.8.0"}).json()["skipped"]
        assert state.config.settings.skipped_update == "0.8.0"
        # Another website in the browser can't start an install.
        r = client.post("/api/update/install", headers={"origin": "https://evil.test"})
        assert r.status_code == 403
        assert client.post("/api/update/retry").status_code == 409
        state.recorder.session_id = 1  # recording
        r = client.post("/api/update/install")
        assert r.status_code == 409 and "recording" in r.json()["detail"]
        state.recorder.session_id = None
        assert client.post("/api/update/install").status_code == 200
        assert state.exit_requested.wait(5)
        client.put("/api/settings", json={"check_updates": False})
        assert client.get("/api/update").json()["enabled"] is False


# ---- release signing script --------------------------------------------------------------
def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "release_sign.py"
    spec = importlib.util.spec_from_file_location("release_sign", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_release_sign_round_trip(tmp_path, monkeypatch):
    rs = _script()
    monkeypatch.setenv(rs.ENV_PASSPHRASE, "correct horse")
    key_file = tmp_path / "keys" / "k.key"
    pub = rs.keygen(key_file)
    assert b"ENCRYPTED PRIVATE KEY" in key_file.read_bytes()
    with pytest.raises(SystemExit):
        rs.keygen(key_file)  # never overwrites
    key = rs.load_key(key_file)
    exe = tmp_path / updater.installer_name("0.8.0")
    exe.write_bytes(INSTALLER)
    with pytest.raises(SystemExit, match="TRUSTED_KEYS"):
        rs.sign(exe, key, "0.8.0", trusted=[])
    with pytest.raises(SystemExit, match="Expected"):
        rs.sign(exe, key, "0.8.1", trusted=[pub])
    manifest, sig = rs.sign(exe, key, "0.8.0", trusted=[pub])
    updater.verify_signature(manifest.read_bytes(), sig.read_text(), [pub])
    m = updater.parse_manifest(manifest.read_bytes())
    assert m.size == len(INSTALLER) and m.sha256 == hashlib.sha256(INSTALLER).hexdigest()
    monkeypatch.setenv(rs.ENV_PASSPHRASE, "wrong one!")
    with pytest.raises(SystemExit, match="passphrase"):
        rs.load_key(key_file)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_signing_key_is_private(tmp_path, monkeypatch):
    rs = _script()
    monkeypatch.setenv(rs.ENV_PASSPHRASE, "correct horse")
    key_file = tmp_path / "k.key"
    rs.keygen(key_file)
    assert key_file.stat().st_mode & 0o077 == 0


def test_installer_script_restarts_the_app_after_an_update():
    """The relaunch entry pairs with the arguments the app passes (bare /RELAUNCH is never
    seen by Inno's {param:}), runs unelevated, and isn't skipped in silent mode."""
    iss = (Path(__file__).resolve().parents[1] / "packaging" / "installer.iss").read_text()
    assert "/RELAUNCH=1" in updater.INSTALLER_ARGS
    assert "ExpandConstant('{param:RELAUNCH|0}') = '1'" in iss
    entry = next(line for line in iss.splitlines() if "Check: ShouldRelaunch" in line)
    flags = entry.split("Flags:")[1].split(";")[0].split()
    assert "runasoriginaluser" in flags and "nowait" in flags and "skipifsilent" not in flags
