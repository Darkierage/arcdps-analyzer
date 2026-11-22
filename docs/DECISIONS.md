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
- **Auto-show.** The window opens, once MumbleLink says the player is out of combat, when
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
  window closes, before the LLM server and uvicorn shutdown, which can take ~10 s.
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

## Open items at the time of writing

- The Trends page has its first slice only (results per session). Not built: problems across
  sessions, per-player and per-party trends, squad stats, and filters by mode, date, map or
  commander.
- The installer and exe are not code-signed (SmartScreen warning). Signing needs a paid
  certificate or signing service.
