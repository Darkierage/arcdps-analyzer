"""Update check, signed download and install (plan 17).

The app asks GitHub for the latest release, verifies the release's signed manifest
(`latest.json` + `latest.json.sig`, Ed25519, keys below) and, on the user's click, downloads the
installer, checks it against the manifest and runs it after the app has closed.

What is sent: HTTPS GETs to GitHub (the release, the two manifest files, the installer on
click) with a generic User-Agent. Nothing about the user or their fights.

Security: the installer is not code-signed and a file downloaded by Python carries no
Mark-of-the-Web, so these checks are the only gate before it runs. GitHub's own digest only
proves the download matches what was uploaded; the signature proves *who* made the release.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__, paths

log = logging.getLogger(__name__)

REPO = "Darkierage/arcdps-analyzer"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
UA = {"User-Agent": f"wvw-analyzer/{__version__}", "Accept": "application/vnd.github+json"}

# Ed25519 public keys (raw 32 bytes, base64) whose signature on latest.json is trusted. A list,
# so a new key can be shipped in a release signed by the old one. Empty: no release can be
# installed from the app (it only links to the release page). `scripts/release_sign.py keygen`
# prints the line to put here.
TRUSTED_KEYS: list[str] = [
    "/HDjOsI8PJFw2MFEoMmyct7aSDOwGFZLvCjZ1trV/X4=",  # release key, created 2026-11-26 for 0.8.0
]

# Testing only: point the app at a local server and trust a test key. The test key is honoured
# only together with the API override, so the production key never signs a test release.
ENV_API = "WVW_UPDATE_API"
ENV_TEST_KEY = "WVW_UPDATE_TEST_KEY"

FIRST_CHECK_DELAY_S = 30
CHECK_INTERVAL_S = 24 * 3600
NOTES_MAX = 4000
MAX_RELEASE_JSON = 2 * 1024 * 1024
MAX_MANIFEST = 16 * 1024
MAX_SIG = 1024
MAX_INSTALLER = 500 * 1024 * 1024
STATE_FILE = "update.json"
UPDATES_DIR = "updates"
MANIFEST_NAME = "latest.json"
SIG_NAME = "latest.json.sig"
INSTALLER_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"]

# What a failed request can raise: urllib's errors are OSErrors, but a malformed reply (a proxy
# or a hotel login page) raises http.client errors that are not.
NETWORK_ERRORS = (OSError, ValueError, http.client.HTTPException)

_VERSION_RE = re.compile(r"^v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_version(s: object) -> tuple[int, int, int] | None:
    m = _VERSION_RE.match(s.strip()) if isinstance(s, str) else None
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(version: object, current: object) -> bool:
    v, cur = parse_version(version), parse_version(current)
    return bool(v and cur and v > cur)


def installer_name(version: str) -> str:
    return f"WvWAnalyzer-Setup-{version}.exe"


def api_url() -> str:
    return os.environ.get(ENV_API) or API_URL


def trusted_keys() -> list[str]:
    keys = list(TRUSTED_KEYS)
    test_key = os.environ.get(ENV_TEST_KEY)
    if test_key and os.environ.get(ENV_API):
        keys.append(test_key)
    return keys


class VerifyError(ValueError):
    """The release or the downloaded file failed a check; never install it."""


def verify_signature(manifest: bytes, sig_b64: str, keys: list[str]) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        sig = base64.b64decode(sig_b64.strip(), validate=True)
    except ValueError as e:
        raise VerifyError("signature is not valid base64") from e
    if len(sig) != 64:
        raise VerifyError("signature has the wrong length")
    for key in keys:
        try:
            raw = base64.b64decode(key, validate=True)
            Ed25519PublicKey.from_public_bytes(raw).verify(sig, manifest)
            return
        except (ValueError, InvalidSignature):
            continue
    raise VerifyError("signature does not match a trusted key")


@dataclass
class Manifest:
    version: str
    installer: str
    size: int
    sha256: str


def parse_manifest(data: bytes) -> Manifest:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError) as e:
        raise VerifyError("manifest is not valid JSON") from e
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise VerifyError("unknown manifest format")
    version, installer = raw.get("version"), raw.get("installer")
    size, sha = raw.get("size"), raw.get("sha256")
    if parse_version(version) is None or version.startswith("v"):
        raise VerifyError("manifest version is invalid")
    if installer != installer_name(version):
        raise VerifyError("manifest names an unexpected installer file")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_INSTALLER:
        raise VerifyError("manifest size is invalid")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        raise VerifyError("manifest sha256 is invalid")
    return Manifest(version, installer, size, sha)


def build_manifest(version: str, installer: Path, published: str) -> bytes:
    """The manifest `scripts/release_sign.py` signs (the exact bytes are what is signed)."""
    data = {"schema": 1, "version": version, "installer": installer.name,
            "size": installer.stat().st_size, "sha256": sha256_file(installer),
            "published": published}
    parse_manifest(json.dumps(data).encode())  # the app must accept what is published
    return (json.dumps(data, indent=1) + "\n").encode("utf-8")


@dataclass
class Release:
    version: str  # "0.8.0"
    tag: str
    notes: str
    url: str  # the release page
    published: str | None
    verified: bool = False
    verify_error: str | None = None
    # Set when verified: the installer asset and the signed manifest (kept to re-verify at
    # download time; update.json could have been edited).
    installer_url: str | None = None
    manifest: str | None = None  # exact bytes, UTF-8
    signature: str | None = None
    digest: str | None = None  # GitHub's "sha256:..." of the installer asset, if given
    size: int | None = None  # installer bytes (signed manifest)


def _https_ok(url: str) -> bool:
    scheme = urlparse(url).scheme
    return scheme == "https" or (scheme == "http" and bool(os.environ.get(ENV_API)))


class Http:
    """The network side, swapped for a fake in tests."""

    def get(self, url: str, max_bytes: int) -> bytes:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise OSError(f"response from {url} is too large")
        return data

    def download(self, url: str, dest: Path, max_bytes: int,
                 progress: Callable[[int, int], None]) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(1 << 20):
                done += len(chunk)
                if done > max_bytes:
                    raise OSError("download is larger than expected")
                f.write(chunk)
                progress(done, total)


def fetch_release(http: Http, current: str = __version__) -> Release | None:
    """The latest release, verified if it carries a valid signed manifest. None: the latest
    release's tag isn't a version this app understands."""
    raw = json.loads(http.get(api_url(), MAX_RELEASE_JSON))
    if not isinstance(raw, dict):
        raise ValueError("unexpected release data")
    tag = raw.get("tag_name")
    if parse_version(tag) is None:
        log.info("update check: latest release tag %r is not a version", tag)
        return None
    version = tag.removeprefix("v")
    notes = raw.get("body") if isinstance(raw.get("body"), str) else ""
    rel = Release(version=version, tag=tag, notes=notes[:NOTES_MAX],
                  url=str(raw.get("html_url") or RELEASES_URL),
                  published=raw.get("published_at") if isinstance(raw.get("published_at"), str)
                  else None)
    if not is_newer(version, current):
        return rel  # nothing to install: the manifest files aren't fetched
    try:
        _verify_release(http, rel, raw.get("assets"))
        rel.verified = True
    except VerifyError as e:
        rel.verify_error = str(e)
        log.warning("update %s cannot be verified: %s", version, e)
    except NETWORK_ERRORS as e:  # the manifest files could not be downloaded
        rel.verify_error = f"could not read the release manifest ({e})"
        log.info("update %s: %s", version, rel.verify_error)
    return rel


def _verify_release(http: Http, rel: Release, assets: object) -> None:
    by_name = {a.get("name"): a for a in assets or [] if isinstance(a, dict)} \
        if isinstance(assets, list) else {}
    if MANIFEST_NAME not in by_name or SIG_NAME not in by_name:
        raise VerifyError("the release has no signed manifest")
    keys = trusted_keys()
    if not keys:
        raise VerifyError("this build has no update signing key")
    urls = [by_name[n].get("browser_download_url") for n in (MANIFEST_NAME, SIG_NAME)]
    if not all(isinstance(u, str) and _https_ok(u) for u in urls):
        raise VerifyError("manifest download address is not HTTPS")
    manifest_bytes = http.get(urls[0], MAX_MANIFEST)
    sig = http.get(urls[1], MAX_SIG).decode("ascii", "replace")
    verify_signature(manifest_bytes, sig, keys)
    m = parse_manifest(manifest_bytes)
    if m.version != rel.version:
        raise VerifyError(f"manifest is for {m.version}, the release is {rel.version}")
    asset = by_name.get(m.installer)
    if asset is None:
        raise VerifyError("the release has no installer named in the manifest")
    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not _https_ok(url):
        raise VerifyError("installer download address is not HTTPS")
    if asset.get("size") != m.size:
        raise VerifyError("installer size differs from the manifest")
    digest = asset.get("digest")
    if isinstance(digest, str) and digest and digest.lower() != f"sha256:{m.sha256}":
        raise VerifyError("GitHub's checksum differs from the manifest")
    rel.installer_url = url
    rel.manifest = manifest_bytes.decode("utf-8")
    rel.signature = sig.strip()
    rel.digest = digest if isinstance(digest, str) else None
    rel.size = m.size


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PendingInstall:
    path: Path
    sha256: str
    silent: bool = True  # False: the retry after an unfinished update runs the normal wizard


@dataclass
class _Download:
    state: str = "idle"  # idle | downloading | ready | failed
    done: int = 0
    total: int = 0
    error: str | None = None


@dataclass
class _Saved:
    """update.json: what survives a restart."""

    last_check: float | None = None
    release: dict[str, Any] | None = None
    # The update started from the app (version, installer file, sha256); cleared once the
    # running version reaches it.
    attempt: dict[str, Any] | None = None


class Updater:
    def __init__(self, data_dir: Path, enabled: Callable[[], bool],
                 skipped: Callable[[], str | None], busy: Callable[[], str | None],
                 publish: Callable[[dict[str, Any]], None], request_exit: Callable[[], None],
                 http: Http | None = None, current: str = __version__,
                 can_install: bool | None = None):
        self.data_dir = data_dir
        self._enabled = enabled
        self._skipped = skipped
        self._busy = busy
        self._publish = publish
        self._request_exit = request_exit
        self.http = http or Http()
        self.current = current
        # Only the installed Windows app replaces itself; from source it only reports.
        self.can_install = (paths.FROZEN and sys.platform == "win32") if can_install is None \
            else can_install
        self._lock = threading.Lock()
        self._checking = False
        self._error: str | None = None
        self._download = _Download()
        self._pending: PendingInstall | None = None
        self._stop = threading.Event()
        self._last_attempt: float | None = None
        self._saved = self._load()
        self.release: Release | None = self._cached_release()

    # ---- persistence -------------------------------------------------------------------
    @property
    def updates_dir(self) -> Path:
        return self.data_dir / UPDATES_DIR

    def _load(self) -> _Saved:
        try:
            raw = json.loads((self.data_dir / STATE_FILE).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return _Saved(raw.get("lastCheck"), raw.get("release"), raw.get("attempt"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("could not read %s; starting fresh", STATE_FILE, exc_info=True)
        return _Saved()

    def _save(self) -> None:
        data = {"lastCheck": self._saved.last_check, "release": self._saved.release,
                "attempt": self._saved.attempt}
        path = self.data_dir / STATE_FILE
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            log.warning("could not write %s", path, exc_info=True)

    def _cached_release(self) -> Release | None:
        raw = self._saved.release
        if not isinstance(raw, dict):
            return None
        try:
            rel = Release(**raw)
        except TypeError:
            return None
        return rel if parse_version(rel.version) else None

    # ---- lifecycle ---------------------------------------------------------------------
    def start(self) -> None:
        self.cleanup()
        threading.Thread(target=self._loop, name="update-check", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(FIRST_CHECK_DELAY_S):
            return
        while True:
            due = self._last_attempt is None or \
                time.time() - self._last_attempt >= CHECK_INTERVAL_S
            if due and self._enabled():
                try:
                    self.check()
                except Exception:  # never let one bad check end the daily checks
                    log.exception("update check failed")
            if self._stop.wait(60):
                return

    def cleanup(self) -> None:
        """Forget a finished update and delete old installers. The installer of an update that
        did not finish is kept for the retry; a file still in use (the installer that just
        restarted the app runs from here) is left for the next start."""
        attempt = self.unfinished()
        if self._saved.attempt and attempt is None:
            log.info("update to %s finished", self._saved.attempt.get("version"))
            self._saved.attempt = None
            self._save()
        keep = attempt.get("installer") if attempt else None
        if not self.updates_dir.is_dir():
            return
        for f in self.updates_dir.iterdir():
            if f.name == keep or not f.is_file():
                continue
            try:
                f.unlink()
            except OSError:
                log.debug("left %s (in use)", f.name)

    # ---- check -------------------------------------------------------------------------
    def check(self) -> dict[str, Any]:
        with self._lock:
            if self._checking:
                return self.status()
            self._checking = True
        self._last_attempt = time.time()
        self._emit()
        try:
            rel = fetch_release(self.http, self.current)
            with self._lock:
                self._error = None
                self.release = rel
                self._saved.last_check = time.time()
                self._saved.release = asdict(rel) if rel else None
            self._save()
            if rel and self._newer(rel.version):
                log.info("update available: %s (verified: %s)", rel.version, rel.verified)
        except NETWORK_ERRORS as e:
            log.info("update check failed: %s", e)
            with self._lock:
                self._error = "Could not reach GitHub" if not isinstance(e, ValueError) \
                    else str(e)
        finally:
            with self._lock:
                self._checking = False
        self._emit()
        return self.status()

    def _newer(self, version: object) -> bool:
        return is_newer(version, self.current)

    # ---- status ------------------------------------------------------------------------
    def unfinished(self) -> dict[str, Any] | None:
        """The update started from the app that the running version hasn't reached."""
        a = self._saved.attempt
        if not isinstance(a, dict) or not self._newer(str(a.get("version"))):
            return None
        name = a.get("installer")
        if not isinstance(name, str) or name != installer_name(str(a.get("version"))):
            return None
        if not (self.updates_dir / name).is_file():
            return None
        return a

    def blocked_reason(self) -> str | None:
        rel = self.release
        if rel is None or not self._newer(rel.version):
            return "No update available"
        if not rel.verified:
            return "This release can't be verified; download it from the release page"
        if not self.can_install:
            return "Updates install only in the installed Windows app"
        if self._download.state == "downloading" or self._pending:
            return "The update is already being installed"
        return self._busy()

    def status(self) -> dict[str, Any]:
        rel = self.release
        available = bool(rel and self._newer(rel.version))
        reason = self.blocked_reason() if available else None
        unfinished = self.unfinished()
        d = self._download
        return {
            "current": self.current,
            "enabled": self._enabled(),
            "checking": self._checking,
            "lastCheck": self._saved.last_check,
            "error": self._error,
            "latest": None if rel is None else {
                "version": rel.version, "notes": rel.notes, "url": rel.url,
                "publishedAt": rel.published, "verified": rel.verified,
                "verifyError": rel.verify_error, "size": rel.size},
            "available": available,
            "skipped": bool(available and rel and self._skipped() == rel.version),
            "canInstall": available and reason is None,
            "blockedReason": reason,
            "download": None if d.state == "idle" else asdict(d),
            "unfinished": None if unfinished is None else {
                "version": unfinished["version"], "canRetry": self.can_install},
            "releasesUrl": RELEASES_URL,
        }

    def _emit(self) -> None:
        try:
            self._publish({"type": "update", "update": self.status()})
        except Exception:
            log.debug("update event not sent", exc_info=True)

    # ---- install -----------------------------------------------------------------------
    def install(self) -> dict[str, Any]:
        """Start downloading the release found by the app's own last check; once verified,
        the app closes and the installer runs. Raises ValueError when not allowed now."""
        with self._lock:
            reason = self.blocked_reason()
            if reason:
                raise ValueError(reason)
            rel = self.release
            self._download = _Download(state="downloading")
        threading.Thread(target=self._download_and_exit, args=(rel,), name="update-download",
                         daemon=True).start()
        self._emit()
        return self.status()

    def _download_and_exit(self, rel: Release) -> None:
        try:
            path, sha = self._download_verified(rel)
        except Exception as e:  # any failure must end in "failed", not a download that never ends
            log.warning("update download failed: %s", e,
                        exc_info=not isinstance(e, NETWORK_ERRORS))
            with self._lock:
                self._download = _Download(state="failed", error=str(e))
            self._emit()
            return
        reason = self._busy()
        if reason:  # recording started or logs arrived during the download
            with self._lock:
                self._download = _Download(state="failed", error=f"{reason}, then try again")
            self._emit()
            return
        self._saved.attempt = {"version": rel.version, "installer": path.name, "sha256": sha}
        self._save()
        with self._lock:
            self._download.state = "ready"
            self._pending = PendingInstall(path, sha)
        self._emit()
        log.info("update %s downloaded and verified; closing the app to install it",
                 rel.version)
        self._request_exit()

    def _download_verified(self, rel: Release) -> tuple[Path, str]:
        if not (rel.verified and rel.manifest and rel.signature and rel.installer_url):
            raise VerifyError("the release is not verified")
        manifest_bytes = rel.manifest.encode("utf-8")
        verify_signature(manifest_bytes, rel.signature, trusted_keys())
        m = parse_manifest(manifest_bytes)
        if m.version != rel.version or not self._newer(m.version):
            raise VerifyError("the manifest is not for a newer version")
        if not _https_ok(rel.installer_url):
            raise VerifyError("installer download address is not HTTPS")
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        final = self.updates_dir / m.installer
        part = final.with_name(final.name + ".part")
        last = [0.0]

        def progress(done: int, total: int) -> None:
            self._download.done, self._download.total = done, total or m.size
            now = time.monotonic()
            if now - last[0] >= 0.25:
                last[0] = now
                self._emit()

        try:
            self.http.download(rel.installer_url, part, m.size, progress)
            size = part.stat().st_size
            if size != m.size:
                raise VerifyError(f"download is {size} bytes, the manifest says {m.size}")
            sha = sha256_file(part)
            if sha != m.sha256:
                raise VerifyError("downloaded file does not match the signed checksum")
            if rel.digest and rel.digest.lower() != f"sha256:{sha}":
                raise VerifyError("downloaded file does not match GitHub's checksum")
            os.replace(part, final)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        return final, sha

    def retry_unfinished(self) -> dict[str, Any]:
        """Run the kept installer of an unfinished update again, with its normal wizard."""
        a = self.unfinished()
        if a is None:
            raise ValueError("No unfinished update")
        if not self.can_install:
            raise ValueError("Updates install only in the installed Windows app")
        if reason := self._busy():
            raise ValueError(reason)
        path = self.updates_dir / a["installer"]
        sha = str(a.get("sha256") or "")
        if not _SHA256_RE.match(sha) or sha256_file(path) != sha:
            raise ValueError("The kept installer is damaged; download it from the release page")
        with self._lock:
            self._pending = PendingInstall(path, sha, silent=False)
        self._emit()
        self._request_exit()
        return self.status()

    def take_pending(self) -> PendingInstall | None:
        with self._lock:
            pending, self._pending = self._pending, None
        return pending


def launch_installer(pending: PendingInstall,
                     popen: Callable[..., Any] = subprocess.Popen) -> bool:
    """Run the installer after the app has shut down cleanly. Re-hashes the file first (it sat
    in the data folder between the check and now)."""
    try:
        if sha256_file(pending.path) != pending.sha256:
            log.error("update installer changed after it was verified; not running it")
            return False
    except OSError:
        log.exception("update installer is gone")
        return False
    # The installer and the app it restarts must not inherit this frozen app's bootloader
    # state (PyInstaller: a process that outlives the app needs a reset environment).
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for key in [k for k in os.environ if k.startswith(("_PYI", "_MEIPASS"))]:
        del os.environ[key]
    args = [str(pending.path), *(INSTALLER_ARGS if pending.silent else [])]
    flags = 0
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        popen(args, cwd=str(pending.path.parent), creationflags=flags, close_fds=True)
    except OSError as e:
        if getattr(e, "winerror", None) != 740 or sys.platform != "win32":
            log.exception("could not start the update installer")
            return False
        # Elevation required: ShellExecute shows the UAC prompt.
        try:
            os.startfile(str(pending.path), arguments=" ".join(args[1:]),
                         cwd=str(pending.path.parent))
        except OSError:
            log.exception("could not start the update installer")
            return False
    log.info("update installer started: %s", pending.path.name)
    return True
