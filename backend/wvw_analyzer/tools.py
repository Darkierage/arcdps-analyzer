"""Download pinned external tools: Elite Insights CLI, .NET runtime, llama-server, LLM model,
replay map images.

Every download is pinned to a version and verified against a checksum. .NET and the models use
the publisher's own checksums (Microsoft's releases.json, Hugging Face LFS metadata); Elite
Insights and llama.cpp don't publish checksums, so theirs were recorded when the version was
pinned.
"""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

EI_VERSION = "v3.33.0.0"
EI_URL = (
    "https://github.com/baaron4/GW2-Elite-Insights-Parser/releases/download/"
    f"{EI_VERSION}/GW2EICLI.zip"
)
EI_SHA256 = "b4314827b9eee6d81ad89913da6a0c9d46b5f52364f1de11589398ace958c07b"

# Private .NET runtime for Elite Insights (bundled with the Windows app; nothing installed
# system-wide). Hash: Microsoft's release metadata for 10.0.15.
DOTNET_VERSION = "10.0.15"
DOTNET_URL = (f"https://builds.dotnet.microsoft.com/dotnet/Runtime/{DOTNET_VERSION}/"
              f"dotnet-runtime-{DOTNET_VERSION}-win-x64.zip")
DOTNET_SHA512 = ("06f0bedd59ae4ac722ada805a6d6bbf605bcdc790c71f59b7003878072902b5cde5dec8c40c0baa8"
                 "1192660d4748e9d79afdbdcb0c0ea9d6b821d0a044c4c6dd")

LLAMA_BUILD = "b12100"
LLAMA_ASSET = {
    "win32": f"llama-{LLAMA_BUILD}-bin-win-cpu-x64.zip",
    "linux": f"llama-{LLAMA_BUILD}-bin-ubuntu-x64.tar.gz",
}
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{build}/{asset}"
LLAMA_SHA256 = {
    "win32": "2578e983b1405b6368e374b64926212229f436c40e19fcffa383e81bab73efd8",
    "linux": "2612b96a683840bf16e3e98a82b0bcc741edde1266870c02002815606714cb13",
}

MODELS = {
    "Qwen3-4B-Q4_K_M.gguf": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
    "Qwen3-1.7B-Q8_0.gguf": "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q8_0.gguf",
}

# Hugging Face LFS sha256 of each model file.
MODEL_SHA256 = {
    "Qwen3-4B-Q4_K_M.gguf": "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
    "Qwen3-1.7B-Q8_0.gguf": "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a",
}

# Combat replay map images: the ones Elite Insights uses for its own replay (its JSON names the
# URL per fight, and positions are already in that image's pixel space). Downloaded on demand,
# not shipped: they are derived from ArenaNet's maps. Hashes recorded when they were pinned.
MAP_IMAGES = {
    "ebg": ("https://i.imgur.com/t0khtQd.png",
            "7199f287973afcb08dd93094e914ad76aab6ec44dd0ee30b45d1185c17516119"),
    "alpine": ("https://i.imgur.com/nVu2ivF.png",
               "70e599be70994818fd7e0a80397d75398dece5929095edd2aec695b94db79a62"),
    "desert": ("https://i.imgur.com/R5p9fqw.png",
               "cb97d610ff5a881509c09c672cc7d61c850ed8c682be5280b58de4c538d612d1"),
    "eotm": ("https://i.imgur.com/iEpKYL0.jpg",
             "08b34f14fb65bdd1114576b5014693b5a491f31e730faf59ecbdb69a0fac4667"),
}

Progress = Callable[[int, int], None]  # (downloaded bytes, total bytes)


class ChecksumError(RuntimeError):
    pass
UA = {"User-Agent": "wvw-analyzer-setup"}


def _download(url: str, dest: Path | None = None, progress: Progress | None = None,
              sha256: str | None = None, sha512: str | None = None) -> bytes:
    """Download to memory (dest None) or stream to a file, verifying the checksum."""
    digest = hashlib.sha512() if sha512 else hashlib.sha256()
    expected = (sha512 or sha256 or "").lower()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        if dest is None:
            buf = io.BytesIO()
            sink = buf
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            sink = open(dest.with_suffix(dest.suffix + ".part"), "wb")  # noqa: SIM115
        try:
            while chunk := resp.read(1 << 20):
                sink.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        finally:
            if dest is not None:
                sink.close()
        if expected and digest.hexdigest() != expected:
            if dest is not None:
                dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
            raise ChecksumError(f"Checksum mismatch for {url} - download corrupted or tampered")
        if dest is not None:
            dest.with_suffix(dest.suffix + ".part").replace(dest)
            return b""
        return buf.getvalue()


def _check_member(dest: Path, name: str) -> None:
    target = (dest / name).resolve()
    if not target.is_relative_to(dest.resolve()):
        raise RuntimeError(f"Refusing to extract outside target dir: {name}")


def _extract(data: bytes, asset: str, dest: Path) -> None:
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for m in zf.namelist():
                _check_member(dest, m)
            zf.extractall(dest)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for m in tf.getmembers():
                _check_member(dest, m.name)
            tf.extractall(dest, filter="data")


def _mark_exec(root: Path, patterns: tuple[str, ...]) -> None:
    for pat in patterns:
        for f in root.rglob(pat):
            f.chmod(f.stat().st_mode | 0o111)


# ---- Elite Insights --------------------------------------------------------------------------
def ei_dir() -> Path:
    return paths.bin_dir() / "GW2EI"


def setup_ei(force: bool = False) -> Path:
    d = ei_dir()
    version_file = d / ".version"
    if not force and version_file.exists() and version_file.read_text().strip() == EI_VERSION:
        return d
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    log.info("downloading %s", EI_URL)
    _extract(_download(EI_URL, sha256=EI_SHA256), "ei.zip", d)
    if not (d / "GuildWars2EliteInsights-CLI.exe").exists():
        raise RuntimeError("GuildWars2EliteInsights-CLI.exe not found in the downloaded archive")
    _mark_exec(d, ("*.exe",))  # needed to launch the Windows exe from WSL
    version_file.write_text(EI_VERSION)
    return d


# ---- private .NET runtime ----------------------------------------------------------------------
def dotnet_dir() -> Path:
    return paths.bin_dir() / "dotnet"


def dotnet_exe() -> Path | None:
    exe = dotnet_dir() / "dotnet.exe"
    return exe if exe.exists() else None


def setup_dotnet(force: bool = False) -> Path:
    """Unpack the pinned Windows .NET runtime into bin/dotnet (used only by Elite Insights)."""
    d = dotnet_dir()
    version_file = d / ".version"
    if not force and version_file.exists() and version_file.read_text().strip() == DOTNET_VERSION:
        return d
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    log.info("downloading %s", DOTNET_URL)
    _extract(_download(DOTNET_URL, sha512=DOTNET_SHA512), "dotnet.zip", d)
    if not (d / "dotnet.exe").exists():
        raise RuntimeError("dotnet.exe not found in the downloaded runtime")
    _mark_exec(d, ("*.exe",))
    version_file.write_text(DOTNET_VERSION)
    return d


# ---- llama.cpp -------------------------------------------------------------------------------
def llama_dir() -> Path:
    # Installed on demand from the app, so it must live somewhere writable when packaged.
    base = paths.data_dir() / "bin" if paths.FROZEN else paths.bin_dir()
    return base / "llama"


def llama_server_path() -> Path | None:
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    return next(iter(llama_dir().rglob(name)), None) if llama_dir().exists() else None


def setup_llama(force: bool = False) -> Path:
    d = llama_dir()
    version_file = d / ".version"
    existing = llama_server_path()
    if not force and existing and version_file.exists() and \
            version_file.read_text().strip() == LLAMA_BUILD:
        return existing
    plat = "win32" if sys.platform == "win32" else "linux"
    asset = LLAMA_ASSET[plat]
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    url = LLAMA_URL.format(build=LLAMA_BUILD, asset=asset)
    log.info("downloading %s", url)
    _extract(_download(url, sha256=LLAMA_SHA256[plat]), asset, d)
    _mark_exec(d, ("llama-*",))
    version_file.write_text(LLAMA_BUILD)
    server = llama_server_path()
    if not server:
        raise RuntimeError("llama-server not found in the downloaded archive")
    return server


def model_path(name: str) -> Path:
    return paths.models_dir() / name


def download_model(name: str, progress: Progress | None = None) -> Path:
    if name not in MODELS:
        raise ValueError(f"Unknown model {name}; choose one of {', '.join(MODELS)}")
    dest = model_path(name)
    if dest.exists():
        return dest
    log.info("downloading model %s", name)
    _download(MODELS[name], dest, progress, sha256=MODEL_SHA256.get(name))
    return dest


# ---- combat replay map images -----------------------------------------------------------------
def maps_dir() -> Path:
    return paths.data_dir() / "maps"


def map_key_for_url(url: str | None) -> str | None:
    """The pinned map image Elite Insights' JSON points at, if it is one of ours."""
    return next((k for k, (u, _) in MAP_IMAGES.items() if u == url), None)


def map_image_path(key: str, root: Path | None = None) -> Path | None:
    """The downloaded image for a map key, or None if it isn't downloaded (or unknown)."""
    if key not in MAP_IMAGES:
        return None
    url = MAP_IMAGES[key][0]
    p = (root or maps_dir()) / f"{key}{Path(url).suffix}"
    return p if p.is_file() else None


def map_images_installed(root: Path | None = None) -> bool:
    return all(map_image_path(k, root) for k in MAP_IMAGES)


def download_map_images(root: Path | None = None) -> list[str]:
    """Fetch the replay map images that are missing; returns the keys downloaded."""
    d = root or maps_dir()
    got = []
    for key, (url, sha) in MAP_IMAGES.items():
        if map_image_path(key, d):
            continue
        log.info("downloading replay map %s", url)
        _download(url, d / f"{key}{Path(url).suffix}", sha256=sha)
        got.append(key)
    return got
