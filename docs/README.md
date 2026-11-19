# Project docs

- [`DECISIONS.md`](DECISIONS.md) — **current** requirements and the decisions behind them
  (review fixes, installer, GvG mode, LLM prompt choice, accepted limitations). Where anything
  else disagrees, this file wins.
- [`plans/`](plans/) — the plans as they were approved before each larger piece of work, kept
  as history:
  1. [`01-implementation.md`](plans/01-implementation.md) — the original app: parsing,
     metrics, detectors, recording, UI, optional LLM (2026-11-17)
  2. [`02-windows-installer.md`](plans/02-windows-installer.md) — Inno Setup installer,
     private .NET runtime, first-run setup (2026-11-18)
  3. [`03-gvg-mode.md`](plans/03-gvg-mode.md) — GvG rounds, call-offs and per-fight mode
     (2026-11-19)

Each plan starts with a status line saying whether it was implemented and where the
implementation deviated. New larger features get the next numbered plan once it is approved,
and their outcome is recorded in `DECISIONS.md`.
