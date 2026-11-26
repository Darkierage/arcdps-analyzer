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
   - Nothing is sent anywhere, except downloads of the pinned tools, the model and the replay map
     images, and the update check against GitHub releases.
   - Linked videos are only read: never copied, moved, changed or deleted. Unlinking removes the
     link only.
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
  session (record, kills and deaths, top 5 recurring problems, top 3 strengths), and `latest`
  (below). The
  addon only lays them out, so wording or analysis changes need no addon update. `schema` is 1;
  the addon refuses a newer schema with "Update the in-game addon". `addon/tests/fixtures/
  overlay.json` is the contract: the Python test checks that the payload still has its shape
  and the Rust tests parse it.
- **Polling.** A background thread polls every 2 s with `If-None-Match` (an unchanged payload is
  a 304) and searches ports 8765–8785 every 5 s when the app isn't found. It recognizes the app
  by `"app": "wvw-analyzer"` in `/api/status`. The render thread never does network I/O.
- **Unloading never stalls the game.** Unloading joins the poll thread on the game's thread. On
  Windows a closed localhost port takes about 2 s to refuse, so a search pass over 21 ports
  takes seconds; the thread checks for Stop between ports, and every request is capped at 2 s
  (200 ms to connect). An HTTP error from the app shows as an error in the window, not as
  "isn't running".
- **Local-only API unchanged.** A native client sends Host `127.0.0.1` and no Origin, which the
  existing middleware already allows, including the recording POSTs.
- **Following the current session.** `latest` is the current session's newest fight (the
  recording session, else the one with the most recent fight), sent even while the player
  browses a fight of an older session. The addon shows **Latest** whenever the fight on screen
  isn't that one, and picking it with **>** goes back to following. (In 0.5.0 the addon only
  knew the browsed fight's session, so it could get stuck there after a new session started.)
- **Auto-show** (replaced in 0.7.0 by the *After a fight* setting, see "In-game overlay
  redesign"; the new-fight rule below is unchanged). The window opens, once MumbleLink says the
  player is out of combat, when
  `latest.addedAt` (when the app picked up the log) moves past everything the addon has seen.
  The first payload only sets the baseline, so fights already there at game start don't open
  it, but the first fight of an empty session does. Deleting fights or a re-analysis doesn't
  count (fight ids can be reused after a delete; `addedAt` keeps moving forward). On by
  default, as is "Hide in combat". Options are saved once a slider is let go.
- **ToS.** ArenaNet approves no add-ons, arcdps and Nexus included. The overlay keeps to what
  that setup already does: it only draws a window through Nexus; it reads no game memory and
  installs no hooks of its own; it sends no input, chat or game actions; its content comes from
  finished log files via the app; the only game state it reads is MumbleLink's in-combat flag;
  it connects only to 127.0.0.1. There is no clipboard or chat output, so posting a debrief
  stays a manual player action.
- **Install from the app.** `addon_install.py` finds the GW2 folder (a Settings override, the
  running `Gw2-64.exe`, then the standalone and Steam default folders under Program Files) and
  requires `addons/Nexus/`. Install and Remove both use the folder typed in Settings. It copies the bundled
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
  - Review after 0.5.0 (a code review and a use-case review against these docs) found the
    stall on unload, the stuck session, no auto-show for a session's first fight, auto-show
    on deletes, error shown as "isn't running", a stale action error, option saves on every
    slider frame, Steam folders not found, and Remove ignoring a typed folder. All fixed, with
    tests for the cross-session `latest`, the new-fight rule, a stop during a slow port search
    and the typed-folder Remove.

## Whole-app review fixes (2026-11-21)

After 0.5.0 every area was reviewed against this file and in code (plan:
[`plans/06-review-fixes.md`](plans/06-review-fixes.md)). The local-only API passed every Host,
Origin and WebSocket attack tried. High and medium findings were fixed:

- **Downs near the tag count.** A down is "another fight" only if it is over 5000 from both the
  stack center and the tag. The stack center is the median of everyone alive, which includes
  players back at a waypoint; in the corpus 37 downs within 2500 of the tag were dropped, in one
  wipe 9 of 25. A down kept only for the tag is judged by its tag distance alone (its stack
  distance is unknown), so `out_of_position` doesn't flag it for a center that was elsewhere.
- **Squad totals are the fight's.** `squadDowns` and `squadDeaths` count only players in the
  fight, matching the timeline the detectors use (36 of 142 corpus fights disagreed before).
- **Healing is judged only where it was recorded.** It is recorded only for players running the
  arcdps healing addon. `comp_audit` flags "no healing" only for a party with such a player, and
  `player_outliers` compares healing only among them.
- **GvG lulls.** A down or death between one round's call-off and the next round's first second
  (1 s lead) belongs to no round, like events after the last round. Session totals and per-fight
  kills/deaths leave out events after a call-off, as the fight page and LLM header do.
- **`ANALYZER_VERSION` 4.** Corpus before/after (142 logs, zerg and GvG mode): 56 of 93 analyzed
  fights changed, squad downs/deaths fell by 1–3 in about 30 fights, one result went from even
  to win, and a handful of notes were added or dropped. No GvG-only change: no corpus fight has
  an event in a lull, so that fix is covered by a unit test.
- **Debriefs follow the analysis.** A re-analysis keeps the stored LLM debrief only if the new
  notes and summary are identical; otherwise it is dropped (its wording came from the old ones).
  The summary's `analyzerVersion` doesn't count (since 0.7.0): a version bump alone keeps it.
- **Stopping recording finishes the last log.** The scan thread keeps checking logs that are
  still being written for `stable_s` + 10 s, adds them to the stopped session, then ends it.
  Stop returns at once. Each recording has its own stop flag and session id, so a new recording
  can start while the old one finishes. Typical case: auto-stop as the game closes while arcdps
  writes the raid's last log.
- **One instance.** A second launch checks each busy port from the preferred one up to the
  first free port for a running WvW Analyzer (probing free ports is slow on Windows, so it stops
  there) and shows that one instead of starting another on the same database.
- **Config safety.** `config.yaml` is written to a temp file and renamed. On load, invalid values
  fall back to their defaults one by one; an unreadable file is kept as
  `config.yaml.broken-<time>` and the app starts with defaults and the setup screen.
- **Settings validation.** Ranges on recording, filter, GvG (call-off grace shorter than the
  round gap) and LLM numbers; `host` must be loopback and the API can't change host or port.
  Detector overrides must be known keys with numbers of the default's type, never negative, and
  counts that default to 1 or more stay at least 1. In the UI a cleared threshold means
  "default" (it was saved as 0, which made a detector fire on nearly every fight).
- **Imports run one at a time**, so parallel uploads can't create the same day's session twice.
- **llama-server stops when the window closes**, before the server's shutdown, and can't be
  started again afterwards. A debrief still running would otherwise hold up the shutdown and the
  process would exit without stopping it.
- **Open (low) findings:** recurring-problem severity is taken from its first fight; a skipped
  fight keeps its old result on the session card; a player can be listed twice in
  `player_outliers`; `boon_wipe` never fires on the corpus; some notes render empty lists ("…
  strips: ."); the unverified-numbers check skips numbers of 10 or less; missing sessions or
  fights return 200 instead of 404; `.zevtc.zip` passes the UI's drop filter but not the API;
  README says non-WvW logs are kept as skipped (imports drop them) and omits the 5-squad
  minimum; the welcome page says the LLM never runs during fights, which nothing enforces.

## Boons over time per party (2026-11-21)

Tester feedback: the fight timeline's "Stability per party" checkbox only showed stability; they
wanted to pick one party and see all its boons (plan:
[`plans/07-party-boon-timeline.md`](plans/07-party-boon-timeline.md)).

- **Data.** The timeline also samples every boon in `BOONS` except Stealth per player, and sends
  per squad and per party, each second: the share of **up** players with the boon (whole
  percents, `null` when nobody in the party is up, the same rule as the existing stability
  coverage) and for Stability and Might the average stacks of up players (0.1). Names go as
  ordered `[id, name]` pairs. `ANALYZER_VERSION` 5; notes and summaries on the corpus are
  unchanged. Size on the largest corpus fight (752 s, 8 parties): stats 640 kB → 966 kB raw,
  115 kB → 151 kB stored (zlib).
- **Boons tab.** A "Boons over time" chart above the table: Squad / Party N chips (professions
  in the chip's tooltip), one line per boon, might and stability stacks dashed on a right axis,
  that party's downs and deaths below, GvG call-off shading. Stability, Aegis, Protection,
  Resistance, Quickness, Alacrity and Might stacks start on; legend choices survive switching
  party.
- **Debrief timeline.** The checkbox became a "Show" select: Squad (as before), Party N (its
  stability, resistance, protection, avg boons, damage and downs/deaths) or All parties:
  stability (the old checkbox view), with an "All boons →" link to the Boons tab. The party is
  kept in the URL (`?party=2`).
- **A way back.** **All boons →** adds a browser history entry, so Back returns to the Debrief
  timeline; the Boons chart has **← Fight timeline**, which goes back through that entry
  (keeping the party picked there) and scrolls to the timeline. Other tab switches still replace
  the entry, as before.
- **URLs come from the address bar.** SvelteKit's `pushState`/`replaceState` (shallow routing)
  don't update `page.url`, so building the next URL from it dropped `?tab=` or `?party=` and
  Back/Forward showed a different tab than the address bar. The page builds URLs from
  `location.href` and follows Back/Forward with a `popstate` listener (a `?finding=` link always
  shows the Debrief). A `?party=` the fight doesn't have falls back to the squad.
- **Review** (use-case review in a real browser and a code review): the backend math matched the
  existing stability/resistance/protection/aegis coverage within 1 point on all corpus fights.
  Fixed: the URL handling above, the duplicate history entry from **← Fight timeline**, GvG
  call-off shading tied to the Stability line (hidden with it), GvG downs left at a call-off
  drawn as normal downs (now hollow, as on the fight timeline), the tooltip mixing percents and
  stacks in one sort, and the chip tooltip counting players who weren't in the fight. Kept:
  parties with nobody in the fight get no chip; the Debrief chart's legend choices reset when
  the party changes (as before).
- **Validated** with synthetic fights (coverage with a downed member, `null` with nobody up,
  might stacks, every boon present per party, display order), the corpus snapshot, and the
  dev app: fight 3 per party on both tabs.

## Who went down: marker tooltips (2026-11-21)

Tester feedback: the down and death markers under the charts show when, not who (plan:
[`plans/08-marker-tooltips.md`](plans/08-marker-tooltips.md)).

- **One tooltip, with the events added.** ECharts can't mix an axis tooltip with per-marker
  tooltips, so both charts keep their axis tooltip and add the squad (or selected party's)
  downs and deaths within ±8 px of the pointer, converted to seconds at the current zoom:
  name in its profession color, profession, party, time; for a down also got up / died,
  stability stacks just before, distance to the tag and "left at call-off" (GvG). The fight
  timeline also counts enemy downs/deaths there (enemies are anonymous). Up to 8 lines, then
  "+N more"; names are HTML-escaped. Shared code: `frontend/src/lib/timelineEvents.ts`.
- **Pointer time.** The time comes from the mouse position (`trackPointer`), not the tooltip's
  params: over the marker lane ECharts passes the nearest marker's data, which showed the wrong
  player (a 0:09 down while pointing at 0:30) in the first browser check. The pixel is kept and
  converted when the tooltip is drawn, so a mouse-wheel zoom or resize (which redraws the
  tooltip without a mouse move) can't use a stale time.
- **What's listed.** Only marker kinds that are shown: a kind switched off in the legend (downs,
  downs left at a call-off, deaths, enemy downs/deaths) isn't listed either. With more than 8
  events in the window, the 8 closest to the pointer are kept (so the hovered marker is always
  there), shown in time order, plus "+N more nearby". A GvG down left at a call-off that didn't
  end in a death says "left at call-off", not "got up" (it may never have ended).
- **No analysis change.** Deaths carry no profession, so it is looked up from the fight's
  players on the page; no backend change, no `ANALYZER_VERSION` bump.
- **Validated** in the dev app: fight 2 and 3, squad and Party 2/4 on both charts, several
  events in the same second, hovering away from markers (no events section), mouse-wheel zoom
  without moving, a legend kind switched off and on. A use-case review drove a headless browser
  over synthetic and corpus fights: every marker of a 52-marker fight named its player on both
  charts, 0 mismatches between pointer and tooltip in pixel scans (zoomed and not), GvG
  call-offs, an 11-death second, a 20-minute fight, and names with HTML characters rendered as
  text. A code review confirmed the pointer handler runs before the tooltip is drawn.

## Crash and error reporting (2026-11-21)

Friends run the installed app on their own PCs, and failures there left little or no trace
(plan: [`plans/09-crash-reporting.md`](plans/09-crash-reporting.md)).

- **Local only, sent by hand.** No crash-upload service: that would break the
  "no network beyond what's needed" stance and ship other people's data. Errors go to the log
  and small files in the data folder; the user copies a report and sends it themselves.
- **Uncaught errors.** `diagnostics.install` sets `sys.excepthook` and `threading.excepthook`:
  the traceback goes to the log at CRITICAL (the packaged app has no console, so a dying
  background thread used to print to nowhere) and a crash record is added. Asyncio and
  endpoint errors already reached the log through the root logger.
- **Unexpected exits.** `running-<pid>.json` exists while that app process runs (not for a
  second launch that only shows the running app). Still there at the next start, with that
  process gone, means it died. It is reported only if the PC wasn't shut down or restarted
  since, so shutting Windows down with the app open isn't a "crash" (details in the review
  fixes below).
- **Native crash dumps.** Analysis workers enable `faulthandler` into `crash.log`; when one
  dies, the processor adds a line naming the fight and the fight's error says "The analysis
  process crashed (often: not enough free memory)" instead of `BrokenProcessPool`. The main
  process uses faulthandler only off Windows: pywebview runs .NET there (pythonnet), and
  faulthandler sees Windows exceptions before anything handles them. .NET raises and handles
  some routinely (access violations for null references, for example), and each would be
  dumped as a "Windows fatal exception", so the file would fill with false alarms. (CPython
  already skips the CLR's own exception code, 0xE0434352.) On Windows, real crashes and hangs of our processes come
  from the Windows event log instead (Application Error 1000, Application Hang 1002,
  .NET Runtime 1026; `wevtutil`, last 30 days).
- **Frontend errors.** `window.onerror` and `unhandledrejection` post to
  `/api/client-error`, which logs them (message ≤2000 and stack ≤8000 characters, at most 50 per
  run; the page also deduplicates and skips the ResizeObserver warning).
- **What the user sees.** Crash records (`crashes.json`, last 20) that weren't dismissed show
  as a banner above every page with **Copy diagnostics**. Settings > Troubleshooting has
  **Copy diagnostics**, **Open app folder** and the folder path. The report is plain text
  meant for a chat message: version, OS, Python, the window's user agent, setup checks (log
  folder, Elite Insights self-test, Guild Wars 2/Nexus/overlay, LLM), fight counts by status,
  the 10 latest failed fights with their errors, crash records, Windows event-log entries,
  the end of `crash.log` when it holds a dump, and the end of this run's and the previous run's
  logs (250 lines each; older logs are listed by name). It is also saved
  as `diagnostics.txt` in the data folder, to attach when copying fails.
- **Redaction.** The user folder becomes `%USERPROFILE%`, the Windows user name `<user>`, every
  account and character name stored in the database `<account>` / `<player>`, and anything else
  shaped like an account (`Name.1234`) `<account>`.
- **API.** `POST /api/diagnostics`, `/api/diagnostics/open-folder` (fixed path, nothing taken
  from the request), `/api/diagnostics/dismiss`, `/api/client-error`; `GET /api/status` gains
  `crashes`. All behind the existing localhost Host/Origin checks. `dataDir` in the status is
  now the folder next to the database (the same folder in the app; tests no longer touch the
  real data folder through it).
- **No analysis change**, no `ANALYZER_VERSION` bump.
- **Validated:** tests for the hooks, unclean-exit detection (including after a reboot), record
  cap, redaction, the report sections, the endpoints and their origin checks, client-error
  truncation and cap, and a real spawn worker that dies (`os._exit`). Live run from WSL: a
  `kill -9` was reported as "closed unexpectedly" on the next start, a posted frontend error
  reached the log, the report replaced the user name, and a clean stop removed the marker. Not
  checked yet: the Windows event-log query, the clipboard in the packaged WebView2 window,
  and the banner on screen.

## Window froze on start: pywebview walked the .NET UI (2026-11-21)

A friend's 0.5.2 "crashed" when the app started and began analyzing the previous evening's
session (87 logs). The app log had nothing useful: it was one rotating file shared by every
run, and the next start had already replaced what mattered.

- **Reproduced.** The friend's 87 logs analyze cleanly from source in WSL and in the packaged
  0.5.2 exe on Windows without a window (`--no-window`): no failures, analysis worker peak
  386 MB, main process ~85 MB, Elite Insights peak ~1 GB. With the window, the packaged exe hung
  on every start (6 of 6, with or without fights to analyze): within ~20 s the window was
  "Not Responding", the API stopped answering and analysis stopped, with 1 s of CPU used, so
  a deadlock rather than load. A user then closes it, which looks like a crash.
- **Cause.** On each page load pywebview builds `window.pywebview.api` by walking every public
  attribute of the `js_api` object, recursively (`webview/util.py`, `get_functions`), on a
  background thread. `WindowApi` kept the pywebview `Window` in a public `window` attribute, so
  the walk descended into `window.native`: the whole WinForms/WebView2 object tree, through
  pythonnet (`AccessibilityObject.Bounds.Empty.Empty...`, "CoreWebView2 can only be accessed
  from the UI thread" in the log). Touching UI objects off the UI thread while holding the GIL
  deadlocks against the UI thread. From source the same walk ran but happened to survive; in
  the frozen build it deadlocked every time here. The attribute dates from 0.3.0.
- **Fix.** The window is kept in `WindowApi._window`; pywebview skips names starting with `_`,
  so only `pick_folder` is exposed. `tests/test_window_api.py` applies pywebview's rule to the
  object after `_open_window` (only methods may be public).
- **Validated** on Windows with a packaged build of the fix and the friend's logs: import, the
  app killed after 17 fights, then a windowed start that resumed the queue (the friend's flow).
  The remaining 70 fights finished in ~3.5 min with the window responsive throughout, no
  "Error while processing" lines, and the killed run reported as "closed unexpectedly".
- **Orphaned workers.** Killing the app (Task Manager, or "close the program" on a hung window)
  left its analysis worker running on Windows indefinitely. Workers now watch the app's process
  (`diagnostics.exit_with_parent`, every 5 s, psutil `is_running` so a reused pid doesn't
  count) and exit when it's gone: 4 s after a kill in the packaged build.
- **Per-run logs.** Each start now writes `logs/wvw_analyzer-<start>-<pid>.log` (rolls over
  once at 5 MB, so ≤10 MB per run) instead of sharing one rotating file, so the log of a run
  that crashed survives the restart. At startup, run logs older than 14 days, beyond 30 runs or
  100 MB in total are deleted, oldest first; the newest 3 always stay. The diagnostics report
  includes the end of this run's and the previous run's log. The old `wvw_analyzer.log` counts
  as one more run log (see the review fixes below).

## Crash reporting: review fixes (2026-11-21)

A light `/review-changes` run over the two sections above found 2 medium and 6 low issues; all
were fixed (plan: [`plans/10-crash-reporting-review-fixes.md`](plans/10-crash-reporting-review-fixes.md)).

- **Second launch.** A launch that only shows the running app no longer writes a run log (the
  file handler is added after the port check; startup errors before it still add one). The
  report's "this run" is the current process's log; the others are ordered by last write, not
  by the start time in the name (robust to the clock going back).
- **Windows shutdown with the app open** (user's choice: keep the banner and detect it). Fast
  Startup, the default, keeps `GetTickCount64` running across a shutdown, so the boot-time
  check alone missed it. On Windows the next start also asks the System event log
  (`wevtutil`) for a shutdown or restart (User32 1074, EventLog 6006/6008, Kernel-General 13,
  Kernel-Power 41); since the heartbeat (next section), only one right after the run was last
  seen counts. The marker is also removed right after the
  window closes, before the LLM server and uvicorn shutdown, which could take ~10 s (that
  was the WebSocket and Windows connection waits fixed in "Exit after SIGTERM" below).
- **SIGTERM** (`--no-window`): uvicorn re-raises it after shutting down; a handler that raises
  `SystemExit` lets the marker cleanup run.
- **Live instances.** Markers are per process; one whose process is still alive (same pid and
  creation time, so a reused pid doesn't count) is left alone, e.g. a hung instance next to a
  new one.
- **Names with spaces.** Redaction uses the stored names (players of analyzed fights,
  commander, POV) and keeps the account pattern as a fallback for names not stored yet.
- **Old log.** The pre-0.5.3 `wvw_analyzer.log` is a report candidate like a run log (the run
  before an upgrade is usually the one being reported) and follows the same retention.
- **"Open app folder"** instead of "Open log folder": it opens the data folder, which holds
  `diagnostics.txt`, `crash.log` and `logs/` (user's choice).
- **Validated:** a regression test per fix (second launch, report order with a clock that went
  back, old log after upgrade, per-pid markers with a live and a reused pid, Fast Startup via the
  event-log answer, the event-log query string, SIGTERM on a real `--no-window` process, stored
  names with spaces, names read from a stored fight). On Windows the real query found a shutdown
  for a start a month ago and none for a start a minute ago. Not checked: an actual Windows
  shutdown with the app open (needs the user).

## Crash reporting: heartbeat and second review fixes (2026-11-21)

A second light `/review-changes` run found that any shutdown after a run started hid that
run's crash, even one hours later: the app hangs in the evening, gets closed, the PC is shut
down for the night, and the next start shows no banner (plan:
[`plans/11-crash-reporting-heartbeat.md`](plans/11-crash-reporting-heartbeat.md)).

- **Heartbeat** (user's choice). A running app writes `lastSeen` into its marker every 2 min
  (`HEARTBEAT_S`). A stale marker counts as ended by Windows only if the System event log has
  a shutdown/restart event between `lastSeen` and 5 min after it (`SHUTDOWN_GRACE_S`). The
  boot-time check is only used when there's no event log (off Windows, or the query failed).
  A hung app's heartbeat stops too (the thread needs the GIL), so a later shutdown can't hide
  the hang. `end_run` stops the heartbeat under the same lock before removing the marker, so it
  can't be written back during the cleanup after the window closes.
- **Event times are UTC.** The query filters `@SystemTime`, which is UTC. `wevtutil /f:text`
  prints its "Date" in local time with a `Z` suffix, which is misleading when checking by hand.
- **Reused pid.** A marker with this process's pid is an old run (the check runs before this
  process writes its marker) and is checked like any other.
- **Redaction order.** Stored player names are replaced before the Windows user name, and the
  `Name.1234` fallback accepts non-English letters.
- **Report:** "Elite Insights: NOT INSTALLED" instead of the version it expects.
- **Docs:** the faulthandler reason (above) and the old-log sentence were corrected.
- **Validated:** regression tests (heartbeat writes and stops at `end_run`; a shutdown inside
  and outside the window after `lastSeen`; boot fallback without an event log; reused pid;
  redaction order and `Zoë.1234`; the EI line; the query string with both bounds). On Windows,
  around a real shutdown event at 02:45:12 UTC: a window from 02:44 found it; windows
  02:00–02:40 and from 02:46 did not. Not checked: a real shutdown with the app open (needs the
  user).

## Session stats and per-player charts (2026-11-21)

Request: see all the per-fight stats (boons, cleanses, ...) for a whole session, and charts per
player, not only for the squad and parties (plan:
[`plans/12-session-stats.md`](plans/12-session-stats.md)).

- **No log combining.** Every analysis already stores its per-player rows (all stat columns,
  party, `in_fight`, active time, fight distances); session stats are built from those. No Elite
  Insights re-run.
- **How values combine** (`Column.session`, also in the column metadata):
  - `sum`: counts and amounts (damage, strips, cleanses, healing, downs, deaths, res time) and
    time in fights add up.
  - `time`: rates and shares (uptime, every generation column, stacks, distances) are averaged,
    weighted by the player's active time in each fight (fight length when missing). 40% for
    5 min and 10% for 1 min give 35%.
  - `dps`: total damage / total time in fights.
  - **Why:** the old Players tab added up every `agg: "sum"` column, so generation (summed
    across party members on the fight page) was summed across fights too: three fights at 40%
    showed 120%, and the "Stability given" leaderboard ranked by it. DPS was summed; uptimes were
    a plain per-fight mean, so a 20 s skirmish counted as much as a 6 min fight.
- **Rows.** Players (one per account, only fights they were in, with `fights`, `activeS` and
  `perMin` for `sum` columns), parties by party number (each fight's party row from its
  in-fight members, then combined weighted by fight length; `accounts` lists who played in
  it), and the squad (the same from each fight's squad row). A group row's DPS is the members'
  DPS added up, so it is time-weighted like a rate.
  - **Split rows.** EI can split one player into several rows in a fight (e.g. after a spec
    change). For the session they are one player in one fight: counts add up, rates are weighted
    by each row's time, and the longest row gives the party.
  - **Time in fights.** The session tables' time column (EI's "Active time" on the fight page)
    is `activeS`: EI's active time, or the fight's length when EI has none. DPS, per minute,
    Min. time and the rate-board rule use the same seconds. (User's call.)
  - **Party size.** "Party N · 5" is the party's usual size: in-fight players per fight it was
    in, rounded. The tooltip lists everyone who played in it over the session. (User's call.)
  - **Distances.** EI gives `distToCom` -1 in fights without a commander (and `stackDist` -1
    when there is no stack), and the commander's own distance to tag is 0. None of these is a
    distance: the session leaves them out of its averages (a player never measured shows "–").
  - **Split rows' time.** Each row of a split player counts with its own active time; only
    when no row has any does the fight's length count, as for a single row.
- **Leaderboards** use the combined values. A rate board ("Stability given") only ranks players
  with at least 25% of the session's fight time, and shows the time-weighted value without a
  per-fight column.
- **Session trend.** Per fight, for the squad, each party, each player and the average in-fight
  player: stability uptime and squad stability given, strips, cleanses, boons lost, damage,
  downs, deaths, distance to tag. `null` where they weren't in the fight, and for distance to
  tag also for the commander and in fights without a tag (the tooltip says which). For a player
  the reference line is the **average player** (a split player counts once), not the squad
  (squad totals are on another scale).
- **Session page.** Tabs Summary · Overview · Boons · Offense · Support · Defense · Positioning ·
  Fights. Stat tabs reuse the fight page's table with Players / Parties, a Total / Per minute
  toggle (`sum` columns only; time in fights stays a total) and Min. time in fights (Any, 5,
  15, 30 min). The Summary has the trend chart (stat and Squad / Party / Player pickers; click a
  fight to open it, for a player at their boons). Clicking a name in a stat table opens that
  player's trend. `?tab=`, `?player=` and the trend's `?stat=` are kept in the URL (user's
  call: the other toggles reset), so a fight's "← Session" link, browser Back and a reload
  return to the same view. The page reads them from the address bar: after Back, SvelteKit's
  `page.url` still holds the URL the page was first opened with.
- **Per-player fight charts.** The timeline stores each squad row's own series, by its
  `series_key` (also on the row): the account for the account's main row (in the fight, then
  longest active time) and `account#2`... for further rows of a split player, so links that only
  know the account (the session trend) open the main row:
  boons as runs (`[start, end]`, might and stability `[start, end, stacks]`, from EI's states at
  0.1 s), per-second health, damage out / in, healing, barrier, boon and condition counts,
  distance to tag (none for the commander) and to the squad's center, and downed / dead
  intervals clamped to the log (EI marks "until the log ends" with an int64 end).
  `ANALYZER_VERSION` 7.
  - **Served one player at a time.** The fight API drops `timeline.players`; the page fetches
    `GET /api/fights/{id}/players/{key}/timeline` when a player is picked. Sending all of
    them would add a few hundred kB to every fight page.
  - **Boons tab:** Squad / Party chips plus a **Player…** select; a player gets a lane chart
    (one lane per boon, Downed and Dead lanes; tooltip lists the boons and stacks at the
    pointer). **Debrief:** the Show select lists players; a player gets health, boons and
    conditions, damage / healing and distances, with downed / dead time shaded. Clicking a name
    in a fight's stat table opens that player's boons. `?player=` is kept in the URL.
  - **One URL write per action.** SvelteKit 3's `replaceState` is async, so two writes in a row
    (party, then tab) built the second from the old address and dropped `?player=`; the page
    now writes the tab and party in one call.
- **Validated:**
  - Unit tests with synthetic rows: time-weighted generation, uptime and distances, DPS =
    damage / time, counts summed, per minute, a player missing a fight, squad and party rows,
    the rate-board rule, trend gaps and the average player; boon runs (merging, stack changes,
    a boon held to the end); per-player series from a synthetic fight; the fight API without
    and the per-player endpoint with the series (404 for an unknown account).
  - Corpus snapshot before and after on all 142 `data/dev_corpus` fights: identical summaries,
    notes and stats except the new `timeline.players` and the columns' `session` field. Stored
    stats (zlib) grow from 3.8 MB to 8.8 MB for the corpus (about 27 kB → 62 kB per fight).
  - Dev app on a copy of the dev database (24-fight session): session stability uptime 51.8%,
    between the fights' 21.8% and 69.1%; no player above 15% squad stability generation;
    per-minute damage matches DPS x 60; five parties with their accounts; trend for the squad, a
    party and a player, a fight click opening the fight; both per-player fight charts with
    tooltips, the name click, and the party / player kept across tabs.

### Review fixes (2026-11-21)

Two `/review-changes` runs (light, then full) on the uncommitted feature found 10 distinct
issues; all are fixed, none left open. The browser check of the split-row fix found one more
(the account key first went to the first row, which may be the one not in the fight), also fixed.

- **Script in a chart tooltip (security).** ECharts sets a formatter's string as `innerHTML`, and
  the trend's series name holds a player's name from the log. A crafted log could run script in
  the app's origin, whose requests pass the localhost Origin check (settings, deletes). The trend
  tooltip is now built by `trendTooltip.ts`, which escapes names, map and result
  (`escapeHtml` in `format.ts`, also used by `timelineEvents.ts`).
- **Split rows.** Per-player series were keyed by account, so only a split player's last row
  was kept; now one per row (`series_key`, above). The session aggregate counted each split row
  as a fight and kept only the last row's trend value; now they are merged (above).
- **Death intervals** carried EI's int64 "until the end" sentinel into the API; now clamped.
- **Overlay poll cost.** The overlay's 2 s poll ran the full session aggregate (player, party,
  squad rows, trend) and unpacked each fight's stats blob, now about 2.3x bigger, to read only
  notes. It now uses `aggregate_session(..., detail=False)` (results, totals, problems,
  strengths only), `session_analyses(..., players=False)` and `analysis_notes()`.
- **DB lock.** `save_analysis` serialized and compressed the stats inside the DB lock (55–90 ms
  for the largest fights); now before taking it.
- **Profession color.** Session rows list several professions; `profColor` now colors by the
  first (most played) instead of falling back to gray.
- **"← Session" link** on a fight page now returns to the session as it was left (tab, player
  picked in the trend), remembered by `sessionNav.ts`.
- **Time column and party size:** decided by the user (see Rows above).
- **Why `ANALYZER_VERSION` 7** (6 was never released): stored v6 per-player series are wrong for
  split players (only the last row, under the account) and carry the death sentinel.
- **Validated:**
  - A regression test per fix: 8 backend tests in `tests/test_session_stats.py` (all failing on
    the code before the fixes, run against a frozen copy) and 4 frontend tests in
    `frontend/tests/` (new `npm test`, Node's built-in runner, no new dependency).
  - Corpus snapshot before (frozen copy of `backend/`) and after, all 142 fights in zerg and GvG
    mode (186 analyzed results): summaries, notes and stat tables identical apart from the
    version and the new `series_key`; 5,882 single-row series identical except 110 death ends
    clamped to the fight end; all 30 split accounts keep their old series as one of their rows,
    with the account key on the in-fight row.
  - Dev app on a copy of the dev database: re-analysis to 7, "Time in fights" and party sizes
    (e.g. Party 2 · 4, "6 players over the session"), no gray bars for multi-profession players,
    the trend tooltip still renders, the back link keeps the picked player, and on a fight with
    a split player each row's name opens its own series and the trend's link opens the in-fight
    row.

### Review fixes, second round (2026-11-21)

A light `/review-changes` run after the first fixes found 6 issues; all are fixed, none left
open. The browser check of the fixes found one more, also fixed.

- **Session distances** averaged EI's -1 ("no commander") and the commander's 0 into Dist. to
  tag for players, parties and the squad (-1 for every player in a fight without a tag).
- **Trend tooltip** said "not in this fight" for a missing distance to tag; it now says "no
  distance (the commander, or no tag)" when they were in the fight (`present` per fight from the
  damage series).
- **Average player** counted a split player once per row; it now uses the merged rows.
- **Parties footnote** described player rows; the text now comes from `sessionNotes.ts` per
  mode.
- **Split rows' time:** a split row with 0 active time weighted its rates by the fight length
  but added 0 to the time; now each row uses its own active time (above).
- **Trend stat in the URL** (`?stat=`, user's choice of the options).
- **Found in the browser check:** after browser Back, the session page restored its view from
  `page.url` (the URL it was first opened with) instead of the address bar.
- **Found in the corpus compare:** session party `accounts` with equal counts were ordered by set
  iteration, so the order changed with Python's hash seed; now row order.
- **No `ANALYZER_VERSION` bump:** only the session aggregate and the frontend changed; stored
  analyses are the same.
- **Validated:**
  - 4 backend regression tests (all failing on a frozen copy of the code before), including the
    aggregate run under three hash seeds; 3 frontend tests (tooltip text, footnote, URL state).
  - Session aggregates for the 3 corpus days before and after: identical apart from Dist. to tag
    (players, parties, squad), the average-player trend and the account order; the same under two
    hash seeds.
  - Dev app on a copy of the dev database: no negative Dist. to tag, "–" for the commander, the
    commander's trend tooltip, the Parties footnote, the trend stat kept through a fight and back
    by the in-app link, browser Back and a reload.

## Trends across sessions, first slice (2026-11-22)

Plan: `docs/plans/13-trends-first-slice.md`. The original plan only said "a trends page
(across sessions)"; this is the smallest useful part of it.

- **What it shows.** A **Trends** page: one point per session with analyzed fights, oldest
  to newest, for one of three stats (win rate, K/D, squad deaths per fight; the pick is kept in
  `?stat=`), and a table with one row per session (newest first): fights, results, the three
  stats and the session's top recurring problem. A point or a row opens the session.
- **Numbers come from the session summary.** `GET /api/trends` runs
  `aggregate_session(detail=False)` per session, so the page can't disagree with a session's
  own Summary; GvG deaths after a call-off are left out in both.
- **Win rate** is wins / (wins + evens + losses). Skirmishes are left out, as on the Sessions
  cards (user's choice of the options). A session of skirmishes only has no win rate (a dash),
  not 0%.
- **GvG and zerg fights count together**, one result per fight, as on the Sessions page
  (user's choice; a mode filter is not built).
- **Sessions without analyzed fights are left out**; with no session the page says so, and
  with one it shows the point and says a trend needs two.
- **Escaping.** Session names are typed by the user or come from a folder name; the chart
  tooltip is built by `sessionTooltipHtml` (`frontend/src/lib/trends.ts`), which escapes them.
- **No analysis change**, so `ANALYZER_VERSION` stays.
- **Review fix (2026-11-22): one fight order for both pages.** The session summary ranks
  problems with a stable sort, so a tie goes to the problem seen first. The Trends query
  ordered a session's fights by `COALESCE(fight_start, created_at), id` and the Summary's
  query by `fight_start` alone; with a fight that has no start time the two could name a
  different top problem. Both now use `FIGHT_ORDER` (`fight_start, id`) from `store/db.py`.
  For the Summary this only adds an explicit tie-break for fights with the same start. A
  session's start on the Trends page is its first fight that has one.
- **Validated:** `tests/test_trends.py` (rows, order, win rate, skirmishes, GvG late deaths,
  the top problem, a tie with a start-less fight, the API against each session's summary) and the tooltip test in
  `frontend/tests/helpers.test.ts`. Browser check on a throwaway instance with six synthetic
  sessions: the picker and `?stat=`, a deep link, the tooltip (a script-like name stays text),
  point and row clicks, the empty and one-session states (with a stubbed API response).
  Screenshots timed out, so nothing was checked by eye.

## Exit after SIGTERM with a page connected (2026-11-22)

`--no-window` didn't exit after SIGTERM: the port closed within a second, but the process
stayed alive (seen for 6 minutes) until killed, with nothing in the log.

- **Cause.** The `/ws` handler only waited for the next event and never read from its socket.
  uvicorn tells a handler that its socket closed (page gone, or server shutting down) through
  that read, so the handler stayed in its wait until the next event. At shutdown no event
  comes, and uvicorn waits for open connections with no time limit. A tab closed earlier had
  the same effect, as long as no event came after it closed. The window had it too: closing it
  waited the full 10 s join, and the server's lifespan shutdown (stopping the processor,
  finishing a recording's last log, the LLM) never ran before the process exited.
- **Fix.** The handler sends events and reads from the socket at the same time, and ends as
  soon as the socket closes. The page still sends nothing.
- **Safety net.** uvicorn now waits at most 5 s (`SHUTDOWN_TIMEOUT_S` in `main.py`) for open
  connections and requests at shutdown, then cancels them. A connection stuck in some future
  way can delay the exit, but not stop it.
- **Validated:** reproduced from WSL on a throwaway instance with a WebSocket client (open at
  the signal, and closed before it); SIGINT forced uvicorn out and the only task it cancelled
  was the `/ws` handler. `tests/test_shutdown.py`: SIGTERM on a real `--no-window` process with
  the page's socket open and with it closed earlier, and the windowed path (page connected,
  window closed) with the lifespan shutdown run. Each must finish in under 3 s, below the safety
  net, and all three failed with the old handler. After the fix both live cases exit in 0.3 s
  and events still reach the page.
- **Windows: closed connections kept the server waiting** (found in the 0.6.1 smoke test).
  With the handler fixed, closing the packaged app's window still took 6.3 s: uvicorn had no
  connections or tasks left, but the asyncio server still counted 9 connections, so its last
  step (`Server.wait_closed`) only ended at the 5 s limit. Python 3.12's proactor loop calls
  `sock.shutdown()` when a connection closes; when the browser already closed its end that
  fails with WinError 10022, and the rest of the cleanup (closing the socket, leaving the
  server's count) is skipped. The app used to hide that error as log noise (`_ProactorNoise`);
  that filter is gone. `main.detach_closed_sockets` wraps the proactor's cleanup on Windows
  and finishes it when the shutdown fails (logged at debug). Probably most of 0.6.0's ~10 s
  window close came from this too.
- **Validated on Windows:** closing the window of a traced run from source took 6.3 s with
  "Cancel 0 running task(s)" and 9 connections still counted; with the fix the count was 0,
  uvicorn finished 0.1 s after starting to shut down and the process exited 1.5 s after the
  window closed. `tests/test_proactor_close.py` runs the standard library's own cleanup with a
  socket whose shutdown fails: unpatched it keeps the connection counted; patched it closes
  and detaches it, still raises an error from the protocol, and leaves a normal close as it was.

## In-game overlay redesign (2026-11-25)

Plan 14. Players use the overlay most, and it read as flat, compressed text.

- **Notes strictly by severity.** The ranker sorted critical with major and minor with context
  by impact, so a major could sit above a critical. Now it is severity, then impact. Which
  critical and major notes are kept can't change; only which minor and context notes make the
  top five. `ANALYZER_VERSION` 8.
- **A version bump keeps debriefs.** The keep rule compared the whole summary, which carries
  `analyzerVersion`, so every bump dropped every stored LLM debrief, and auto-debrief only
  rewrites the latest session. Found in the plan review.
- **Payload, still schema 1.** Only added fields: `badge`, `heading`, `meta`, `facts` (stat
  tiles: label, value, note, tone), `headline` and `numbers` (the small panel),
  `issuesTitle` (the fight page's wording), `moreCount`, `session.strip` (every analyzed fight,
  oldest first), and `session.problems[].severity` is now the worst one across the problem's
  fights (computed in `overlay.py`; the app's session page is unchanged). GvG facts count only
  kills and deaths inside rounds, like its result line. The new addon falls back to `title`
  and `resultLine` with an older app.
- **The addon stays a dumb renderer.** Every fact comes from the app. The addon writes labels
  and composes a few lines from the app's numbers, and a wording change there needs an addon
  update:
  - labels: the tab names, "NEXT TIME", "WENT WELL", "Fights", "click to open a fight",
    "Recording", "Not recording", "Not connected", "Start", "Stop", "Latest", "Open debrief",
    "Debrief, worded by the local LLM", and the empty and error states;
  - from numbers: the session tiles ("40 fights", Kills, Deaths, KDR with two decimals),
    "3 of 7 · 2 lost", "4 of 7 fights", "<name> · 48:12 of fighting", "N more in the app",
    "N more · hides when combat starts", "Fight n of N", "Analyzing (N queued)".
  (Listing corrected after the review, plan 15.)
- **Drawing is platform-independent.** `addon/src/view` uses `arcdps-imgui` directly (the same
  0.8.0 with `tables-api` that nexus-rs uses, so the types are shared) and runs on Linux.
  `ui.rs` and `addon.rs` keep the Nexus glue. Decisions that aren't drawing are plain, tested
  functions: which cards start open, the small panel's rules, the settings migration.
- **Preview without the game.** `cargo run --example preview` runs the same view code in a
  headless ImGui context and turns the draw data into PNGs with a small CPU rasterizer (vertex
  color times the atlas alpha, clip rectangles, alpha blending; no new dependency). Layout,
  wrapping, sizes and colors match; Nexus's renderer and UI scale don't.
- **Look ("A, cards", agreed on mockups).** No native title bar; a header band with the queue,
  the recording state with Start/Stop and Close ("Not connected" without the app). A tab
  switch, then a fixed result block (badge, map, time and length, four stat tiles) over a
  scrolling list. One card per issue: critical and major open, minor and context one line;
  with nothing serious the first card opens. A click toggles a card, kept per fight while the
  game runs. Colors and sizes are in `view/theme.rs`. Default size 460 by 600 (a saved size is
  kept: the window id is unchanged), minimum 360 by 200.
- **Fonts.** Inter Regular and SemiBold, static TTFs subset to Latin and Latin Extended
  (about 40 KB each), embedded in the DLL; the OFL text ships as `bin/addon/Inter-OFL.txt`.
  Six sizes (Regular 12, 13; SemiBold 11, 13, 15, 18) go to Nexus with
  `FontDataOwnedByAtlas = false`, so ImGui never frees the embedded bytes. Nexus hands back
  raw `ImFont` pointers, kept in atomics (a callback may come while the addon's lock is held)
  and pushed with `igPushFont`; until then the current font is used. A change of the game's
  interface size resizes them (`resize_font`). Nexus may build a font larger than asked
  (in game: 1.5 times, Windows scaling at 150% with Nexus's DPI scaling on), while the layout uses the UI scale
  alone; the addon measures that factor on the first font it gets back and asks for that much
  less, so text keeps the mockups' size against the spacing. See "Overlay: first look in game".
- **Tiles that don't fit.** A tile's note goes on its label line ("Squad · +2 allies"); a value
  too wide drops to 15 px, then wraps at spaces onto more lines (`21W 12L` / `5E 2S`); only a
  single word too wide is clipped. (An ellipsis first; it hid the losses at 360 wide. Plan 15.)
- **Small panel after a fight.** A second window, sized to its content, movable, no focus on
  appearing and no keyboard navigation. It shows once a new fight is analyzed, the player is
  out of combat, the full window is closed and the payload already has the new fight. Combat,
  dismiss, Open debrief or opening the full window hide it; it comes back only for a newer
  fight.
- **"After a fight" setting**: small panel (default), full window, or nothing. It replaces
  "Show the window when a new fight is analyzed": a saved `false` becomes nothing, anything
  else the small panel; the other options are kept. An unknown value falls back to the
  default without resetting the rest.
- **Validation.**
  - Corpus (142 fights, zerg mode) before and after: 16 fights changed, 13 that were out of
    severity order and 3 where a minor note replaced a context note in the top five. Summaries
    (apart from `topIssue`, `topSeverity`, `analyzerVersion`), positives and the set of issues
    are identical in every fight.
  - Python: the ranker order, a version bump keeping the debrief, the new payload fields (zerg
    and GvG facts, strip, worst severity, old fields kept), the regenerated fixture; all tests
    and ruff pass.
  - Rust (Linux): parsing with and without the new fields, default-open cards, capitalizing a
    fact, the small panel's rules, the settings migration; clippy clean for Linux and
    `x86_64-pc-windows-msvc`. The preview draws every state without a panic and was compared
    with the mockups by eye (win, loss with a card opened by click, clean win, no fights, app
    not running, a problem, 360 wide, five open cards scrolling, long titles, an older app,
    the session tab with 7 and 40 fights, the small panel).
  - Not yet checked in game: sharp fonts at the UI scale, dragging by the header, the small
    panel without keyboard focus and hiding in combat, scrolling and resizing, the options and
    the settings migration, frame time.

## Overlay redesign: review fixes (2026-11-25)

Plan 15. A full review of plan 14 (performance, security and use cases; Opus reviewers) found
two medium and four low issues; all are fixed. Analysis output is unchanged.

- **The session strip scrolls (F1).** It sat fixed above the list, so a long session or a short
  window (90 fights at 360 by 420) left the recurring problems no room at all. Only the tiles
  stay fixed now, like the fight tab's result block. Decided with the user.
- **Fonts handed to Nexus live on the heap (F2).** The font bytes (`FontDataOwnedByAtlas =
  false`), the glyph ranges and the font config pointed into the DLL's static data. If Nexus
  keeps a font after the addon is unloaded or hot-reloaded, a later atlas rebuild would read
  freed memory and crash the game. They are now heap copies that are never freed (about
  80 KB per load). Whether Nexus actually keeps them is unknown (its font manager isn't in this
  checkout); the copies are safe either way.
- **Long unspaced words are cut in one pass (F3).** The old cut re-measured each prefix,
  roughly cubic: a 1,800-character LLM debrief line cost about 11 ms per frame. It now adds up
  character advances (ImGui 1.80 has no kerning).
- **Tile values wrap (F4)** instead of the ellipsis, see "Tiles that don't fit". Decided with
  the user.
- **The addon-written strings are listed (F5)** under "The addon stays a dumb renderer".
- **Two wrong comments (F6)**: chip padding, and the window style's lifetime.
- **Validation.** New Rust tests: a 10,000-character word cut into fitting pieces with nothing
  lost in under 500 ms (debug build), a too-wide tile value wrapping at spaces, the heap copies
  holding the same bytes away from the statics. Preview: a 90-fight session at 360 by 420
  scrolls to its problems; the record wraps at 360 and 460. pytest, ruff, cargo test, clippy for
  Linux and Windows, the preview and the DLL build pass. Not checked in game.

## My play: personal improvement hints (2026-11-25)

Plan: [`plans/16-player-improvement.md`](plans/16-player-improvement.md). Hints for one player
(any account in the logs), for a fight, a session or many fights, from the user's own logs only.

- **Facts at analysis time, rules at request time.** The analysis worker writes one
  `player_fights` row per squad row (`metrics/personal.py`, zlib JSON): downs from
  `timeline.squad_downs` (plus the party's stability the second before, health 3 s before, other
  squad downs within 4 s, rank, the death recap's span, enemies and top skills), downs left at a
  GvG call-off kept apart and never judged, time dead and downed clamped to the log, cast time
  without auto-attacks (dropped above 100), cancelled casts, dodges (`Dodge` casts), food and
  utility (buff classes), top 5 skills dealt and taken, the row's job, and per stat the
  row's value, the median and count of same-spec, same-job peers and the squad median. The rest
  of the squad's downs are stored per row as compact tuples, without the row's own account, so a
  rule never needs another row. `coach/` reads only these rows, so thresholds change without a
  re-analysis. `ANALYZER_VERSION` 9 (8 is the notes order from the overlay redesign). Which row a squad down belongs to is kept in
  `Timeline.squad_down_keys`, outside the stored series.
- **A rule is a comparison, never a bare share.** "Clearly above the squad" is an exact tail
  probability at the squad's rate in the same fights (Poisson for the down rate, binomial for a
  share of downs, Poisson-binomial for "among the first three") at 5%, plus a ratio or margin.
  The baseline is the rest of the squad (the player's own downs left out). A player at the
  squad's rate never fires; "Nothing stands out in N fights" is a result with its own text.
- **Same spec is not same job.** A row's job is its strongest output against the squad median
  among the outputs that reach 25% of the squad's strong players (90th percentile of those with
  any). **Why:** `player_outliers`' absolute per-minute minimums left a third of rows without a
  job in quiet fights, so a player's job flipped between fights in 66% of player+spec groups;
  with the relative bar it is 38%, mostly hybrid specs (strips vs damage). A player's job on a
  spec is the one they had in most fights on it; each row stores the same-spec peers' medians
  per job (`spec_peers`), so the player is compared with that job's peers in *every* fight on
  the spec, not only the fights where their own row came out with that job (which would leave
  out exactly the weak ones).
- **Survival runs over all fights and says when one spec stands out.** If the down rate isn't
  high overall but is on one spec (its own gate and test), the hint is about that spec. The
  hint names a cause (no stability, far, alone, first down) when that cause stands out in the
  same fights, even with the cause rules off. Causes rank right after the rate, never above it.
- **Rules kept (user's choice of the options, after the calibration).** On by default:
  `me_deaths`/`me_survivor`, `me_low_output`/`me_top_output`, `me_low_activity`/`me_active`,
  `me_no_food`. Off by default, available in Settings: `me_down_no_stab`, `me_down_far`,
  `me_caught_alone`, `me_first_down` (fired at chance level), `me_far_from_tag` (fired for
  nobody), `me_cc_taken` (fired for 1 player). Their overrides live in `Settings.detectors`
  next to the detectors' (`registry.check_overrides` knows both registries); the Settings
  page lists them in a "My play" section with the account to open on (`Settings.my_account`;
  default: the account that recorded the most fights).
- **Calibration** (`scripts/calibrate_personal.py`, dev corpus: 93 analyzed fights, 91
  accounts, 2,910 in-fight rows; every rule on; profile scope):

  | Rule | Past the gate | Issue | Strength |
  |---|---|---|---|
  | `me_deaths` | 78 | 19% | 9% |
  | `me_down_no_stab` | 64 | 6% | – |
  | `me_down_far` | 64 | 3% | – |
  | `me_caught_alone` | 65 | 6% | – |
  | `me_first_down` | 53 | 2% | – |
  | `me_far_from_tag` | 86 | 0% | – |
  | `me_low_output` (per spec) | 53 | 21% | 11% |
  | `me_low_activity` (per spec) | 53 | 13% | 15% |
  | `me_cc_taken` | 76 | 1% | – |
  | `me_no_food` | 87 | 31% | – |

  The cause rules' p-values were spread like chance (2 to 4 of about 64 players at p < 0.05,
  where chance gives 3.2): down causes are squad-level in this corpus, as the plan found. The
  down rate separates players (15 of 78 at p < 0.05, chance 3.9). No player was far from the
  tag in most of their fights (the most: 46%). `me_no_food` is mostly "no utility": 16 players
  almost never use one, a steady habit. Output thresholds 0.65 / 1.4 are about the 13th and
  88th percentile of the median ratio to peers; activity's strength bar was raised to 1.35 for
  the same reason. The recording player's profile: down rate 1.4x the squad overall (under the
  bar), 2.1x on one spec (25 downs, the squad's rate 11.9, time dead 16% vs 4%); strengths in
  strips and cast time on another spec; "nothing stands out" on two of the three days.
  Examples checked by hand against the raw logs: down times, strip peers, a 0-cleanse support
  fight, a log with food and no utility.
- **Down-rate gate.** The rule judges once the player's downs *or* the squad's rate for their
  time reach 3 (a squad that never goes down still makes 10 downs stand out). Its trend
  compares downs per 10 minutes beyond the squad's rate (a difference stays finite).
- **Scopes.** `fight`: no habits, each down gets the hint that matches it (most specific
  first: call-off, no stability, far, alone, low health, bomb, burst). `session`: half the
  gates and "this session" wording. Several sessions or all fights: full gates and a trend
  (the latest third of the fights against the rest). Two logs of the same fight (time spans
  overlapping by half the shorter) count once, the player's own log first; split rows count
  as one player.
- **Pages.** My play (player, scope and spec in the URL), a fight's and a session's **You**
  tab (following the page's `?player=`), and `?t=` on a fight to open a player's chart at a
  down. Deep links from examples and "Your downs" use the row key.
- **Storage.** Dev database copy (29 fights) vacuumed: 3.25 MB → 3.86 MB; the facts take
  15.8 kB per fight against 52 kB of stats and 53 kB of player rows.
- **Validated:**
  - Corpus snapshot before and after, all 142 logs in zerg and GvG mode (186 analyzed
    results): summaries, notes and stat tables identical apart from the version.
  - `tests/test_personal_facts.py` (downs with and without stability, alone and in a bomb,
    GvG call-off downs, clamped times, cast time above 100, recap and skill tables present and
    missing, consumables, dodges, peers without the commander, a split player, the table),
    `tests/test_coach.py` (every rule at, below and above its gate and exactly at the squad's
    rate, per-spec standout, the main-job comparison, trend, same fight twice, split rows,
    defaults and overrides, every `me_*` template's placeholders in its evidence) and
    `tests/test_my_play_api.py` (each scope, unknown player, too little data, nothing to work
    on, the default account, the Settings list); frontend helper tests for scopes, links and
    formatting.
  - Browser check on a throwaway instance built from the corpus: My play for the recording
    player and another player, an example opening the fight on the player's chart with the
    down highlighted, a fight's You tab against its stat tables and timeline (downs, damage
    taken, CC, dodges, healing and distance identical), a session's You tab, and saving a
    personal rule from Settings.
- **Review fixes (2026-11-25).** A light `/review-changes` run found 5 issues; all are fixed.
  - **Tails on long profiles.** The binomial tail overflowed (`math.comb` of 1,000+ downs) and
    the Poisson tail underflowed (`exp(-mu)` above about 745), so on an "all fights" profile
    the review returned a 500 once the down rate fired, or the down rate never fired. Both are
    now summed on a log scale (`lgamma`), and the cause check that names a down-rate cause has
    the same error guard as the rules.
  - **Settings thresholds in "Your downs".** The split table and the per-down hints used the
    cause rules' defaults; they now use the rules built from Settings.
  - **A player who wasn't in the fight** got an empty recap and a "You" tab stuck loading; the
    API now answers 404 and the tab only offers players who were in the fight.
  - **Fights you led** count for survival and food (user's choice of the options; the README
    said "survival only").
  - **Validated:** regression tests for each (exact tails at 1,030 and 760 and against brute
    force on small cases, a 400-fight profile that fires and names its cause, thresholds from
    Settings in the split and the hints, the 404); no analysis output changed, so no
    re-analysis.

## Overlay showed an empty session (2026-11-26)

Found while testing the redesigned overlay in game: with no recording running, it showed no
fights at all.

- **Cause.** The overlay takes the top of the Sessions list, which sorts sessions by their last
  fight's start, or by their own start when they have no fight. The two are stored in different
  formats ("2026-11-21 18:40:16 +01:00" and "2026-11-21T02:05:00") and were compared as text,
  where the "T" sorts after the space. So two recordings started and stopped without a fight at
  02:05 sorted above the raid whose fights ran until 18:40, on the Sessions page too.
- **Fix.** The session start is compared in the fights' format (`SESSION_START` in
  `store/db.py`), ties go to the newer session, and the overlay skips sessions without an
  analyzed fight unless it is recording one.
- **Validated:** `tests/test_overlay_api.py` (empty sessions earlier the same day, and an empty
  session that really is newer); it fails on the code before the fix.

## Overlay: first look in game (2026-11-26)

A capture of the game window (the overlay on the Fight tab, at 4K with interface size Larger and
Windows scaling at 150%) matched the mockups in look and layout, with two problems:

- **Text too large for the layout.** The 15 px heading ("Eternal Battlegrounds", 129 px wide
  in the preview at scale 1) was 320 px wide, 2.48 times, while the spacing was at Nexus's UI
  scale (about 1.67). So Nexus builds registered fonts 1.5 times the asked size: Windows scaling
  is 150% and Nexus's DPI scaling is on (its font manager isn't in this checkout). A first
  estimate of 1.22, from fitting the text to Inter with another renderer, was wrong; compare
  with the preview, which uses ImGui's own text metrics. Tiles and titles wrapped early ("Squad · +22 allies" on three lines). Fix: the addon measures
  the factor once (built size times ImGui's global font scale, against the size it asked for,
  from a font as first added) and then asks for every size divided by it; a factor outside 0.5
  to 4 is ignored. Measuring once avoids a resize loop.
- **Nexus.log flooded.** nexus-rs sets the log level to Trace, so ureq's debug and trace lines
  (a hex dump of every overlay request, every 2 s) filled the log: 7,953 of 8,073 lines in
  8 minutes, about 8 MB an hour. There since the first addon (plan 5). Fix: `load()` caps the
  level at Info; nexus-rs's `log_filter` feature would do the same with a much larger DLL.
- **Validation.** A Rust test for the factor; cargo test, clippy for Linux and Windows and the
  DLL build pass. In game after the fix: Nexus.log reports "Nexus builds fonts 1.50x the asked
  size", the heading is 212 px wide (1.64 times the preview, against a layout scale of 1.67),
  the Squad tile's label takes two lines at 360 wide, and the addon wrote no debug or trace
  lines.
- **A size option.** At the mockups' proportions the body text (13 px at scale 1) was about
  20% smaller than the game's own text and arcdps's at interface size Larger, and Inter
  Regular's strokes (under 2 px at 4K) looked soft. Decided with the user: an option rather
  than a bigger type scale for everyone. *Size* in the addon's Nexus options offers 100%
  (default, the mockups), 115% and 130%, stored as `size` in `settings.json` (a missing value
  is 100%, any other the nearest choice). It multiplies the UI scale, so text and layout grow
  together and wrapping stays as in the preview. Font sizes are also rounded to whole pixels
  before the Nexus factor is taken out.

## Overlay: in-game UI review (2026-11-26)

Captures of the game window while the user clicked through the overlay at 130% (Fight and
Session tabs, older fights, a fight opened from the strip, the options and the size switch).
Fixed, decided with the user:

- **The fight arrows stay put.** At the newest fight the newer arrow and **Latest** were hidden
  and the row is right-aligned, so the older arrow moved about 130 px right; paging back by
  clicking twice landed on the label. Every slot is now always drawn, unusable buttons dimmed,
  and the "Fight n of N" slot fits the session's widest number, so the arrows don't move.
- **Recurring problems rank by their worst severity.** The session summary kept the severity a
  problem had in the first fight it appeared in, while the overlay showed the worst one. In the
  reviewed session "Downed allies were not picked up" (13 of 24 fights, all 13 lost) showed
  MAJOR but ranked as minor (its count weighs 0.3), below "Outnumbered" (11 lost). The summary
  now keeps the worst severity, for the ranking, the overlay and the app's Sessions page alike.
  Analysis output is unchanged.
- **The keybind has a name in Nexus:** "Toggle WvW Analyzer window" instead of
  `KB_WVW_ANALYZER_TOGGLE`, in English for every language Nexus ships.

Left as they are: a lone "4." when a fact wraps, the skirmish line's hyphen (code-written
framing, also in the app) and the session name format (the app's own name).
Not captured: the "went well" cards, the debrief row, recording, the small panel after a fight.
Validation: a backend test where ranking by the first severity puts the problems the other way
round (fails without the fix); the preview's newest-fight state keeps the arrow in place at 460
and 360 wide; pytest, ruff, cargo test, clippy for Linux and Windows and the DLL build pass.

## In-app updater (2026-11-26)

Friends only learned about a new version when told, then had to find the release page (plan:
[`plans/17-app-updater.md`](plans/17-app-updater.md)).

- **GitHub Releases only, no other hosting.** `releases/latest` (no login, 60 requests an hour
  per IP, no drafts or pre-releases) gives the tag, notes and assets, with GitHub's own sha256
  `digest` per asset.
- **On by default, switchable** (`check_updates`, Settings > Updates): a check ~30 s after
  start, then every 24 h while running, and "Check now". This is a deliberate exception to "no
  network beyond what's needed": the request carries a generic User-Agent
  (`wvw-analyzer/<version>`) and nothing about the user. Failures are logged at INFO and never
  shown as an error banner.
- **Download only on click.** "Install and restart" downloads the installer; nothing is fetched
  in the background (the check reads only the small manifest files, and only when the release
  is newer). Decided over a background
  download: ~57 MB per release for everyone is more traffic than the wait saves.
- **Signed manifest (Ed25519).** The installer isn't code-signed and a file downloaded by
  Python has no Mark-of-the-Web, so the app's own checks are the only gate. GitHub's digest
  proves the download matches the upload, not who uploaded it. Each release carries
  `latest.json` (version, installer name, size, sha256) and `latest.json.sig`; the app trusts
  the keys in `updater.TRUSTED_KEYS` (a list, so a key can be rotated). Before the installer
  runs: the signature matches a trusted key, the signed version is newer than the running one
  and equals the tag (no replaying an old signed release), the file has the signed size and
  sha256 and GitHub's digest, and the name is `WvWAnalyzer-Setup-<version>.exe`. The cached
  manifest is re-verified at download time and the file re-hashed right before it runs. A
  release without a valid manifest is announced with a link only. Release notes are unsigned:
  shown as plain text. Accepted: someone with the GitHub account can hide an update, not push
  one. The private key stays outside the repo, passphrase-protected
  (`scripts/release_sign.py`). `cryptography` is the new dependency (the standard library has
  no Ed25519; a hand-written verifier wasn't worth the risk).
- **Install hand-off.** The install endpoint takes no body: it uses only the release from the
  app's own last check. It is refused while recording or while logs are queued (the installer
  closes the app), and checked again after the download. When the file is verified, the app
  sets an exit request; `main.py` closes the window (or stops the server), the normal shutdown
  runs (the run is marked as closed normally, llama-server stops), and only after a clean
  shutdown the installer starts detached with `/SILENT /SUPPRESSMSGBOXES /NORESTART
  /RELAUNCH=1`. The child gets `PYINSTALLER_RESET_ENVIRONMENT=1`, no `_PYI*`/`_MEIPASS*`
  variables and a reset DLL directory, so neither the installer nor the restarted app inherits
  the frozen app's bootloader state. Error 740 (elevation needed) falls back to ShellExecute.
- **Installer restart entry.** `[Run]` gets `nowait runasoriginaluser; Check: ShouldRelaunch`,
  reading `{param:RELAUNCH|0}`: Inno's `{param:}` only sees `/Name=Value`, so a bare
  `/RELAUNCH` would never restart the app (found in the plan review, from Inno's source).
  `runasoriginaluser`: after an all-users (elevated) install the app must not restart as the
  admin account, with another data folder.
- **Unfinished updates.** `update.json` in the data folder records the attempted version. If the
  next start still runs an older version (UAC declined, install aborted), a banner offers to run
  the kept installer again with its normal wizard (re-hashed first). At startup old installers
  in `updates/` are deleted; a file in use (the installer that just restarted the app) is left
  for the next start.
- **Banner rules.** "Later" (until the app restarts) and "Skip this version" hide the offer,
  also after a failed download; only a download in progress keeps it up. Checks turned off
  also hide the banner for a release found earlier (Settings still shows it). The "did not
  finish" banner has its own Later, and a release newer than the unfinished one replaces it.
  The page re-reads the update status after recording or queue events, so an install blocked
  by recording becomes available once it stops.
- **Errors.** A malformed reply (`http.client` errors are not `OSError`) counts as "could not
  reach GitHub"; the daily loop survives any error; a download that fails in any way ends as
  "failed".
- **Only the installed Windows app installs.** From source the app checks and links to the
  release page.
- **Testing hooks.** `WVW_UPDATE_API` points the check at another URL (plain HTTP allowed then);
  `WVW_UPDATE_TEST_KEY` adds a trusted key only together with it, so the production key never
  signs a test release.

Validation: `tests/test_updater.py` (37 tests: versions, a signed release, same/older versions, a
tag that isn't a version, offline, no manifest, tampered/wrong-key/mismatched/replayed manifests,
asset size and digest mismatches, a build without keys, the test key rule, skip, download and
exit request, busy before and during the download, a tampered download, an edited cache,
unfinished update and retry, cleanup with a locked file, installer arguments and environment,
the re-hash before launch, the window/server close, launch only after a clean shutdown, the
API with the Origin rule, the signing script round trip, the installer script's restart entry;
after the review: no manifest requests when up to date, malformed replies, the loop surviving
an error) and a frontend test for the banner rules. An independent use-case review found six
issues (a failed download kept the banner, no refresh after recording stopped, manifest
requests on every check, `http.client` errors, checks off kept the banner, the unfinished
banner could not be hidden); all are fixed with tests, except the refresh after recording
stops, which is checked by reading only (the live store isn't unit-testable). Run against a local fake release server: the automatic
check after ~30 s verified a test-signed release without downloading the installer; with
installing allowed, the install click downloaded and verified the file, the app closed itself
cleanly (no run marker left) and handed over the installer; the next start reported the update
as unfinished. Not run: the Windows install itself (needs the user, see the plan's validation
list).

## Combat replay and synced video (2026-11-26)

Plan 18 ([`plans/18-combat-replay-video-sync.md`](plans/18-combat-replay-video-sync.md); written
as plan 17 and renumbered on merging, as 17 went to the in-app updater). A fight's **Replay** tab plays the fight on the map and, when a linked recording
covers it, the video at the same moment; clicks on the fight timeline and "▶ Replay" links jump
there. An optional OBS connection starts and stops OBS with the app's recording and links the
files.

- **Replay data: Elite Insights' combat replay, cached per fight.** The EI JSON already has
  every actor's positions (at the polling rate, in the replay map's pixel space), facing and
  down / dead / disconnected intervals (`ParseCombatReplay=true` was already set), so old
  fights replay without a re-parse. It is extracted in the worker process (the EI JSON is tens
  of MB unpacked) into `<EI JSON name>.replay.json.gz` next to the EI JSON, with the source's
  size and time inside, so a re-parse rebuilds it. The biggest corpus fight (12.5 min, 138
  actors) builds in about 2 s and is about 700 KB gzipped; opening it again takes 40 ms. Not
  part of the analysis: no `ANALYZER_VERSION` bump.
- **Cleanup keeps the replay cache.** The startup cleanup deleted every unreferenced
  `.json(.gz)` in `ei/`, which would have wiped the caches each start. A `*.replay.json.gz` now
  stays while the EI JSON it was made from is used, and goes with it (fight deletion too).
- **Facing:** EI's orientation is the angle in the replay's pixel space (it matches the
  direction of movement within 2° on the corpus), drawn for the squad and allies only.
- **Map images: Elite Insights' own, downloaded on demand.** EI names an image per fight for
  Eternal Battlegrounds, the Alpine and Desert Borderlands and Edge of the Mists, and its
  positions are already in that image's pixels, so no coordinate fit is needed. The four images
  are pinned, checksummed downloads (`tools.MAP_IMAGES`, about 8 MB), fetched from the Replay
  tab or Settings into the data folder; the page never loads them from the internet, and they
  are not shipped in the installer (they are derived from ArenaNet's maps). **Seared
  Borderlands has no image** (most of the corpus): EI frames those fights in a box around the
  fight itself, whose origin is not in the JSON, so no fixed image could be aligned. It shows a
  grid in game units with a scale bar.
- **Videos are linked by time, not to a session.** A video covers every fight its span
  overlaps, in any session. The page maps fight second `t` to video second with
  `fight_start + t - video_start - paused_before(t) + offset` (`frontend/src/lib/videoSync.ts`):
  the fight start is the log's `timeStartStd` (not `instanceTimeStartStd`, the map entry), one
  offset per video fixes every fight in it, and pauses come from OBS.
- **A video's start**, best first: the OBS connection; the file name (OBS's default
  `2026-11-10 18-11-50`, NVIDIA's `2026.11.10 - 18.11.50`, Game Bar's, read as this PC's local
  time); the file's creation time; else one length before its last write once the page knows
  the length. Accuracy is about ±1 s (the log start is to the second); **−0.5 s / +0.5 s** and
  **Sync here** (scrub the video to the moment the replay shows, save) set the offset exactly.
- **Linking:** the session's **Videos** tab lists files in the recording folders (default: the
  Videos folder and one level of subfolders) whose time covers the session's fights, plus a
  file picker (desktop window) and a path field. Only `.mp4 .mkv .mov .webm .m4v` can be linked,
  and the file route serves a linked file by id only, so the API can't be used to read other
  files. Drag and drop was left out: the page can't learn a dropped file's path.
- **Playback:** one clock drives the map and every video; a video is re-seeked only when it
  drifts more than 0.25 s, and only the main video has sound. A file that doesn't decode (HEVC
  without its extension, or a container the window can't play) shows a remux hint.
- **OBS connection** (`obs.py`, optional, off by default). OBS WebSocket v5, built into OBS 28+,
  at `127.0.0.1` only. Rules:
  - OBS records while the app records: the app's recording start (by hand or with the game)
    starts OBS, unless OBS already records (that recording is used); OBS connecting while the
    app records starts it then. Recording with the game includes loading screens: starting at
    the first fight log would miss that fight, since a log arrives after the fight.
  - The app stops only a recording it started; one started in OBS keeps running.
  - The events have no time stamps: a recording's start is the app's clock when it learns of
    it minus `GetRecordStatus.outputDuration`. The file name comes with the stop
    (`outputPath`) or a split (`RecordFileChanged`), else from the record folder by time.
    A recording joined while paused is marked approximate (its duration leaves the pause out).
  - Left running after the app closed: the next start shows "OBS is still recording from the
    last session" with Stop / Keep; the app never stops it on its own.
  - OBS missing, a wrong password or a refused start only show a status; log recording is never
    affected. The password stays in `config.yaml`: the settings API returns only whether one is
    set, and a save without it keeps it.
- **Validation:** pytest (210, among them replay extraction, cache reuse and rebuild, the
  cleanup rule, the video API with Range requests, file-name times, coverage with an offset, the
  password never returned, and the OBS flows against a fake OBS WebSocket server: auth, start /
  stop with the app, recordings started in OBS left alone, pauses, splits, joining late,
  leftover keep / stop, failures); frontend tests for the sync math and the clock; the zerg and
  GvG analysis of all 142 corpus fights is byte-identical before and after. Run in Chrome
  against a scratch data folder: a timeline click opened the replay 3 s earlier with an MP4 and
  an MKV (H.264) at the expected frame, playback stayed in sync, nudge and Sync here saved the
  right offsets, the EBG image lined up with the roads, and Record / Stop drove a fake OBS
  through the real UI. Not checked: WebView2 itself, a real OBS, HEVC files.

### Review fixes (2026-11-26)

An independent use-case review of plan 18 found four OBS edge cases; all fixed, each with a test
that fails without the fix:

- **A recording started in OBS after OBS restarted went into the old row.** The app kept the
  row it was tracking when the connection dropped; with auto-link off, a recording then started
  by hand in OBS was written into that row, with its old start. The tracked row is now dropped
  on disconnect (a reconnect while OBS still records finds it again by its start), and a
  recording that isn't linked isn't tracked.
- **OBS's spelling of a file path** (forward slashes on Windows) is stored like every other path
  (absolute, this system's separators), so a split file isn't suggested and linked a second time.
- **A row whose length is unknown covers no fight.** Rows closed without a file (the app was
  closed while OBS recorded and the file can't be found) got `end = start`, which still covered
  the fight running at that moment (a stray camera icon).
- **The connection thread survives its reader failing** (a settings save closing the socket
  between two reads could end it until the app restarted). The reader keeps its own socket,
  the loop reconnects after any error, and requests waiting for an answer fail as soon as the
  connection closes instead of after their 5 s timeout.

### Test with a real OBS on Windows (2026-11-26)

`main` run natively on Windows (a WSL app can't reach OBS in WSL's NAT mode, and OBS reports
Windows paths), with a separate data folder, against OBS 32.2.2 (WebSocket 5.7.4) recording
MKV with NVENC AV1:

- OBS not running: "OBS is not reachable" in Settings and the header; nothing else affected.
  No password: "OBS asks for a password". With it: "Connected to OBS 32.2.2".
- **Record** in the app started OBS; the row's start was 0.58 s after the second in OBS's file
  name. **Stop** stopped it and linked `<Videos>\2026-11-26 22-35-49.mkv`; the row spans
  37.76 s, the file is 37.50 s.
- With a test fight starting 10.42 s into that recording, the Replay tab showed the 1080p AV1
  MKV in Chrome at exactly the expected second, and in step while playing.
- **Fixed:** the browser played an old file for a reused video id. The file route sent no cache
  header, and an id comes back after the newest video is unlinked (here: another data folder
  on the same port). The route now sends `Cache-Control: no-cache`, and the page asks for
  `/api/videos/<id>/file?v=<start>`, so a different file is a different address. Tested in the
  API and frontend tests.
- Not covered: the app's own WebView2 window (Chrome was used), pausing, file splitting and the
  leftover notice with the real OBS (covered against the fake server).

Left as is: `tests/test_api.py::test_status_settings_and_fight` sometimes fails when its
WebSocket test session closes (`CancelledError`); it fails the same way without plan 18 (once
in 6 full runs of the previous commit).

## Open items at the time of writing

- The Trends page has its first slice only (results per session). Not built: problems across
  sessions, per-player and per-party trends, squad stats, and filters by mode, date, map or
  commander.
- My play's cause, distance and CC rules are off by default after a calibration on one
  recording player's three raid days; with more players' logs they may hold.
- Replay and video (plan 18), to check on Windows: playback in the app's WebView2 window (Chrome
  plays OBS's AV1 MKV), and the sync error against a visible in-game event. Record / Stop with a
  real OBS works. No map image for Seared Borderlands.
- The installer and exe are not code-signed (SmartScreen warning). Signing needs a paid
  certificate or signing service. The in-app updater checks its own Ed25519 signature instead.
- The updater's Windows end-to-end test (per-user and all-users install, UAC declined, an
  aborted install, Smart App Control) is still to be run by the user. The release signing key
  was created for 0.8.0 (its public key is in `TRUSTED_KEYS`; the private key stays with the
  maintainer, outside the repo).
