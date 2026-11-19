# WvW Analyzer: Windows installer plan

> **Status:** approved 2026-11-18, implemented in v0.2.0. Deviation: `CloseApplications=force` plus a PowerShell stop of processes from the program folder, because the window-less app ignored the polite close on upgrade. This is the plan as approved; it is kept as history and not
> updated. Current behavior and later decisions are in [`../DECISIONS.md`](../DECISIONS.md).

## Context

Sharing the app today means zipping `dist\WvWAnalyzer\` and telling friends to unzip it, install .NET 10 and
ignore warnings. That isn't friendly. The goal is **one `WvWAnalyzer-Setup-<version>.exe`** a friend can run:

- Next → Install → Finish, with Start menu and desktop shortcuts and a normal uninstaller;
- the app then works without installing anything else;
- a short first-run screen guides them to "Start recording".

Decisions (user, 2026-11-18):

- **Inno Setup 6.** Per-user install, no admin. Built on this PC's Windows side; friends never need Inno Setup.
- **Private .NET 10 runtime bundled.** About 30 MB, MIT-licensed, redistributable. Elite Insights runs on it, so
  nothing is installed system-wide, and it works offline. (Checked: the Windows `GW2EI-win-x64` build is also
  framework-dependent, so there is no self-contained Elite Insights to use instead.)
- **Uninstall asks** "Also delete your analyzed fights and settings?", with **No** as the default.
- **First-run setup screen** in the app. This was also an open item from the original plan.

## What the friend experiences

1. Runs `WvWAnalyzer-Setup-0.2.0.exe`. SmartScreen warns, because the installer is unsigned: More info → Run anyway.
2. Wizard: welcome → install folder (default `%LOCALAPPDATA%\Programs\WvW Analyzer`, no admin) → "Create desktop
   shortcut" checkbox → Install → "Launch WvW Analyzer".
3. The app opens on **Welcome / setup**:
   - arcdps log folder: found automatically, or entered by hand;
   - Elite Insights: shows "ready" after a self-test;
   - optional local LLM: Install button, about 2.5 GB, can be skipped;
   - Finish: lands on Fights with a "Start recording" hint.
4. Upgrades: running a newer setup over an old install closes the running app, replaces the program files and keeps
   all data.
5. Uninstall: Windows "Apps & features" → asks whether to delete data (default keep). arcdps logs are never touched.

## Implementation

### 1. Private .NET runtime and Elite Insights launch (backend)

- `backend/wvw_analyzer/tools.py`:
  - add `setup_dotnet()`. It downloads a pinned `dotnet-runtime-10.0.x-win-x64.zip` (latest is 10.0.15) from
    Microsoft's official download host and verifies its **SHA-512** (from Microsoft's `releases.json`, pinned in
    code);
  - extracts to `bin/dotnet/`;
  - also pin a SHA-256 for the Elite Insights and llama.cpp downloads.
- `backend/wvw_analyzer/ingest/ei_runner.py`:
  - when `bin/dotnet/dotnet.exe` exists, run `bin/dotnet/dotnet.exe GuildWars2EliteInsights-CLI.dll …`, with
    `DOTNET_ROOT` set to that folder and `DOTNET_MULTILEVEL_LOOKUP=0`, so the private runtime is always used;
  - otherwise fall back to today's behavior (the system .NET, or WSL interop in dev);
  - add `self_test()`, which runs `dotnet --list-runtimes` and checks that `Microsoft.NETCore.App 10.` is listed.
- `scripts/setup_tools.py`: add `--dotnet` (on by default on Windows builds).

### 2. Robust app start (backend)

- `backend/wvw_analyzer/main.py`:
  - **single instance.** Before starting the server, check whether `/api/status` on the configured port answers as
    WvW Analyzer. If so, open that instance's window or URL and exit;
  - if the port is taken by **another program**, pick the next free port (8765–8785) instead of failing.
  - `__version__` becomes the single version source, bumped to **0.2.0** (also `pyproject.toml`).

### 3. First-run setup (backend + frontend)

- Settings gains `onboarded: bool = False` (config.py).
- `GET /api/selftest` returns `{logDir: {ok, path, wvwLogs}, elite: {ok, version, runtime}, llm: {...}}`. This
  reuses `paths.default_log_dir()`, `iter_logs` from `ingest/recorder.py`, the new `EIRunner.self_test()` and
  `LlmService.status()`.
- New route `frontend/src/routes/welcome/+page.svelte`: three cards (log folder / Elite Insights / optional LLM) and a
  Finish button. Finish saves `onboarded: true` and goes to `/`.
  - The log folder card takes a text input. In the desktop window, a **Browse…** button uses pywebview's folder
    dialog through the `window.pywebview.api.pick_folder` JS bridge (exposed in `main.py`). In a plain browser that
    button is hidden.
- `+layout.svelte`: on start, if `onboarded` is false, redirect to `/welcome`. Settings gets a "Run setup again"
  link.
- The empty state on the Fights page already explains recording and import; keep it.

### 4. Installer script

- New `packaging/installer.iss` (Inno Setup 6):
  - `AppId` (fixed GUID, so upgrades replace in place) and `AppName=WvW Analyzer`; `AppVersion` comes from
    `/DAppVersion=…`;
  - `PrivilegesRequired=lowest`, `DefaultDirName={autopf}\WvW Analyzer` (per-user → `%LOCALAPPDATA%\Programs`),
    `ArchitecturesAllowed=x64compatible`;
  - `CloseApplications=yes`, `RestartApplications=no`, so the Restart Manager closes a running app on upgrade;
  - `[Files]`: the whole `dist\WvWAnalyzer\` folder (exe, `_internal`, `bin\GW2EI`, `bin\dotnet`);
  - `[Icons]`: Start menu entry, an optional desktop icon (task checkbox) and an uninstall entry;
  - `[Run]`: "Launch WvW Analyzer" checkbox on the last page;
  - **WebView2 check** in `[Code]`: if the WebView2 runtime registry key is missing (rare on Windows 10/11), run the
    bundled 2 MB `MicrosoftEdgeWebview2Setup.exe /silent /install`. It works per-user, but needs internet.
  - `[UninstallDelete]` + `[Code] CurUninstallStepChanged`: ask with `MsgBox(..., MB_YESNO or MB_DEFBUTTON2)`; on
    Yes, delete `{localappdata}\WvWAnalyzer` (database, parsed JSON, uploads, the LLM model and runtime, settings).
    The arcdps folder is never referenced.
  - Kill a running `llama-server.exe` / Elite Insights child of the app before upgrade or uninstall
    (`taskkill /IM llama-server.exe /F` only if its path is inside our data folder; via `[Code]` + WMI query).
  - Compression `lzma2/ultra64`, `SolidCompression=yes`; output `dist\WvWAnalyzer-Setup-{version}.exe`.
- An app icon (`packaging/icon.ico`, generated from the existing shield logo) is used for the exe (PyInstaller spec
  `icon=`), the installer and the shortcuts.

### 5. Build pipeline

- `scripts/build_windows.ps1`: `uv sync` → frontend (or `-SkipFrontend`) → `setup_tools.py` (Elite Insights +
  .NET) → PyInstaller → copy `bin\GW2EI` + `bin\dotnet` → **`iscc /DAppVersion=<__version__> packaging\installer.iss`**.
  It fails clearly if `iscc.exe` isn't found and prints the winget command.
- Building happens in a Windows copy of the repo (`%USERPROFILE%\WvWAnalyzer-build`), as last time.
- **Needs your OK when implementing:** installing Inno Setup 6 on your Windows (`winget install JRSoftware.InnoSetup`,
  free, per-user).

### 6. Docs

- README: "Install" section for friends, including the SmartScreen note, and "Build the installer" for you.
- docs/DECISIONS.md: installer decisions.

## Not in scope

- **Code signing.** It needs a paid certificate or a signing service; the SmartScreen warning stays, and the README
  explains it.
- **Auto-update.** Friends run the new setup to upgrade; data is kept.
- The Trends page and the remaining low-severity review items.

## Verification

1. **Unit tests:**
   - `EIRunner` uses the private dotnet when present (command line and environment);
   - the port-fallback and existing-instance logic;
   - `/api/selftest` shape;
   - the `onboarded` redirect flag in settings.
2. **Private runtime really used:** on Windows, run the bundled Elite Insights with `DOTNET_ROOT` pointing at
   `bin\dotnet` and the system .NET excluded (`DOTNET_MULTILEVEL_LOOKUP=0`); parse a real log.
3. **Installer round-trip:**
   - silent install into a test folder: `Setup.exe /VERYSILENT /CURRENTUSER /DIR=<test dir>`;
   - launch the installed exe headless with a throwaway `WVW_DATA_DIR`, then run the existing smoke test: status,
     import one real log, analyzed, top issue.
   - Note: processes started from the Claude app get Windows file virtualization for `%LOCALAPPDATA%`, so the tests
     use explicit test folders.
4. **Upgrade:** install 0.2.0 over a test install with data present → data kept and the app starts.
5. **Uninstall:** silent uninstall → program folder gone, data kept (the default). The "delete data" path is checked
   with a test data folder.
6. **First-run screen:** checked in the browser (fresh data folder → redirected to /welcome → checks shown → Finish →
   Fights).
7. **What I can't verify here:** a truly clean PC without .NET/WebView2, and the real SmartScreen prompt. Best final
   check: run the installer in **Windows Sandbox** (if your Windows edition has it) or on a friend's PC.
