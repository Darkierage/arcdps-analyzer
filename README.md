# WvW Analyzer

A local desktop app for Guild Wars 2 **WvW (zerg) fights**. It turns arcdps logs into:

- **A debrief.** Ranked notes on *why the fight was lost* and *what to change*, each with
  evidence and the moment on the fight timeline. Examples: stability gaps during the enemy bomb,
  losing the strip war, enemy strip bombs, lost openings, enemy downs escaping, downed allies not
  picked up, condition pressure, sustain running out, parties without support, players caught
  away from the tag.
- **Standard log stats.** Boon uptime and generation, damage, down contribution, damage to downed
  enemies, strips, cleanses, healing, defense and positioning. Each is shown per player, per party
  and for the squad.
- **Boons over time, per party or player.** The Boons tab charts every boon second by second for
  the squad or one party (share of its players who had it, plus might and stability stacks), with
  that party's downs and deaths. Pick a **player** to see their own boons as lanes, filled while
  they had each boon (might and stability darker with more stacks), and when they were downed or
  dead. On the Debrief tab the fight timeline can show one party, every party's stability, or
  one player (health, boons and conditions, damage dealt and taken, healing, distance to the tag
  and to the squad). Click a name in any stat table to open that player's boons. Hover a down or
  death marker to see who it was (profession, party, whether they got up, stability before the
  down, distance to the tag).
- **Sessions.** One per raid night, with recurring problems, strengths and leaderboards. Click a
  problem or strength to see the fights behind it, each with its numbers; a fight opens its
  debrief at that note. **See stats** on a note opens the stat table behind it, sorted by that
  column (for example strips for "Won the strip war").
  - **Session stats.** The same tabs as a fight (Overview, Boons, Offense, Support, Defense,
    Positioning) for the whole session, per player, per party and for the squad. Counts and
    amounts are totals (or **per minute** in fights); uptime, generation, stacks and distances
    are averages weighted by time in each fight; DPS is damage / time in fights. **Min. time in
    fights** hides players who were only there briefly.
  - **Session trend.** One stat fight by fight (stability uptime and given, strips, cleanses,
    boons lost, damage, downs, deaths, distance to tag) for the squad, a party or a player, with
    the squad's average player as a reference line. Click a fight to open it (for a player: at
    their boons). Click a name in a session stat table to see that player's trend.
- **Trends.** One point per session, oldest to newest: win rate, K/D or squad deaths per
  fight, with a table of every session's results and its top recurring problem. Click a
  session to open it.
- **My play.** Hints for one player (you, or anyone in your logs): what to work on and what to
  keep doing, over the last session, the last 5 sessions, 30 days or all fights, per spec if you
  like. Your survival is compared with the rest of the squad in the same fights, your output
  and cast time with players of the same spec *and the same job* (strips, damage, cleanses,
  healing, stability) in the same fights. Each hint shows its sample next to the squad's, a
  trend, and example fights that open on your charts at the moment. When nothing stands out it
  says so, with your numbers next to your peers' and the squad's. A fight's and a session's
  **You** tab show the same for that fight or session: each of your downs with the hint that
  matches it, what hit you and your top skills. See [My play](#my-play).
- **An in-game overlay (optional).** A small window inside Guild Wars 2 with the latest fight's
  notes and the session summary, so you don't have to alt-tab. It's a Raidcore Nexus addon,
  installed from Settings.
- **An optional local LLM debrief.** Qwen3 via llama.cpp rewrites the findings into a
  paste-ready text. Everything else is fully static and needs no LLM.

## How it works

```
arcdps .zevtc ──► Elite Insights CLI ──► EI JSON ──► metrics ──► detectors ──► ranked notes
     ▲ recorder watches the log folder                     │                      │
     └──────────── live updates over WebSocket ◄───────────┴── SQLite ◄───────────┘
```

- **Recording:** press **Start recording** before the raid. Every log arcdps finishes writing is
  picked up once its size has been stable for 3 seconds. Logs are parsed one at a time at low
  priority and appear in the UI live. **Import logs** handles logs you already have.
- **Filters:** non-WvW logs and tiny fights (under 20 s, under 5 enemies) are kept as *skipped*.
- **Who was in the fight:** squad members elsewhere on the map (scouts, players running back) are
  excluded from fight analysis. So are the first 3 seconds of boon data, because arcdps can't see
  boons applied before the log started.
- **Enemy boons aren't in WvW logs.** Strip analysis therefore compares strips out vs boons lost,
  and detects squad-wide boon wipes followed by downs.

## GvG mode

In a **GvG**, two guilds fight agreed rounds at an agreed spot. When one commander calls a round
off, both sides stop, walk away and rez everyone, downed enemies included, then regroup for the
next round. Analyzed as a normal zerg fight, that looks like mistakes: "enemy downs escaped",
"downed allies not picked up", a "skirmish" result.

In GvG mode:
- **Call-off:** a round ends at its last second of fighting. Kills up to 3 s after that still
  count.
- **Not counted:** downs still open at the call-off and kills after it are not held against
  either side. The fight page shows them as "left at call-off", and the chart shades what
  follows each call-off and draws left downs hollow.
- **Rounds:** a lull of 25 s or more inside one log starts a new round. Each round has its own
  opening and sustain checks.
- **Result:** each round is won or lost on players taken out (kills plus downs left at the
  call-off). The fight result is the round score. There are no "skirmishes" in GvG.
- **Where to switch it:**
  - Settings → *Fight type* sets the default for new fights.
  - The **GvG** switch in the header changes the same setting, so it can be flipped on before a
    GvG block and off after it.
  - Each fight stores its own mode. **Analyze as GvG / zerg** on a fight or a session page
    re-analyzes it.

The round gap and the grace time can be changed in Settings. Both are first guesses, set without
real GvG logs.

## In-game overlay (Nexus addon)

The overlay shows the analyzer's results in game: the latest fight (result line, ranked notes
with their fixes, what went well, the LLM debrief if one was written), older fights of the
session with **<** / **>**, the session summary (record, kills and deaths, recurring problems,
strengths) and a **Start / Stop recording** button.

- **Requirements:** [Raidcore Nexus](https://raidcore.gg/Nexus) (it also loads arcdps), and
  WvW Analyzer 0.5.0 or newer running on the same PC. Players using arcdps without Nexus aren't
  supported yet.
- **Install:** Settings → *In-game overlay* → **Install**, with the game closed. The Guild Wars 2
  folder is found automatically for the standard and Steam default folders (otherwise enter
  it). The app copies `WvWAnalyzer.dll` into `<Guild Wars 2>\addons`
  and nothing else. **Remove** deletes that DLL and the addon's settings folder. After an app
  upgrade the addon is updated on the next start while the game is closed, or with **Update**.
- **In game:** the Quick Access icon or **ALT+SHIFT+W** (rebindable in Nexus) toggles the
  window. Options in Nexus → Addons → WvW Analyzer: open the window when a new fight has been
  analyzed (only once you're out of combat), hide it in combat, background opacity.
- **Timing:** a fight shows up once the app has analyzed its log, usually within half a minute
  of the fight ending. The window follows the current session; while you browse older fights,
  **Latest** goes back to the newest one.
- **What it does and doesn't do.** It only draws a window through Nexus. Everything in it comes
  from the WvW Analyzer app over `127.0.0.1`, which works from finished arcdps logs like Elite
  Insights does. The only game state it reads is MumbleLink's "in combat" flag (ArenaNet's
  official interface, provided by Nexus), to hold back the auto-show. It doesn't read game
  memory, send keys or chat, or connect anywhere else.
- **At your own risk.** ArenaNet doesn't approve any third-party add-on, including arcdps and
  Nexus. The overlay adds nothing beyond what that setup already does, but using it is your
  decision.

## Detectors

| Detector | Finds |
|---|---|
| `stab_gap_deaths` | Down bursts that hit parties with low stability coverage |
| `boon_wipe` | Squad boons collapsing within seconds, followed by downs |
| `strip_balance` | Boons lost vs strips dealt; too few strippers |
| `early_cascade` | Several downs early, before the enemy lost anyone |
| `downstate` | Allied downs not rallied; enemy downs not converted to kills |
| `cleanse_pressure` | Many conditions on the squad; downs while carrying many conditions |
| `sustain_decline` | Healing + barrier vs damage taken dropping in the second half |
| `out_of_position` | Downs far from the tag or the stack |
| `comp_audit` | Parties without stability, cleanses or healing; players in tiny parties |
| `outnumbered` | Enemy count vs squad + nearby allies |
| `player_outliers` | Players far below others of the same profession in that profession's main output |

Thresholds can be edited in **Settings**. Use **Save & re-analyze all** to apply them to every
fight. To change the note wording, copy `backend/wvw_analyzer/notes/templates.yaml` to
`<data dir>/templates.yaml` and edit it.

**Calibrate against your own fights:** `scripts/calibrate.py` prints how often each detector fires
in won vs lost fights, plus metric medians per outcome. On the first 93 fights it was tuned with,
`strip_balance` fired in 71% of losses vs 6% of wins, and `early_cascade` in 46% vs 6%.

## My play

Personal hints are built only from your logs, with no outside data (no builds, no benchmarks):

- **When a log is analyzed**, every squad member gets a set of facts stored with the fight:
  their downs (stability, the party's stability, distance to the tag, other squad downs within
  4 s, health 3 s before, the death recap's skills), time dead, cast time without
  auto-attacks, cancelled casts, dodges, food and utility, top skills dealt and taken, their
  job in that fight (strongest output against the squad) and, per stat, the median of the other
  players with the same spec and job and of the squad. Older fights are re-analyzed once.
- **When the page opens**, the rules run over those facts, so changing a rule in Settings needs
  no re-analysis:

  | Rule | Fires when | On by default |
  |---|---|---|
  | `me_deaths` | your downs per minute are well above the rest of the squad's in the same fights (at least 1.5x and unlikely by chance), overall or on one spec | yes |
  | `me_low_output` | on a spec, your main job's output is below 65% of other players with that spec and job (median over fights with 2+ of them); above 140% is a strength | yes |
  | `me_low_activity` | on a spec, your cast time without auto-attacks is below 75% of those players'; above 135% is a strength | yes |
  | `me_no_food` | a quarter or more of your fights without food or a utility | yes |
  | `me_down_no_stab`, `me_down_far`, `me_caught_alone`, `me_first_down` | a cause of your downs (no stability while your party had it, far from the tag, picked off alone, among the first down) is well above the squad's share | no |
  | `me_far_from_tag`, `me_cc_taken` | much farther from the tag than the squad in most fights; CC'd far more than the squad with less stability than your party | no |

  The rules that are off by default fired for almost nobody, or no more often than chance, on
  the fights they were calibrated on. The down-rate hint still names a cause when one stands
  out, and **Your downs** shows how your downs split next to the squad's.
- **Same fight twice:** when two logs cover the same fight (a friend's log next to yours), the
  one the player recorded counts. A player split by Elite Insights into several rows in one
  fight counts once. Fights you led count for survival and food only (a commander has no
  distance to the tag and no peers).
- **Calibrate against your own logs:** `scripts/calibrate_personal.py` runs every rule over
  every player in a folder of EI JSON and prints how often each fires, how often a player's job
  changes between fights on one spec, and the recording player's profile.

## LLM debrief tuning

`scripts/llm_bench.py` compares prompt variants (`backend/wvw_analyzer/llm/prompts.py`) for the local
model:

- **Automatic checks:** ranking kept, fixes carried over, no invented numbers or names, no padding,
  format.
- **Reference comparison:** similarity to reference debriefs written by Claude (Opus 5.5).
- **Graded reads:** Claude's grades of every output, stored in `data/llm_bench/judgments-*.yaml`.

```bash
uv run python scripts/llm_bench.py prepare            # pick 30 fights from data/dev_corpus (--mode gvg)
uv run python scripts/llm_bench.py run --variants v8_header --temps 0.1 [--server PATH --ngl 99]
uv run python scripts/llm_bench.py sheet <results.jsonl>   # side-by-side sheet for grading
uv run python scripts/llm_bench.py report <results.jsonl ...>
```

Current default: `v8_header` at temperature 0.1. Code writes the result line, the framing (for
example "Clean win, only small things to tidy up") and a one-line fact and fix per problem. The model
only turns these into chat bullets, which removed the paraphrasing errors smaller prompts made
("downed" turned into "died", numbers mixed up).

| Prompt | Claude's grade (out of 10) |
|---|---|
| `v8_header` | 10.0 |
| `v7_short` | 9.6 |
| `v6_framed` | 8.4 |
| `v5_anchored` | 7.3 |
| `v1_json` (original) | lowest automatic score |

## Development (WSL / Linux)

```bash
uv sync                                        # Python 3.12 + deps
uv run python scripts/setup_tools.py           # Elite Insights CLI -> ./bin (add --llm for llama + model)
cd frontend && npm install && npm run build    # UI (or `npm run dev` for hot reload on :5173)
uv run wvw-analyzer --no-window                # http://127.0.0.1:8765
uv run pytest                                  # tests (+ corpus test if data/dev_corpus has EI JSON)
```

The in-game overlay addon (`addon/`, Rust) is cross-compiled from WSL to a Windows DLL with
[cargo-xwin](https://github.com/rust-cross/cargo-xwin). It needs rustup with the
`x86_64-pc-windows-msvc` target, `cargo install cargo-xwin`, and clang-cl + lld-link (LLVM 18+;
set `LLVM_BIN` if they aren't on `PATH`):

```bash
scripts/build_addon.sh                         # -> bin/addon/WvWAnalyzer.dll
cd addon && cargo test && cargo clippy         # model, client and settings tests run on Linux
```

From WSL, the Windows `GuildWars2EliteInsights-CLI.exe` runs through interop. It needs the
.NET 10 runtime on Windows. Dev data (config, DB, EI cache) lives in `./data`.

## Install (Windows 10/11)

Run `WvWAnalyzer-Setup-<version>.exe`.

- **No admin rights needed.** It installs for your user only, in
  `%LOCALAPPDATA%\Programs\WvW Analyzer`, and creates a Start menu entry (a desktop shortcut is
  optional).
- **Nothing else to install.** The log parser (Elite Insights) and its private .NET runtime are
  included and nothing is installed system-wide. The installer only adds Microsoft WebView2 on
  the rare Windows install that lacks it.
- **SmartScreen warning:** the installer isn't code-signed, so Windows says "Windows protected
  your PC". Click **More info → Run anyway**.
- **First launch** shows a short setup screen: the arcdps log folder (usually found
  automatically), a parser check, and an optional download of the AI debrief model.
- **Upgrading:** run the newer setup. It closes the running app and keeps all your data.
- **Uninstalling** (Windows *Apps & features*) asks whether to also delete your analyzed fights
  and settings in `%LOCALAPPDATA%\WvWAnalyzer`. The default is to keep them. Your arcdps logs are
  never touched.

## Troubleshooting

If something goes wrong, open **Settings > Troubleshooting** and click **Copy diagnostics**,
then paste the result into a message to whoever helps you. It holds the app version, the setup
checks, recent errors and crashes, and the end of the app log, with your Windows user name and
account names removed. Nothing is sent anywhere automatically. The same report is saved as
`diagnostics.txt` in `%LOCALAPPDATA%\WvWAnalyzer` (**Open app folder**). Each app start
writes its own log in the `logs` folder there, so the log of a run that crashed is still there
after a restart. Logs are kept for 14 days (at most 30 runs and 100 MB).

When the app crashed or closed unexpectedly, a banner offers the same button on the next start.

## Building the app and installer

Requires uv, Node.js 22.17+ (or `-SkipFrontend` with a prebuilt `frontend/build`) and Inno Setup 6
(`winget install JRSoftware.InnoSetup`). The overlay addon is built in WSL first
(`scripts/build_addon.sh`); copy `bin/addon/` along with the repo. In PowerShell, from the repo
root:

```powershell
./scripts/build_windows.ps1                # -> dist\WvWAnalyzer-Setup-<version>.exe
./scripts/build_windows.ps1 -NoInstaller   # only dist\WvWAnalyzer\ (portable folder)
```

The build does the following:
- downloads the pinned Elite Insights, .NET runtime and WebView2 bootstrapper, verifying their
  checksums or signature;
- builds the app with PyInstaller and bundles `bin\addon\WvWAnalyzer.dll`;
- compiles `packaging/installer.iss`.

The version comes from `backend/wvw_analyzer/__init__.py`.

## Layout

- `backend/wvw_analyzer/ingest`: recorder (folder watch), processor queue, EI runner, loader
- `backend/wvw_analyzer/metrics`: stat columns, per-second timeline, summary, session aggregation
- `backend/wvw_analyzer/detectors`: rules producing findings
- `backend/wvw_analyzer/coach`: personal rules and the review served to My play
- `backend/wvw_analyzer/notes`: ranking, merging and templates
- `backend/wvw_analyzer/llm`: llama-server lifecycle and debrief prompt
- `backend/wvw_analyzer/api`: FastAPI REST and WebSocket; serves the built UI
- `backend/wvw_analyzer/addon_install.py`: install, update and remove the in-game overlay
- `addon/`: the in-game overlay, a Rust Nexus addon (nexus-rs)
- `frontend/`: SvelteKit + Tailwind + ECharts
- `scripts/`: tool setup, calibration, addon and Windows builds
- `packaging/`: PyInstaller spec, Inno Setup script, icon
- `docs/`: decisions (`DECISIONS.md`) and the approved plans (`plans/`)
