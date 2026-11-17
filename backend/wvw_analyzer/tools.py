"""Download pinned external tools: Elite Insights CLI, llama-server and the LLM model."""

from __future__ import annotations

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

LLAMA_BUILD = "b12100"
LLAMA_ASSET = {
    "win32": f"llama-{LLAMA_BUILD}-bin-win-cpu-x64.zip",
    "linux": f"llama-{LLAMA_BUILD}-bin-ubuntu-x64.tar.gz",
}
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{build}/{asset}"

MODELS = {
    "Qwen3-4B-Q4_K_M.gguf": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
    "Qwen3-1.7B-Q8_0.gguf": "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q8_0.gguf",
}

Progress = Callable[[int, int], None]  # (downloaded bytes, total bytes)
UA = {"User-Agent": "wvw-analyzer-setup"}


def _download(url: str, dest: Path | None = None, progress: Progress | None = None) -> bytes:
    """Download to memory (dest None) or stream to a file."""
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
                done += len(chunk)
                if progress:
                    progress(done, total)
        finally:
            if dest is not None:
                sink.close()
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
    _extract(_download(EI_URL), "ei.zip", d)
    if not (d / "GuildWars2EliteInsights-CLI.exe").exists():
        raise RuntimeError("GuildWars2EliteInsights-CLI.exe not found in the downloaded archive")
    _mark_exec(d, ("*.exe",))  # needed to launch the Windows exe from WSL
    version_file.write_text(EI_VERSION)
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
    _extract(_download(url), asset, d)
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
    _download(MODELS[name], dest, progress)
    return dest
