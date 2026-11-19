# WvW Analyzer: strength and problem drill-down plan

> **Status:** approved 2026-11-20, implemented (unreleased). Deviations: focus entries can
> also carry `sort: "asc"` (stability uptime shows the lowest first); links carry
> `from=session` so the fight page's back link returns to the session. This is the plan as
> approved; it is kept as history and not updated. Current behavior and later decisions are in
> [`../DECISIONS.md`](../DECISIONS.md).

## Context

The session Summary lists **Strengths** ("Won the strip war") and **Recurring problems** with
only a fight count. There is no way to see which fights earned a strength, what the numbers
were, or which stat drove it.

The data is mostly there already: `aggregate_session` keeps the fight ids per entry
(`fights: number[]`), and every stored finding has its full `evidence` and a code-written
one-line `short` fact. The UI ignores the ids and the aggregate drops the numbers (it even
strips the bracketed part of the title). The fight page has no deep links: the active tab is
local state.

## Design

### 1. Backend: per-fight occurrences (`metrics/aggregate.py`)
- Each Strength and Recurring problem gets `occurrences: [{fightId, start, map, result,
  severity, impact, short}]`, strongest (highest impact) first, ties by time.
- `short` is the template's one-line fact, written by code (no LLM).
- `fights: number[]` stays for compatibility. The change is additive to the session API only;
  stored analysis output does not change, so `ANALYZER_VERSION` is not bumped.

### 2. Backend: detector focus metadata
- `Detector.focus: ClassVar[dict[str, dict]]`: template key -> `{tab, column}` naming the
  fight-page stat tab and column that best shows the evidence (e.g. `strip_balance_good` ->
  offense / `strips`). Static metadata, so detectors stay pure.
- The fight API adds `focus` to each finding when it serves the notes (looked up by key), so
  stored analyses do not change, old fights get the link too and no re-analysis is needed.
  Findings without a useful column (comp, outnumbered, player outliers) get none.

### 3. Session page
- Strength and Recurring problem rows become buttons that expand an inline list of the
  contributing fights: time, map, result badge, the `short` fact. Each line links to
  `/fights/<id>?tab=debrief&finding=<key>`.

### 4. Fight page deep links
- Read `?tab=` and `?finding=` on load; keep the URL in sync when the tab changes
  (`replaceState`, so the back button returns to the session).
- `finding=<key>` opens the Debrief tab, expands "More" if the finding is there, scrolls the
  card into view and marks it active; a finding with a window also sets the timeline
  highlight.
- Finding cards with a `focus` get a "See stats" link that switches to that tab, sorts the
  table by that column (descending, or ascending when lower is better) and tints the column.

### 5. Validation and docs
- Unit test for occurrences and focus; API test still passes.
- `ruff`, `pytest`, `npm run check`, `npm run build`; compare `data/dev_corpus` analysis
  before/after (only the new `focus` field may differ).
- `DECISIONS.md` entry, README session section, docs index.
