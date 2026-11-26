# PyInstaller spec for the Windows desktop build (run via scripts/build_windows.ps1).
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
PKG = ROOT / "backend" / "wvw_analyzer"

datas = [
    (str(ROOT / "frontend" / "build"), "frontend"),
    (str(PKG / "notes" / "templates.yaml"), "wvw_analyzer/notes"),
    (str(PKG / "ingest" / "ei_wvw.conf"), "wvw_analyzer/ingest"),
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "backend")],
    datas=datas,
    hiddenimports=collect_submodules("wvw_analyzer") + collect_submodules("uvicorn")
    # The OBS connection imports its client inside a function.
    + collect_submodules("websockets")
    + ["webview.platforms.edgechromium"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WvWAnalyzer",
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="WvWAnalyzer")  # noqa: F821
