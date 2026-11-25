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
  4. [`04-strength-drilldown.md`](plans/04-strength-drilldown.md) — fights behind session
     strengths and problems, fight-page deep links and "See stats" (2026-11-20)
  5. [`05-ingame-overlay.md`](plans/05-ingame-overlay.md) — in-game overlay as a Nexus addon
     (2026-11-20)
  6. [`06-review-fixes.md`](plans/06-review-fixes.md) — whole-app review fixes (2026-11-21)
  7. [`07-party-boon-timeline.md`](plans/07-party-boon-timeline.md) — boons over time per party
     (2026-11-21)
  8. [`08-marker-tooltips.md`](plans/08-marker-tooltips.md) — who went down / died on chart
     markers (2026-11-21)
  9. [`09-crash-reporting.md`](plans/09-crash-reporting.md) — crash and error reporting,
     per-run logs, the window freezing on start (2026-11-21)
  10. [`10-crash-reporting-review-fixes.md`](plans/10-crash-reporting-review-fixes.md) — crash
      reporting review fixes (2026-11-21)
  11. [`11-crash-reporting-heartbeat.md`](plans/11-crash-reporting-heartbeat.md) — run heartbeat
      and second review fixes (2026-11-21)
  12. [`12-session-stats.md`](plans/12-session-stats.md) — session stat tabs, session trend and
      per-player charts (2026-11-21)
  13. [`13-trends-first-slice.md`](plans/13-trends-first-slice.md) - Trends across sessions,
      first slice: results per session (2026-11-22)
  14. [`14-player-improvement.md`](plans/14-player-improvement.md) — personal improvement
      ("My play"): per-player recap and profile from the logs (2026-11-25)

Each plan starts with a status line saying whether it was implemented and where the
implementation deviated. New larger features get the next numbered plan once it is approved,
and their outcome is recorded in `DECISIONS.md`.
