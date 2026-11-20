# WvW Analyzer: requirements and decisions

This records what the app must do and the decisions made while building it. The original
implementation plans are in `docs/plans/`. Where they differ, this file wins.

## Goal

A local Windows desktop app for Guild Wars 2 **WvW zerg fights**. It parses arcdps logs and tells an
organized group *why a fight was lost and what to change*, as short ranked notes with evidence. It
also shows the standard per-player, per-party and per-squad log stats, like other WvW log tools.

## Hard requirements

1. **Static analysis.** Rule-based detectors produce the findings. An LLM is optional and may only
   rephrase findings; it must never be the source of a fact.
2. **Light while gaming.** It runs on the same PC as GW2:
   - Elite Insights parsing runs one log at a time, at below-normal priority.
   - The optional LLM runs on the CPU with 2 threads at idle priority. It starts on demand and
     unloads when idle.
   - The auto-debrief only runs after no new log has arrived for a while.
3. **Recording mode.** Start/Stop recording watches the arcdps log folder. Every new log is picked
   up only once it is completely written (size and mtime stable for 3 s, and readable), then parsed
   and analyzed automatically, with live UI updates. Logs that existed before recording started are
   ignored.
4. **Import of existing logs:**
   - by date range (grouped into one session per day);
   - by picking one or more files;
   - by dropping files or whole folders anywhere in the app.

   Already-imported logs are never duplicated, and importing an already-imported single log opens
   that fight. More than 20 new logs require explicit confirmation, showing count, date span,
   number of sessions and an estimated time (about 4 s per log). Queued imports can be cancelled;
   fights from a recording are never cancelled.
5. **Skip non-WvW logs cheaply.** The arcdps log header holds the encounter species id, and WvW is
   1. Non-WvW logs are rejected without running Elite Insights. WvW logs that are too small (under
   20 s, under 5 enemies, under 5 squad members; configurable) are stored as "skipped".
6. **Stats.** Per player, party and squad, with sortable tables:
   - boon uptime and generation (self / group / off-group / squad), with % and stacks for
     stability and might;
   - offense, including damage to downed enemies and down contribution;
   - support (strips, cleanses, healing, barrier, resurrects);
   - defense;
   - positioning (distance to tag and stack, measured while in the fight);
   - a fight timeline with stab / resist / protection coverage, damage in and out, healing, and
     down/death markers.

   Squad members who weren't near the fight are flagged and excluded from fight analysis.
7. **Sessions.** One recording, or one imported day, is a session. Its summary shows results, kills
   and deaths, recurring problems (ranked by how often they show up in losses), leaderboards and a
   per-account players table.
8. **Settings:**
   - log folder and Elite Insights path;
   - filters;
   - recording options (poll interval, stable time, auto-record with the GW2 process on Windows);
   - every detector's thresholds and on/off switch (stored as overrides of the defaults), plus
     "Save & re-analyze all";
   - LLM options and install.

   Note wording comes from `notes/templates.yaml` and can be overridden in the data folder.
9. **Data handling:**
   - All data lives in one data folder: `./data` in development, `%LOCALAPPDATA%\WvWAnalyzer` in
     the exe.
   - Original arcdps logs are never copied, unless imported from outside the arcdps folder (then
     into `uploads/`), and never deleted.
   - Deleting a fight or session also deletes its parsed Elite Insights JSON and any uploaded copy.
     On startup, parsed files no fight references are removed (only inside the folder next to the
     database).
   - Nothing is sent anywhere, except downloads of the pinned tools and the model.
10. **UI.** Clean, modern, dark web UI in a native window (pywebview / WebView2). It is consistent
    across pages: one page container width for every page and tab. Big tables scroll inside a
    height-bounded card, so the horizontal scrollbar is always visible; the header, first column and
    totals row are sticky.

## Key decisions

| Area | Decision |
|---|---|
| Parser | GW2 Elite Insights CLI (pinned version in `tools.py`) -> compressed JSON; never parse `.zevtc` ourselves |
| Backend | Python 3.12 (uv), FastAPI + one WebSocket, SQLite (WAL), numpy/pandas for per-second series |
| Frontend | SvelteKit 3 / Svelte 5 SPA (static adapter), Tailwind 4, ECharts (modular imports); served by FastAPI |
| Window / packaging | pywebview + PyInstaller onedir; Elite Insights bundled in `bin/`; LLM files downloaded on demand |
| Recording | Polling scanner instead of filesystem events (works the same on Windows, WSL and network folders) |
| Findings | 11 detectors -> `Finding` with severity, impact, time window and evidence. The ranker merges overlapping findings and shows the top 5 plus up to 2 positives. Text is rendered from YAML templates. |
| Detector calibration | Thresholds tuned on about 93 real fights (`scripts/calibrate.py`). Several detectors require real downs before firing, to avoid nonsense notes in skirmishes. |
| Outcome | Result from the deaths trade: win if (enemy deaths + 1) / (squad deaths + 1) >= 1.5, loss if <= 1/1.5, skirmish if under 3 deaths in total |
| LLM | Optional. Qwen3-4B Q4_K_M via llama.cpp `llama-server` (pinned build). Prompt `v8_header` at temperature 0.1. Code writes the result line, the framing ("Clean win...") and a one-line fact and fix per problem; the model only phrases bullets. Chosen with `scripts/llm_bench.py` against reference debriefs written by Claude; earlier prompts that paraphrased more made factual errors. |

## Decisions from the code review (2026-11-18)

- **Analysis worker.** Each fight is analyzed in a short-lived worker process at below-normal
  priority, so the large Elite Insights JSON (up to about 700 MB in memory for long fights) is
  released afterwards. Elite Insights runs single-threaded.
- **Stale analyses.** `ANALYZER_VERSION` is stored with each analysis. On startup, fights from an
  older version are re-analyzed from the cached JSON.
- **Imports.** Date-range import previews first (new / already imported / non-WvW / days) and uses
  the same >20 confirmation. Non-WvW logs never become fights.
- **Detector overrides.** Settings replace the `detectors` overrides as a whole, so a detector can
  be re-enabled or reset to its defaults.
- **Auto-record.** It respects a manual Stop until the game is closed.
- **Auto-debrief.** It only covers the latest recording session (not imported history) and backs
  off after failures.
- **Local-only API:**
  - the Host header must be localhost / 127.0.0.1, which blocks DNS rebinding;
  - state-changing requests and the WebSocket must come from a localhost origin, or send no Origin
    header, which blocks other websites in the browser.

## Known limitations (accepted)

- One log is one player's point of view: enemy data is partial, and enemy boons aren't recorded in
  WvW logs. Strip analysis therefore compares strips out vs boons lost.
- Healing and barrier data only exist for players running the arcdps healing addon.
- arcdps can't see boons applied before the log started, so the first 3 s of boon data are ignored.

## Installer and first run (2026-11-18)

- **Inno Setup 6, per-user** (`PrivilegesRequired=lowest`, `%LOCALAPPDATA%\Programs\WvW Analyzer`).
  A fixed `AppId` makes a newer setup upgrade in place; program files are replaced and user data
  is kept.
- **Private .NET runtime.** The .NET 10 runtime (Microsoft's zip, SHA-512 verified) is bundled in
  `bin\dotnet`. Elite Insights runs as `bin\dotnet\dotnet.exe GuildWars2EliteInsights-CLI.dll`, so
  there is no system .NET dependency and no admin. There is no self-contained Elite Insights build
  to use instead.
- **Closing the app on upgrade or uninstall.** The installer force-closes processes running from
  the program folder (the app, its workers, Elite Insights) and an app-started llama-server.
  Nothing else is touched.
- **Uninstall** asks whether to delete `%LOCALAPPDATA%\WvWAnalyzer`; the default is No.
  Silent uninstall keeps the data.
- **WebView2:** the 2 MB Evergreen bootstrapper is bundled (Authenticode-checked at build time)
  and runs only if WebView2 is missing.
- **Pinned checksums** for every download (Elite Insights, .NET, llama.cpp, models).
- **App start:** a second launch opens the running instance; a port used by another program
  moves the app to the next free port.
- **First-run setup screen** (`/welcome`, shown while `onboarded` is false): log folder (with a
  Browse dialog in the desktop window), parser self-test, optional LLM install. Configs from
  before this screen count as onboarded.

## GvG mode (2026-11-19)

- **Why.** In a GvG, rounds end with an agreed call-off: both sides stop and rez everyone.
  Zerg rules read the downs left at that moment as failed cleaves or allies not picked up.
- **Mode per fight.** `fights.mode` (`zerg` | `gvg`) is stamped from `Settings.fight_mode` when
  a fight is added. Changing the setting doesn't touch existing fights; a fight or session
  override stores the new mode, drops the old debrief and re-analyzes. Fights from before this
  change are `zerg`.
- **Call-off.** A round's last second with any real fighting: damage in or out of at least 1%
  of the fight's peak per second. After a call-off nobody deals damage, so the low-level
  finishing of downs still belongs to the round. Kills within `calloff_grace_s` (3 s) of the
  call-off count.
- **Rounds.** A lull of at least `round_gap_s` (25 s) without fighting splits a log into rounds,
  in GvG mode only: 23 of 142 normal zerg logs have 20 s+ lulls.
- **What isn't counted:**
  - downs still open at the call-off (left by agreement);
  - downs and deaths after it.
  `downstate` judges only the rest. Its GvG text leaves out the resurrect total, because the
  log's resurrect count includes the rezzing after the call-off.
- **Per round:**
  - `early_cascade` and `sustain_decline` run per round and report the worst one ("in N of M
    rounds");
  - `out_of_position` ignores downs after a call-off;
  - `strip_balance` uses fighting time without the regroups.
- **Result.** Per round, players taken out (counted deaths plus downs left) with the same 1.5x
  rule as zerg fights, but without "skirmish". The fight result is the round tally. Sessions also
  count GvG round wins and losses.
- **LLM.** The code-written header says "GvG round win" / "GvG win 2-1 over 3 rounds" and lists
  what was left at the call-off. The skirmish framing isn't used. The model's input is the
  already-corrected facts, so the prompt itself is unchanged.
- **Validation.**
  - With the 142 corpus logs analyzed as zerg fights, the results match the previous version
    except one fight. Elite Insights had split one down into two intervals, so it was counted
    twice; continued intervals are now merged.
  - The same logs analyzed as GvG: 89 one-round logs and 4 two-round logs; 6 enemy and 1 own
    down left at a call-off.
  - The corpus has **no real GvG logs**: thresholds still need checking on real ones.

## Strength and problem drill-down (2026-11-20)

- **Why.** The session Summary listed strengths ("Won the strip war") and recurring problems
  with only a fight count. There was no way to tell which fights earned them or which stat
  drove them.
- **Session aggregate.** Each strength and recurring problem lists its `occurrences`: fight id,
  time, map, result, the real finding key (GvG variants included) and the template's one-line
  `short` fact. They are ordered by impact, then by time. The facts come from code; no LLM is
  involved.
- **Deep links.** The fight page reads `?tab=`, `?finding=<key>`, `?stat=<column>`, `?sort=asc`
  and `?from=session`:
  - a finding link opens the debrief, expands "more" if needed, highlights and scrolls to the
    card, and sets the timeline highlight when the finding has a window;
  - tab changes update the URL with `replaceState`;
  - `from=session` makes the back link return to the session.
- **Focus stat.** Each detector declares `focus`: finding key -> `{tab, column, sort?}`, the
  stat that best shows its evidence (strips, cleanses, stability uptime lowest first, ...). The
  fight API adds it when it serves the notes, so stored analyses don't change and old fights
  get the link without a re-analysis. Comp, outnumbered and player-outlier notes have no single
  column and get none. "See stats" opens that tab, sorts by the column and tints it.
- **No version bump.** Analysis output is unchanged, so `ANALYZER_VERSION` stays 3.
- **Validation.**
  - The 143 corpus logs analyzed before and after give byte-identical summaries and notes.
  - A test checks that every focus names an existing template and a column on the stated tab.
  - Checked in the running app: Won the strip war -> fight -> strips table, sorted by the top
    strippers named in the note.

## In-game overlay (2026-11-20)

- **Why.** Reading the debrief meant alt-tabbing out of the game. The overlay shows it in game.
- **Nexus only.** The overlay is a Raidcore Nexus addon (API v6). Nexus already loads arcdps
  and gives addons an ImGui context, render callbacks, Quick Access icons, keybinds and
  MumbleLink. A plain arcdps extension was left out: arcdps now builds with ImGui 1.92, while
  Nexus (and the `arcdps-imgui` bindings) use 1.80, so it would be a second UI integration.
- **Rust with nexus-rs** (Zerthox, pinned git rev), cross-compiled from WSL with cargo-xwin and
  clang-cl/lld-link. No Windows toolchain is needed. The C runtime is linked statically (no VC++
  redistributable). `model`, `client` and `settings` are platform-independent and tested on
  Linux; only the Nexus glue (`addon.rs`, `ui.rs`) is Windows-only.
- **Crash safety.** The addon runs inside the game process. nexus-rs doesn't catch panics in
  callbacks, and its `panic` features show a message box over the game, so they are off. Every
  callback runs under `catch_unwind`: a panic is logged and the overlay stops drawing until it's
  reloaded. (The plan said `panic = "abort"`; that would have closed the game instead.)
- **Dumb renderer.** `GET /api/overlay` sends finished, code-written strings: the fight
  (title, `result_line` and `framing_line` from `llm/prompts.py`, ranked notes with `short` and
  `fix_short`, positives, the stored LLM debrief if any, previous and next fight ids) and the
  session (record, kills and deaths, top 5 recurring problems, top 3 strengths, `latestId`). The
  addon only lays them out, so wording or analysis changes need no addon update. `schema` is 1;
  the addon refuses a newer schema with "Update the in-game addon". `addon/tests/fixtures/
  overlay.json` is the contract: the Python test checks that the payload still has its shape
  and the Rust tests parse it.
- **Polling.** A background thread polls every 2 s with `If-None-Match` (an unchanged payload is
  a 304) and searches ports 8765–8785 every 5 s when the app isn't found. It recognizes the app
  by `"app": "wvw-analyzer"` in `/api/status`. The render thread never does I/O.
- **Local-only API unchanged.** A native client sends Host `127.0.0.1` and no Origin, which the
  existing middleware already allows, including the recording POSTs.
- **Auto-show.** When `latestId` changes, the window opens once MumbleLink says the player is
  out of combat (on by default). "Hide in combat" is on by default.
- **ToS.** ArenaNet approves no add-ons, arcdps and Nexus included. The overlay keeps to what
  that setup already does: it only draws a window through Nexus; it reads no game memory and
  installs no hooks of its own; it sends no input, chat or game actions; its content comes from
  finished log files via the app; the only game state it reads is MumbleLink's in-combat flag;
  it connects only to 127.0.0.1. There is no clipboard or chat output, so posting a debrief
  stays a manual player action.
- **Install from the app.** `addon_install.py` finds the GW2 folder (a Settings override, the
  running `Gw2-64.exe`, then Program Files) and requires `addons/Nexus/`. It copies the bundled
  `bin/addon/WvWAnalyzer.dll` to `addons/WvWAnalyzer.dll.part` and renames it into place, so
  Nexus never sees half a file. It never touches anything but that DLL and the addon's
  `addons/WvWAnalyzer/` settings folder, and it never installs Nexus or arcdps. A locked DLL
  (game running) gives "Close the game". `addons/` is writable without admin once Nexus is
  installed.
- **The app is the only updater.** The addon declares `UpdateProvider::None`. "Up to date"
  means the installed DLL's SHA-256 matches the bundled one. On Windows the app updates an
  installed addon at startup when the game isn't running, so the app and addon versions can't
  drift.
- **Validation.**
  - Python: payload, browsing, ETag 304, empty database, native-client recording calls allowed
    and foreign origins refused; installer against a fake GW2 folder (Nexus present/absent,
    install, idempotent update, uninstall leaves other files, locked DLL, auto-update rules).
  - Rust: fixture parsing, unknown and missing fields, newer schema, settings round trip, and
    the client against a fake analyzer (discovery, ETag, action errors, quick stop).
  - On the dev data: `/api/overlay` gives the real result line, session record and browsing
    ids; a 304 takes about 8 ms; the GW2 folder and Nexus are detected from WSL.
  - Analysis code is untouched, so `ANALYZER_VERSION` stays 3. Corpus tests pass.
  - In game (2026-11-21, user check): Nexus loads the addon and the window shows the debrief
    from the running analyzer.
  - With the game running, the installer can't replace the loaded DLL and shows the "Close
    the game" message; nothing is left behind.
  - The Quick Access icon follows the game's menu-bar style (a flat khaki silhouette) after
    the first, colored one stood out. Nexus shows icons that aren't hovered at about 43%
    brightness, so the texture is a light near-white that shows as khaki, like the other
    addons' icons. `scripts/draw_addon_icon.py` draws it.
  - Packaged 0.5.0 build: the frozen app bundles the DLL, reports it installed and up to
    date, and serves `/api/overlay`.

## Open items at the time of writing

- No "Trends across sessions" page (original plan, phase 6).
- The installer and exe are not code-signed (SmartScreen warning). Signing needs a paid
  certificate or signing service.
