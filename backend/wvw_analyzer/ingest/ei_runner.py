"""Run the Elite Insights CLI on a single log and return the generated JSON path."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from .. import paths, tools

log = logging.getLogger(__name__)

BASE_CONF = Path(__file__).with_name("ei_wvw.conf")


class EIError(RuntimeError):
    pass


def _to_windows(p: Path) -> str:
    return subprocess.check_output(["wslpath", "-w", str(p)], text=True).strip()


def _from_windows(p: str) -> Path:
    return Path(subprocess.check_output(["wslpath", "-u", p], text=True).strip())


class EIRunner:
    def __init__(self, exe: Path, out_dir: Path | None = None, timeout_s: float = 600,
                 dotnet: Path | None | bool = True):
        self.exe = exe
        self.out_dir = out_dir or (paths.data_dir() / "ei")
        self.timeout_s = timeout_s
        # Private .NET runtime shipped with the app (bin/dotnet); False disables it.
        self.dotnet = tools.dotnet_exe() if dotnet is True else (dotnet or None)
        self.via_wsl = paths.is_wsl() and (
            exe.suffix.lower() == ".exe" or (self.dotnet is not None))

    def available(self) -> bool:
        return self.exe.exists()

    def _arg(self, p: Path) -> str:
        return _to_windows(p) if self.via_wsl else str(p)

    def _conf(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        conf = self.out_dir / "ei_run.conf"
        text = BASE_CONF.read_text(encoding="utf-8")
        text += f"\nOutLocation={self._arg(self.out_dir.resolve())}\n"
        if not conf.exists() or conf.read_text(encoding="utf-8") != text:
            conf.write_text(text, encoding="utf-8")
        return conf

    def _dll(self) -> Path:
        return self.exe.with_suffix(".dll")

    def _base_cmd(self) -> list[str]:
        """How to start Elite Insights: via the private runtime if bundled, else the exe."""
        if self.dotnet and self._dll().exists():
            # The dotnet muxer only uses the runtime next to it, never a system-wide .NET.
            return [str(self.dotnet), self._arg(self._dll())]
        if self.exe.suffix.lower() == ".dll":
            return ["dotnet", str(self.exe)]
        return [str(self.exe)]

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.dotnet:
            env["DOTNET_ROOT"] = str(self.dotnet.parent)
            env["DOTNET_MULTILEVEL_LOOKUP"] = "0"
            env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
        return env

    def self_test(self) -> dict[str, object]:
        """Can Elite Insights run here? Checks the files and the .NET runtime it will use."""
        out: dict[str, object] = {"ok": False, "version": tools.EI_VERSION, "runtime": None,
                                  "private": bool(self.dotnet), "error": None}
        if not self.available():
            out["error"] = "Elite Insights is not installed"
            return out
        cmd = [str(self.dotnet), "--list-runtimes"] if self.dotnet else ["dotnet",
                                                                          "--list-runtimes"]
        kwargs: dict = {"env": self._env()}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kwargs)
        except (OSError, subprocess.TimeoutExpired) as e:
            out["error"] = f".NET runtime not available ({e})"
            return out
        runtimes = [ln.split()[1] for ln in res.stdout.splitlines()
                    if ln.startswith("Microsoft.NETCore.App ")]
        ok = [v for v in runtimes if v.startswith("10.")]
        out["runtime"] = ok[-1] if ok else (runtimes[-1] if runtimes else None)
        out["ok"] = bool(ok)
        if not ok:
            out["error"] = ".NET 10 runtime not found"
        return out

    def parse(self, log_file: Path) -> Path:
        if not self.available():
            raise EIError(f"Elite Insights not found at {self.exe}. Run scripts/setup_tools.py.")
        cmd = self._base_cmd() + ["-c", self._arg(self._conf()), self._arg(log_file)]
        kwargs: dict = {"env": self._env()}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
            )
        log.info("EI parse %s", log_file.name)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_s, **kwargs,
            )
        except subprocess.TimeoutExpired as e:
            raise EIError(f"Elite Insights timed out after {self.timeout_s:.0f}s") from e
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        result = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Processed - "):
                try:
                    result = json.loads(line[len("Processed - "):])
                except json.JSONDecodeError:
                    continue
        if not result:
            tail = " | ".join(out.strip().splitlines()[-3:])
            raise EIError(f"Elite Insights produced no result (exit {proc.returncode}): {tail}")
        if not result.get("parsed"):
            raise EIError(f"Elite Insights could not parse the log: {result.get('status')}")
        files = [f for f in result.get("generatedFiles") or [] if f.endswith((".json", ".gz"))]
        if not files:
            raise EIError("Elite Insights did not generate JSON output")
        path = _from_windows(files[0]) if self.via_wsl else Path(files[0])
        if not path.exists():
            raise EIError(f"Generated JSON missing: {path}")
        return path
