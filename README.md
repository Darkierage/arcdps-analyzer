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
- **Sessions.** One per raid night, with aggregated stats, leaderboards and recurring problems.
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

## Building the app and installer

Requires uv, Node.js 22.17+ (or `-SkipFrontend` with a prebuilt `frontend/build`) and Inno Setup 6
(`winget install JRSoftware.InnoSetup`). In PowerShell, from the repo root:

```powershell
./scripts/build_windows.ps1                # -> dist\WvWAnalyzer-Setup-<version>.exe
./scripts/build_windows.ps1 -NoInstaller   # only dist\WvWAnalyzer\ (portable folder)
```

The build does the following:
- downloads the pinned Elite Insights, .NET runtime and WebView2 bootstrapper, verifying their
  checksums or signature;
- builds the app with PyInstaller;
- compiles `packaging/installer.iss`.

The version comes from `backend/wvw_analyzer/__init__.py`.

## Layout

- `backend/wvw_analyzer/ingest`: recorder (folder watch), processor queue, EI runner, loader
- `backend/wvw_analyzer/metrics`: stat columns, per-second timeline, summary, session aggregation
- `backend/wvw_analyzer/detectors`: rules producing findings
- `backend/wvw_analyzer/notes`: ranking, merging and templates
- `backend/wvw_analyzer/llm`: llama-server lifecycle and debrief prompt
- `backend/wvw_analyzer/api`: FastAPI REST and WebSocket; serves the built UI
- `frontend/`: SvelteKit + Tailwind + ECharts
- `scripts/`: tool setup, calibration, Windows build
- `packaging/`: PyInstaller spec, Inno Setup script, icon
- `docs/`: decisions (`DECISIONS.md`) and the approved plans (`plans/`)
