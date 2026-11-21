# WvW Analyzer: who went down / died on timeline markers plan

> **Status:** approved 2026-11-21, released in 0.5.2. Deviations: the time used for the
> lookup (and the tooltip header) comes from the mouse position (`trackPointer`), because over
> the marker lane ECharts hands the axis tooltip the nearest marker's data, which can be many
> seconds away; no separate hover emphasis was needed (ECharts already enlarges a hovered
> marker); the helpers ended up as `eventsSection`, `trackPointer` and `secondsPerPixels` (not
> `eventsNear`/`eventLines`). A review then added the fixes listed in DECISIONS.

## Context

Tester feedback on the Boons tab's "Boons over time" chart (and the same applies to the
Debrief's fight timeline): the down ▲ and death ✕ markers in the lane under the chart show
*when* something happened but not *who*. They want to hover a marker and see who went down or
died.

What exists:
- Both charts (`frontend/src/lib/components/FightTimeline.svelte`,
  `BoonTimeline.svelte`) use one ECharts `tooltip` with `trigger: 'axis'`; its formatter
  skips scatter series, so markers never show anything.
- The data is already in the payload: each down in `timeline.squadDowns` has `player`,
  `profession`, `group`, `died`, `stab` (stacks just before), `dist_tag`, `left` (GvG);
  each death in `squadDeaths` has `t`, `player`, `group`. Enemy downs/deaths are anonymous
  times only.
- ECharts can't mix an axis tooltip and per-item tooltips in one chart (series tooltips only
  work with `trigger: 'item'`), and switching to `item` would lose the boon/damage readout.

## Design

**Keep the axis tooltip and add the events under the pointer to it.** When the pointer is
within a few pixels of one or more markers (in any of the chart's grids, so hovering the
marker itself works), the tooltip gets an extra section listing them:

```
0:09
Stability 100%  …                (as today)
─────────────
▲ Name (Firebrand) · Party 4 · down — died · 0 stab · 1200 from tag
✕ Name (Scourge) · Party 4 · died
Enemy: 2 downs, 1 death
```

- **Tolerance in pixels, not seconds:** the window is ±8 px converted to seconds with
  `chart.convertFromPixel` at the current zoom, so it works zoomed in or out. Events at the
  same moment are all listed (sorted by time); more than 8 → "+N more".
- **Down line:** name (profession color via `profColor` from `#lib/format.ts`), party,
  "died" or "got up", stability stacks before the down, distance to tag when known, and
  "left at call-off" for GvG. **Death line:** name, profession, party. Deaths carry no
  profession in the payload, so it is looked up from the fight's players (a new
  `professions` prop: name → profession, built from `stats.players` on the fight page) —
  no backend or analysis change, so no `ANALYZER_VERSION` bump and no re-analysis.
- **Which events:** each chart lists what its lane shows — the selected party's (or squad's)
  downs and deaths, and on the Debrief chart also the enemy lane as counts ("Enemy: 2 downs,
  1 death"), since enemies are anonymous.
- **Discoverability:** markers get a hover emphasis (slightly bigger) and the pointer cursor;
  the chart caption mentions "hover a marker to see who".
- **Shared code:** a small `frontend/src/lib/timelineEvents.ts` with
  `eventsNear(tl, x, tolSeconds, filter)` and `eventLines(...)` (HTML-escaped names), used by
  both charts' formatters, so the two stay consistent.

### Out of scope
Click-to-filter by player, per-player timelines, the session pages, the in-game overlay.

## Files
- `frontend/src/lib/timelineEvents.ts` (new): nearby-event lookup and tooltip lines.
- `frontend/src/lib/components/FightTimeline.svelte`, `BoonTimeline.svelte`: formatter adds
  the events section; marker emphasis/cursor; `professions` prop.
- `frontend/src/routes/fights/[id]/+page.svelte`: build the name → profession map, pass it,
  caption text.
- Docs: `docs/plans/08-marker-tooltips.md`, a short `docs/DECISIONS.md` section, README
  fight-page line.

## Verification
- `cd frontend && npm run check && npm run build`; `uv run pytest` stays green (no backend
  change).
- In the dev app (fight 3), in the browser: hover a down and a death marker on the Boons chart
  (Party 4 and Squad) and on the Debrief timeline → names, profession, party, died/got up,
  stab, distance; markers in the same second all listed; zoom in (mouse wheel) and the
  tolerance still matches the marker size; hover far from markers → no events section; GvG
  fight → "left at call-off"; enemy lane shows counts. Names with special characters render
  as text (escaped).
