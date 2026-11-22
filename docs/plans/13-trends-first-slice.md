# WvW Analyzer: Trends across sessions, first slice plan

> **Status:** approved 2026-11-22, implemented (unreleased). Deviations: the table lists
> sessions newest first (the chart reads oldest to newest); K/D always shows two decimals;
> skirmishes show in the table as "+nS" next to W / E / L; the endpoint also returns each
> session's squad and enemy deaths; the chart tooltip names the top problem too. The browser
> check ran without screenshots (they timed out), through the page's DOM, tooltip and canvas
> state; the empty and one-session states were checked with a stubbed API response. Review
> fix (2026-11-22): the Trends query and the session Summary's query now share one fight order
> (`FIGHT_ORDER` in `store/db.py`); before, a tie between two problems could name a different
> top problem on the two pages when a fight had no start time.

## Context

The original plan (01, phase 6) asked for "a trends page (across sessions)" and never said
more. Everything else compares fights inside one session; nothing shows whether raids get
better or worse from one session to the next. `DECISIONS.md` listed the page as an open item.

This plan builds the smallest useful slice: results per session. The rest is listed under
"Not in this slice".

What exists and is reused:
- `aggregate_session(items, detail=False)` already builds a session's results, totals and
  recurring problems without player rows (the overlay uses it).
- `SessionTrend.svelte` and `trendTooltip.ts` show the pattern for an ECharts line chart with
  an escaped tooltip and a click that opens what the point stands for.

## Design

- **Backend.** `GET /api/trends` returns `{"sessions": [...]}`: one row per session with at
  least one analyzed fight, oldest first by the session's first fight.
  - `Database.trend_sessions()` reads every analyzed fight's summary and notes in one query and
    groups them by session, in the same fight order as the session Summary's query.
  - `session_trend()` in `metrics/aggregate.py` runs `aggregate_session(detail=False)` per
    session and takes every number from it, so this page and the session's own Summary agree
    (GvG deaths after a call-off are left out in both).
  - Per session: fights, results (win / loss / even / skirmish), win rate, K/D, squad deaths
    per fight, squad and enemy deaths, and the top recurring problem (key, title, count,
    losses, severity).
- **Win rate** = wins / (wins + evens + losses), in percent. Skirmishes are left out, as on
  the Sessions cards. A session of skirmishes only has no win rate (`null`, shown as a dash).
- **GvG and zerg fights count together**, one result per fight, as on the Sessions page.
- **Frontend.** A **Trends** entry in the navigation and a `/trends` page:
  - a line chart, one point per session, with a stat picker (Win rate, K/D, Squad deaths per
    fight); the picked stat is kept in `?stat=`;
  - a table, one row per session: name and date, fights, results, the three stats and the top
    recurring problem;
  - a click on a point or a row opens the session;
  - no sessions: an empty state; one session: its point and a note that a trend needs two;
  - the page reloads on fight and recording events, like the Sessions page.
- **Escaping.** A session's name is typed by the user or taken from a folder on import. The
  chart tooltip is built by `sessionTooltipHtml` in `trends.ts`, which escapes everything from
  data; the table uses Svelte's text interpolation.
- **No analysis change.** No detector, metric or stored field changes; `ANALYZER_VERSION`
  stays.

## Not in this slice

- Problems across sessions (which problem keeps coming back over several raids).
- Per-player and per-party trends across sessions; squad stats (damage, boons, strips).
- Filters by mode, date range, map or commander.
- Caching: the endpoint reads all analyzed fights' summaries and notes on each call.

## Validation

- `tests/test_trends.py`: rows and their order, win rate without skirmishes, a skirmish-only
  session, sessions without analyzed fights left out, GvG late deaths, the top problem, and
  the API against each session's own summary.
- `frontend/tests/helpers.test.ts`: the tooltip escapes the session name and the problem
  title; `?stat=` falls back to the first stat.
- Browser check on a throwaway instance with six synthetic sessions (one with a script-like
  name, one of skirmishes only, two on one day).
