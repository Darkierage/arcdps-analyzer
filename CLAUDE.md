# CLAUDE.md

A local Windows desktop app that analyzes Guild Wars 2 arcdps **WvW** logs: rule-based debriefs
("why lost / what to change"), standard log stats, a recording mode, an optional local LLM
debrief, and a GvG mode. Backend: Python 3.12, FastAPI, SQLite. Frontend: SvelteKit 3 / Svelte 5,
Tailwind 4, ECharts, in a pywebview window. Packaged with PyInstaller and an Inno Setup installer.

## Project docs (keep them current)

- `docs/DECISIONS.md` holds the **current** requirements and the reasons behind them. Read it
  before changing behavior; it wins over everything else.
- `docs/plans/NN-name.md` holds the approved plans, kept as history (see `docs/README.md`).
- `README.md` is user-facing: install, detectors, GvG mode, the LLM benchmark, building.
- When doing larger work:
  - Save the approved plan as the next numbered file in `docs/plans/`, with a status line on
    top.
  - Record the outcome in `docs/DECISIONS.md`: what was decided, why, and how it was validated.
  - Update the plan's status line, noting any deviations, instead of rewriting the plan.
  - Update `README.md` when user-visible behavior changes.
- Docs are public: no personal paths, account names or emails. Write
  `%USERPROFILE%\...`, not a real user folder.

## Commands

```bash
uv sync                                   # Python deps (uv may live at ~/.local/bin/uv)
uv run pytest                             # all tests; test_corpus runs only if data/dev_corpus exists
uv run ruff check backend tests scripts   # lint (line length 100)
cd frontend && npm run check              # svelte-check / TypeScript
cd frontend && npm run build              # the backend serves frontend/build
uv run wvw-analyzer --no-window           # http://127.0.0.1:8765 (dev data in ./data)
uv run python scripts/setup_tools.py      # Elite Insights CLI -> ./bin (--llm for llama + model)
```

## Environment

- **Where things run.** Development happens in WSL. The game, the arcdps logs and the .NET
  runtime are on Windows. The Windows Elite Insights exe runs from WSL through interop.
- **Windows builds.** Run `scripts/build_windows.ps1` on Windows from a copy of the repo:
  - Windows Node is too old for SvelteKit 3, so build `frontend/build` in WSL first, copy it
    over, and pass `-SkipFrontend`.
  - The script fails with a hint if Inno Setup is missing.
  - Installing tools on the user's Windows needs their OK.
- **Versions.** The version lives in `backend/wvw_analyzer/__init__.py`, `pyproject.toml` and
  `uv.lock`; bump all three. Releases are tagged `vX.Y.Z` and the installer
  `dist/WvWAnalyzer-Setup-X.Y.Z.exe` is attached to a GitHub release (`gh`).

## Architecture

```
.zevtc -> Elite Insights CLI -> EI JSON -> metrics (columns, timeline, summary)
       -> detectors -> Finding -> ranker -> notes (templates.yaml) -> SQLite -> API/WebSocket -> UI
```

- **Folders:**
  - `backend/wvw_analyzer/ingest`: recorder (polling), processor queue, EI runner, loader.
  - `metrics`: `timeline.py` (per-second series, engagement window, GvG rounds), `summary.py`
    (counts, result), `rounds.py`, `aggregate.py` (sessions).
  - `detectors`: one class per rule; `registry.py` lists them.
- **Worker processes.** Each fight is analyzed in a short-lived spawn worker
  (`analysis_job`), so the large EI JSON is released afterwards.
- **Fight mode.** Every fight row stores its own `mode` (`zerg`/`gvg`). `Settings.fight_mode` is
  only the default for newly added fights.

## Rules for changes

- **Facts come from code, never from the LLM.** Detectors produce every number. The LLM
  (`llm/prompts.py`, default `v8_header`) only phrases bullets from code-written facts; the
  result line and framing are code-written too. Re-check prompt changes with
  `scripts/llm_bench.py`, using Claude-written references and grades.
- **Detectors** must be pure and deterministic. Their text comes from
  `notes/templates.yaml`, and every placeholder must exist in the evidence (a missing one
  renders as `?`). Thresholds live in `defaults` and can be overridden in Settings.
- **Bump `ANALYZER_VERSION`** (`analysis.py`) whenever analysis output changes. Stored fights
  from an older version are re-analyzed on startup.
- **Keep the zerg path stable when adding modes or features.** Snapshot the analysis of
  `data/dev_corpus` before and after, and compare. GvG-only logic must not change zerg results.
- **Local-only API.** It only accepts a localhost Host header. State-changing requests and the
  WebSocket need a localhost Origin or none. Keep it that way.

## Frontend conventions

- `#lib/...` imports need explicit extensions: `import { api } from '#lib/api.ts'`.
- Svelte 5 runes (`$state`, `$derived`, `$effect`). Use `$state.snapshot`, not
  `structuredClone`, on reactive objects.
- Every page uses the `.page` container (same width everywhere). Big tables scroll inside a
  bounded card with a sticky header, first column and totals row.
- Types for API responses live in `frontend/src/lib/api.ts`. Keep them in sync with the backend.

## Data and privacy

- **Never modify or delete original arcdps logs.** Imports from outside the log folder are
  copied to `uploads/`.
- **File cleanup** only touches files inside the folder next to the database. Tests must use
  temp dirs, never the real data dir.
- **Never commit** logs, EI JSON, `data/` or player/account names. `data/dev_corpus` (real
  fights used by `tests/test_corpus.py` and the calibration and benchmark scripts) is
  git-ignored for that reason. Use `tests/factory.py` for synthetic fights in tests.
- **Commits and PRs:** no Claude attribution lines (no `Co-Authored-By: Claude`, no
  "Generated with Claude Code").
