# WvW ArcDPS Analyzer — Implementation Plan

> **Status:** approved 2026-11-17, implemented (v0.1, phases 1-5; the Trends page from phase 6 is still open). This is the plan as approved; it is kept as history and not
> updated. Current behavior and later decisions are in [`../DECISIONS.md`](../DECISIONS.md).

## Context
Goal: a local desktop app that takes Guild Wars 2 arcdps WvW (zerg) logs and tells an organized group **why a fight was lost and what to change**. The output is short ranked notes with evidence, not raw stats a human still has to interpret. Alongside the diagnosis, the app shows the **standard WvW log stats** (boon uptime per group and squad, damage, down contribution, strips, cleanses...) that common log parsers show. It has a **recording mode** that automatically picks up and analyzes each log as arcdps writes it after a fight. The diagnosis is fully static (rule-based detectors). An optional local LLM only rewrites the findings into a natural-language debrief. The app must stay light while GW2 is running on the same machine.

Decisions made:
- **Python backend** (FastAPI)
- **Svelte 5 frontend** (Tailwind, ECharts) in a **pywebview** window
- **llama.cpp** `llama-server` subprocess, with Qwen3 4B Q4_K_M, optional
- **Windows-native target**: develop in WSL, package a Windows exe
- **Real logs** will be provided
- **UI is built from the start**, alongside the engine

Environment found: the repo is empty, not yet a git repo. WSL2 has Python 3.14, Node 24 and an RTX 4090; no dotnet and no uv installed.

## Key technical decisions
| Area | Decision | Why |
|---|---|---|
| Log parsing | **GW2 Elite Insights CLI** → JSON (with combat replay and detailed WvW enabled) | Mature, maintained, handles every arcdps format quirk. We never parse `.zevtc` ourselves. |
| EI in dev (WSL) | Call the Windows `GuildWars2EliteInsights-CLI.exe` from WSL through interop | Same binary as production. Needs the .NET runtime on Windows (verified in setup). |
| Python | **uv**, with Python pinned to **3.12** | Wheels for pywebview, numpy and PyInstaller are reliable there. 3.14 is too new for packaging. |
| Storage | **SQLite** (fight index, metrics summary, findings) + gzipped EI JSON cache on disk | No server. Fast fight list. Fights can be re-analyzed when detectors change. |
| Analysis | pandas/numpy for time series; detectors as plain Python classes | Easy to write, test and tune. |
| Config | `config.yaml` (log folder, thresholds per detector, LLM settings) | Thresholds are tuned without code changes. |
| API | FastAPI REST + one WebSocket for "new fight analyzed" events | Live UI updates while raiding. |
| Frontend | SvelteKit with `adapter-static`, Tailwind v4, ECharts, dark theme first | Built once into static files that FastAPI serves. |
| Window | pywebview (WebView2) on Windows; plain browser at `localhost` during WSL dev | No Electron overhead. WSL doesn't need a GUI stack. |
| LLM | `llama-server` subprocess: `-ngl 0 -t 2`, idle priority, started on demand, killed when idle, off by default | Doesn't compete with the game. The static diagnosis works without it. |
| Packaging | PyInstaller onedir: `WvWAnalyzer.exe` + `bin/` (EI CLI, llama-server) + `models/` (downloaded on first run) | Single app for the user. |

## Project layout
```
arcdps-analyzer/
  pyproject.toml, uv.lock, config.example.yaml, README.md
  backend/wvw_analyzer/
    main.py              # entry: start API, watcher, open pywebview window
    config.py            # pydantic settings loaded from config.yaml
    ingest/
      watcher.py         # watchdog on the arcdps.cbtlogs folder, file-complete detection
      queue.py           # single-worker processing queue, per-fight status
      session.py         # recording sessions (start/stop, optional GW2 process autodetect)
      ei_runner.py       # run the EI CLI, settings file, output to cache
      loader.py          # EI JSON → typed Fight model (pydantic), WvW-only filter
    model/fight.py       # Fight, Player, Party, TimeSeries, Event dataclasses
    metrics/             # derived per-second series and aggregates (shared by stats tables + detectors)
      boons.py           # uptime/generation per player/party/squad, per-second series
      offense.py         # damage, DPS, down contribution, downs/kills, CC
      support.py         # cleanses, resurrects, healing/barrier
      defense.py         # damage taken, downs, deaths, dodges/blocks, incoming strips
      aggregate.py       # session-level sums/averages, leaderboards
      strips_cleanses.py # strip/cleanse events over time, own damage spikes
      positioning.py     # distance to tag, stack spread, distance at death
      deaths.py          # down/death timeline, down→death time, rallies
      outcome.py         # kills vs deaths, trades per push, enemy count estimate
    detectors/
      base.py            # Detector interface + Finding schema
      registry.py        # auto-discovery, config-driven thresholds/enable
      stab_gap_deaths.py, strip_timing.py, out_of_position.py,
      early_cascade.py, cleanse_pressure.py, downstate.py,
      sustain_decline.py, comp_audit.py, outnumbered.py, player_outliers.py
    notes/
      ranker.py          # impact score, merge overlapping findings, top N
      templates.py       # cause/fix text templates (editable YAML)
    llm/manager.py       # llama-server lifecycle + summarize()
    store/db.py          # SQLite (sqlite3 + small repository layer)
    api/                 # FastAPI routers: fights, findings, players, settings, ws
  frontend/              # SvelteKit + Tailwind + ECharts
    src/routes/          # /sessions, /sessions/[id], /fights, /fight/[id]/{debrief,overview,boons,offense,support,defense,positioning}, /settings
    src/lib/components/  # RecordButton, QueueStatus, FindingCard, FightTimeline, StatTable (sortable, squad/party/player toggle), Badge...
  tests/
    fixtures/            # trimmed EI JSON from real logs (+ expected findings)
    test_loader.py, test_metrics_*.py, test_detectors_*.py
  scripts/
    setup_tools.py       # download EI CLI + llama-server into bin/
    build_windows.ps1    # npm build + PyInstaller
  notebooks/             # optional: threshold calibration over many fights
```

## Core contracts
**Finding** (detector output, also the LLM input):
```python
class Finding(BaseModel):
    detector: str              # "stab_gap_deaths"
    severity: Literal["critical","major","minor","positive"]
    impact: float              # e.g. deaths explained, weighted toward early deaths
    window: tuple[float,float] | None   # fight seconds, highlighted on the timeline
    subjects: list[str]        # parties/players involved
    evidence: dict             # numbers the templates use (uptime %, counts, distances)
    cause: str                 # rendered from a template
    fix: str                   # rendered from a template
```
**Detector**: `run(fight: Fight, m: Metrics, cfg: DetectorCfg) -> list[Finding]`. It's pure and deterministic, with its own unit tests.

**Ranker**: sort by impact, merge findings whose windows overlap and which share subjects (e.g. a stab gap and an early cascade during the same push), and output the top 3–5 plus up to 2 "what went well" items.

## Recording sessions (auto-analysis while raiding)
- A **Start recording / Stop recording** button in the app header, with a status pill showing a live counter like "Recording · 7 fights".
- While recording, the watcher (watchdog, recursive over `arcdps.cbtlogs`, since arcdps writes into per-boss/WvW subfolders) picks up every **new** `.zevtc`/`.evtc` created after the session started.
- **Detecting that a log is complete:** arcdps writes the file when the fight ends. The watcher waits until the file size is unchanged for ~3s and the file can be opened for exclusive read, then queues it. Older files are ignored unless imported manually.
- **Processing queue:** one worker at a time (so the game isn't disturbed). EI parse → metrics → detectors → SQLite → WebSocket push. Each fight shows status in the UI: queued / parsing / analyzed / failed (with the error and a retry button).
- **Filtering:** only WvW logs are kept. Others are skipped (EI reports the fight as WvW). Fights shorter than N seconds and fights with fewer than N squad members are skipped too; both are configurable, which drops tagging-up skirmishes.
- **Session record:** each recording is stored as a `session` row (start, end, fights), so a raid night is a unit. The session summary page aggregates all its fights.
- **Manual import:** a "drag & drop / pick folder" option also covers older logs. EI runs with low process priority as well.
- Optional: **auto-start recording** when the GW2 process is detected and stop when it closes (off by default).

## Fight statistics (standard log-parser data, in-app)
These are the same stat families as the common WvW report tools (EI WvW report / TopStats-style), computed from EI JSON. They are **shown per player, per party (subgroup) and for the whole squad**, with sortable tables and a toggle between totals, per second, and uptime %:
- **Overview:** duration, map, squad count / allies / estimated enemy count, squad damage & DPS, downs/kills dealt vs downs/deaths taken, K/D.
- **Boons:** uptime (self/group/squad), generation (self/group/off-group/squad) for stability, aegis, protection, resolution, resistance, quickness, alacrity, might (avg stacks), fury, regeneration, vigor, swiftness, superspeed, stealth.
- **Offense:** damage, DPS, power vs condition damage, **damage to downed targets (down contribution)**, downs dealt, kills, CC (breakbar/hard CC), strips (outgoing boons removed), damage per skill (top skills).
- **Support:** cleanses (self/others), strips, resurrects/rally time, healing and barrier output (when the healing addon is present), stab generation.
- **Defense:** damage taken, barrier absorbed, downs, deaths, dodges, blocks, evades, missed/interrupted, conditions taken, boons stripped from us.
- **Positioning:** average distance to the commander and to the stack center, time spent far from the tag.
- **Charts:** squad and party boon uptime over time (stab, resistance...), damage dealt/taken per second, the death/down timeline.
- **Session aggregation:** the same tables summed or averaged over all fights of a recording session, plus "top players" leaderboards per category (top stab, strips, cleanses, down contribution, etc.).

Stats tables and the diagnosis share one metrics layer: detectors read the same numbers shown in the tables, so the notes and the stats always agree.

## UI (milestone scope)
App shell: a sidebar (Sessions, Fights, Settings), a header with the Record button and the queue status, and a dark theme.
1. **Sessions:** list of raid nights → session summary (aggregated stats, leaderboards, wins/losses, the issues that occurred most often across fights).
2. **Fight list:** map, time, duration, squad vs enemy count, K/D, result badge, processing status, top issue chip. Live updates over WebSocket.
3. **Fight page** with tabs:
   - **Debrief:** ranked notes (cause → fix, with evidence), plus a timeline chart with stab per party, deaths/downs, strips, own damage spikes. Clicking a note highlights its time window.
   - **Overview:** squad totals and the key numbers.
   - **Boons:** uptime/generation tables, switchable between squad / party / player.
   - **Offense / Support / Defense:** the stat tables above.
   - **Positioning:** distance stats.
4. **Settings:** log folder, EI path, WvW filters (min duration and squad size), detector thresholds and enable toggles, LLM on/off, threads, idle timeout, auto-record.

## Implementation phases
**Phase 0 — setup**
- `git init`, uv project (Python 3.12), ruff + pytest, SvelteKit scaffold, Tailwind, ECharts.
- `scripts/setup_tools.py` downloads the EI CLI.
- Verify that EI runs from WSL on a sample log, and write the EI settings file (JSON output, combat replay, detailed WvW).

**Phase 1 — ingest, recording, data model, app shell**
- Watcher with completion detection → processing queue → EI runner → loader → SQLite.
- Recording sessions (start/stop), WvW filter, manual import.
- Explore the real logs' JSON to map exact fields (buff IDs for stab, aegis, resistance etc., `support`/`defenses`/`statsAll`/`dpsTargets`, combat replay positions, the commander tag, enemy targets).
- FastAPI endpoints, WebSocket, and the app shell with the Record button, fight list and processing status, working end to end on your logs.

**Phase 2 — fight statistics**
- Metrics layer: boons (uptime and generation per player/party/squad), offense (incl. down contribution), support, defense, positioning.
- Fight page tabs Overview / Boons / Offense / Support / Defense / Positioning, with sortable tables and the boon-uptime timeline charts.
- Verify the numbers against EI's own HTML report for the same log.

**Phase 3 — diagnosis (first 4 detectors) + debrief**
- Detectors: `stab_gap_deaths`, `strip_timing`, `out_of_position`, `early_cascade`.
- Templates, ranker, Debrief tab with FindingCards and the timeline highlight.
- Tests use fixtures cut from your logs.

**Phase 4 — remaining detectors + session summary**
- `cleanse_pressure`, `downstate`, `sustain_decline`, `comp_audit`, `outnumbered`, `player_outliers`.
- Sessions page with aggregated stats, leaderboards and recurring issues.
- Settings page with thresholds editable from the UI.

**Phase 5 — LLM debrief (optional feature)**
- `llm/manager.py` (subprocess, idle priority, 2 threads, `-ngl 0`, kill when idle), model download on first enable.
- A "Write debrief" button. The prompt is told to use only the given findings' numbers.
- Queue mode: auto-run only after N minutes without new logs.

**Phase 6 — packaging + tuning**
- PyInstaller Windows build, pywebview window, first-run wizard (log folder, tools download).
- Calibrate thresholds against your wins and losses; add a trends page (across sessions).

## Risks / open items
- **One player's point of view:** analysis quality depends on whose log it is. The commander's POV works best. Merging multiple POVs is a later feature, not in scope now.
- **Missing heal data:** healing and barrier need the arcdps healing-stats addon. Sustain detectors degrade gracefully and say "no heal data" when it's absent.
- **Field mapping:** buff IDs and field names get verified against real EI output in Phase 1, before detectors are written.
- **EI updates:** pin an EI version in `setup_tools.py`. The loader tolerates unknown or missing fields.

## Verification
- **Unit tests:** `uv run pytest` covers the loader (field mapping on real fixtures), metric series (uptime math against EI's own uptime totals as a cross-check) and each detector (expected findings on chosen fights).
- **End-to-end (dev):** run the backend in WSL pointed at a folder of your logs, open `http://localhost:<port>`, and check that the fight list fills in and the debrief notes and timeline make sense. Sanity-check the notes against your own memory of the fights.
- **Stats accuracy:** for 3–5 of your logs, compare boon uptime, damage, down contribution, strips and cleanses per player and per party with EI's HTML report (dps.report / wvw.report) for the same log. They should match within rounding.
- **Recording:** start recording, then copy a `.zevtc` into the watched folder in chunks to simulate arcdps writing it. Confirm it's picked up only once complete, shows queued → parsing → analyzed in the UI without a refresh, and that files from before the recording started are ignored. Then a real test: record during a raid and check the session summary afterwards.
- **Phase 5:** the LLM summary only contains numbers that appear in the findings JSON (automated check). Watch CPU and priority in Task Manager while GW2 runs.
- **Phase 5:** a clean Windows run of the packaged exe, including the first-run wizard.
