# WvW Analyzer: in-game overlay (Nexus addon) plan

> **Status:** approved 2026-11-20, released in 0.5.0 (2026-11-21) after an in-game check.
> Deviations:
> - The Phase 0 spike only covered the build (the DLL exports `GetAddonDef`, and Nexus and
>   `arcdps-imgui` both use ImGui 1.80). Loading it in game moved to the final check.
> - Panics are caught per callback instead of `panic = "abort"`, which would close the game.
>   nexus-rs's panic features are off because they show a message box.
> - The installer lives in `backend/wvw_analyzer/addon_install.py` (not `overlay/installer.py`).
> - The session block also carries `latestId`, for auto-show while browsing older fights.
> - `addon/Cargo.toml` became the fourth place to bump the version.
>
> This is the plan as approved; it is kept as history. Current behavior and later decisions are
> in [`../DECISIONS.md`](../DECISIONS.md).

## Context

The analyzer's debrief lives in a separate window, so reading it means alt-tabbing out of the
game. The goal is a small in-game window that shows the analyzer's results. The analyzer app
installs it, and it works with the user's setup (Raidcore Nexus loading arcdps).

**Feasibility: yes.** What was checked on this machine:
- Nexus loads through `Guild Wars 2\d3d11.dll`. arcdps runs as a Nexus addon (`addons\ArcDPS.dll`).
  Nexus-native addons (API v6) sit next to arcdps-only extensions (Boon Table, Healing Stats)
  in `addons\`.
- `addons\` is writable without admin (Everyone: full control, set when Nexus was installed),
  so the app can copy a DLL there.
- A similar addon already exists: "WvW Fight Analysis" is a Nexus addon that opens its own ImGui
  windows. Our addon will use a distinct name ("WvW Analyzer") to avoid confusion.
- Nexus API v6 (`Nexus.h`) has what the addon needs: `GUI_Register(RT_Render | RT_OptionsRender)`,
  `QuickAccess_Add`, `InputBinds_RegisterWithString`, `Textures_LoadFromMemory`, the ImGui
  context and allocator, the addon directory, and MumbleLink data.

**Decisions made with the user:** Nexus only (arcdps-only support may come later). Rust with
`nexus-rs`, cross-compiled from WSL. v1 features: view the latest debrief, start/stop recording,
session summary. No clipboard button and no chat output.

## ToS position (recorded in DECISIONS.md)

ArenaNet's third-party policy approves no add-ons: they are used at your own risk and ArenaNet
acts at its discretion. arcdps and Nexus are tolerated in practice. The overlay must add no new
kind of risk on top of the arcdps and Nexus the user already runs. Hard rules:
- **Display only.** It draws an ImGui window through Nexus's own render callback. It has no
  hooks of its own and does no memory reading or writing.
- **No input or automation.** It sends no keystrokes, chat messages or game actions. It reads
  Nexus keybinds only to toggle its own window.
- **Post-fight data only.** All content comes from the analyzer over `127.0.0.1`, and the
  analyzer works from finished arcdps log files, like Elite Insights or dps.report. The only game
  state the addon reads is MumbleLink's "in combat" flag, used to hold back auto-show. MumbleLink
  is ArenaNet's official interface, exposed by Nexus.
- **No network beyond localhost.** It does no telemetry and no self-update (see Updates below).

## Architecture

```
analyzer (FastAPI :8765..8785)  --GET /api/overlay (ETag, ~2 s poll)-->  Nexus addon (Rust)
                                <--POST /api/recording/start|stop-------  (no Origin header)
```

- **Dumb renderer.** The backend sends finished, code-written strings. The addon only lays them
  out, so analysis or wording changes never need an addon update. The payload carries a `schema`
  number. If it's newer than the addon understands, the addon says "Update the in-game addon
  from WvW Analyzer > Settings".
- **Local-only API stays as is.** A native client sends Host `127.0.0.1` and no Origin, which
  the existing `local_only` middleware (`api/app.py`) already allows for GET and POST. No
  security change.
- **No analysis change.** The analysis output is unchanged, so `ANALYZER_VERSION` stays and the
  zerg path is untouched. The dev_corpus snapshot is still compared before and after as a guard.

## Phases

### Phase 0: spike (go/no-go, needs you in game once)
Build a minimal addon in `addon/` with `nexus::export!` and a window that shows `GET /api/status`.
Check these before building more:
1. **Toolchain.** In WSL: `rustup`, the `x86_64-pc-windows-msvc` target, and `cargo-xwin`
   (which downloads the MSVC CRT and Windows SDK; you accept Microsoft's license). Nothing is
   installed on Windows.
2. **Loading.** Nexus loads the DLL and `Nexus.log` shows "Loaded addon". The ImGui window
   renders, which confirms that the `arcdps-imgui` crate matches Nexus's ImGui context.
3. **Networking.** An HTTP call from a background thread to the analyzer works and never blocks
   rendering.
4. **Hot reload.** What Nexus does when the DLL file is replaced while the game runs (the Nexus
   log shows it watching the folder). This decides the installer's "game is running" behavior.

If step 2 fails (ImGui mismatch), stop and report. The fallback is C++ against the official
`Nexus.h`.

### Phase 1: backend overlay endpoint
- New `backend/wvw_analyzer/api/overlay.py`, mounted from `create_app`, with
  `GET /api/overlay?fight=<id>`. Without `fight`, it returns the latest analyzed fight of the
  current or most recent session.
- Payload (schema 1), all strings built in Python:
  - `app`: version, recording (active, session name), queue (pending, current fight);
  - `fight`: id, header line (time · map · duration · squad vs enemy), result and result line,
    kills and deaths, ranked notes `[{severity, title, short}]`, positives, LLM debrief bullets
    (if written), `prevId` and `nextId` within the session;
  - `session`: name, W/L/skirmish record, kills and deaths, top recurring problems with counts.
- Reuse what exists: `state.db.fight` and `state.db.analysis` for notes, `_split_debrief`
  (`api/app.py`, moved to a shared helper) for the debrief, `aggregate_session`
  (`metrics/aggregate.py`) for the session block, and the code-written result line already used
  by the debrief pipeline (`llm/prompts.py`). No new wording logic.
- ETag: hash of the payload. `If-None-Match` returns 304, so 2 s polling is close to free.
- `GET /api/status` gains `"app": "wvw-analyzer"` so the addon can recognize the right
  process when it probes ports 8765–8785 (the same range `main.choose_port` uses).

### Phase 2: the Rust addon (`addon/`)
- `Cargo.toml`: a `cdylib` named `WvWAnalyzer`, with `nexus` (Zerthox/nexus-rs, pinned rev),
  `serde`/`serde_json`, and `ureq` (no TLS, localhost only). Release profile has
  `panic = "abort"`, wrapped in nexus-rs's panic handler, so a bug logs instead of unwinding
  into the game.
- Modules:
  - `model.rs`: serde types for schema 1. Platform-independent, unit tested on Linux.
  - `client.rs`: background thread. It discovers the port, polls with ETag (2 s when connected,
    10 s backoff when not), and shares the latest snapshot through `Arc<Mutex<..>>`. The render
    thread never does I/O.
  - `ui.rs`: the window, with a **Fight** tab (header, result, notes with severity color,
    positives, debrief bullets, ◀ ▶ fight browsing) and a **Session** tab (record, K/D,
    recurring problems). The status line shows whether the analyzer is connected, recording
    state with a Start/Stop button, and queue progress. It falls back to "WvW Analyzer is not
    running" if there's no connection.
  - `lib.rs`: export, load and unload. Registers RT_Render, RT_OptionsRender, a Quick Access
    icon (embedded PNG via `Textures_LoadFromMemory`) and the keybind `ALT+SHIFT+W` (rebindable
    in Nexus).
  - `settings.rs`: options in `addons\WvWAnalyzer\settings.json`: auto-show after a new fight
    (default on, only when MumbleLink says out of combat), hide in combat, background opacity.
- Identity: `Signature` is a fixed random negative int (not on the Raidcore library),
  `Provider = UP_None`, flags `AF_None` (hot-reload safe: unload joins the poll thread).

### Phase 3: install from the app
- New `backend/wvw_analyzer/overlay/installer.py`:
  - `find_gw2_dir()`: checks, in order, a Settings override, the running `Gw2-64.exe` path
    (the auto-record process check in `ingest/recorder.py` already finds the process), then
    `%ProgramFiles%\Guild Wars 2`.
  - `status()`: is GW2 found, is Nexus present (`addons\Nexus\` and a root loader DLL), and is
    our DLL missing, installed or different. "Different" is a SHA-256 comparison with the
    bundled DLL.
  - `install()`: copies to a temp file, then `os.replace` onto `addons\WvWAnalyzer.dll`. The
    Phase 0 result decides what happens while the game runs: either rely on Nexus hot reload,
    or refuse with "Close Guild Wars 2 first".
  - `uninstall()`: removes only our DLL and our `addons\WvWAnalyzer\` folder. It never touches
    other files.
  - If Nexus is missing, it explains that Nexus is required and links raidcore.gg. It never
    installs Nexus or arcdps.
- API: `GET /api/overlay-addon`, `POST /api/overlay-addon/install`, `POST .../uninstall`.
- `Settings.gw2_dir: str | None` override in `config.py`.
- Settings page (`frontend/src/routes/settings`): an **In-game overlay** card with status, the
  GW2 folder, Install, Update and Remove buttons, and a one-line note that it is display-only,
  needs Nexus, and that third-party add-ons are at your own risk. Types go in
  `frontend/src/lib/api.ts`.
- **Updates.** The analyzer is the only updater, so the addon and the app's schema never drift.
  After an app upgrade, Settings shows "Update available". On startup, if the addon is installed
  and the game isn't running, the app updates it silently.

### Phase 4: build and packaging
- `scripts/build_addon.sh` (WSL): `cargo xwin build --release --target x86_64-pc-windows-msvc`,
  then copies to `bin/addon/WvWAnalyzer.dll` (`bin/` is not committed).
- `paths.py`: path to the bundled DLL, for both dev and the frozen exe.
- `scripts/build_windows.ps1`: copies `bin\addon` into `dist\WvWAnalyzer\bin\`, or fails with
  a hint to run `build_addon.sh` in WSL first (the same pattern as the frontend). The Inno
  installer picks it up with `bin\`.
- Version 0.5.0 in the three usual places. The addon's Cargo version matches.

### Phase 5: docs
- `docs/plans/05-ingame-overlay.md` (this plan, with its status line).
- A `docs/DECISIONS.md` section: Nexus-only, Rust/nexus-rs, the localhost dumb-renderer
  protocol, the ToS rules above, the app as the only updater, and the Phase 0 findings.
- `README.md`: an "In-game overlay" section covering requirements (Nexus), install and remove
  from Settings, keybind and Quick Access, what it does and doesn't do, and the at-your-own-risk
  note. Build steps for the addon go in the building section.
- `CLAUDE.md`: the addon build command and the `addon/` folder.

## Tests and verification
- **Python:**
  - `tests/test_overlay_api.py`: payload from `tests/factory.py` fights, the latest-fight and
    browsing logic, 304 on a matching ETag, an empty database, POST to recording with no Origin
    allowed and a foreign Origin refused.
  - `tests/test_overlay_installer.py`: a fake GW2 folder in a temp dir. Covers Nexus
    present/absent, install, idempotence, a hash change leading to update, uninstall removing
    only our files, and a locked or unwritable target giving a clear error.
- **Contract:** the Python test writes the schema-1 payload to `addon/tests/fixtures/` and the
  Rust `cargo test` (native Linux) parses it. A schema change can't silently break the addon.
- **Commands:** `uv run pytest`, `uv run ruff check backend tests scripts`,
  `cd frontend && npm run check && npm run build`, `cd addon && cargo test && cargo clippy`.
- **Zerg path:** dev_corpus analysis snapshot is identical before and after.
- **In game (you, once per phase 0 and at the end):**
  - `Nexus.log` shows the addon loaded;
  - the Quick Access icon and keybind toggle the window;
  - a fight finishes, the window auto-shows out of combat and shows the same notes as the app;
  - Start/Stop recording works;
  - closing the analyzer shows "not running" without stutter;
  - Remove in Settings unloads it cleanly.

## Risks
- **ImGui mismatch between `arcdps-imgui` and Nexus.** Caught in Phase 0; the fallback is C++.
- **Nexus API changes.** Mitigated by pinning the nexus-rs rev, and the `APIVersion` check is
  done by Nexus.
- **Policy.** No official approval exists for any add-on. The rules above keep the overlay in
  the same category as the arcdps/Nexus setup already in use, and README states the risk plainly.
