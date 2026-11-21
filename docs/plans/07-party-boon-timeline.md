# WvW Analyzer: per-party boon timeline plan

> **Status:** approved 2026-11-21, released in 0.5.1. Deviations: boon names are sent as
> ordered `[id, name]` pairs (`boonNames`), since a JSON object's numeric keys are re-sorted
> by id in the browser, which scrambled the legend. After tester feedback ("no way back"),
> **All boons →** adds a history entry and the Boons chart has **← Fight timeline**; a review
> then fixed the URL handling (see DECISIONS).

## Context

Tester feedback on a fight's Debrief tab (`/fights/<id>`): the fight timeline's only per-party
option is the **Stability per party** checkbox, which overlays one stability line per party.
They want to **pick one party and see all of its boons** over the fight, not only stability,
and suggested it might need its own tab.

What exists:
- `metrics/timeline.py` already samples per-player boon states and builds per-party series in
  `_group_series` (stab, resist, prot, aegis coverage; avg boon count; downs; damage; healing),
  sent as `stats.timeline.parties` and drawn by `frontend/src/lib/components/FightTimeline.svelte`
  (`partyLines` adds one stability line per party).
- The fight page's **Boons** tab is a whole-fight table only (uptime and generation per player,
  party and squad; `StatTable`, groups `Uptime` / `… generation`).
- `model/fight.py` `BOONS` lists the 13 boons plus Stealth; `INTENSITY_BOONS` = Stability, Might.

Size check on the largest corpus fight (752 s, 8 parties): stats JSON today 640 kB (115 kB
zlib). All 13 boons for squad + 8 parties as integer percents adds about 257 kB raw, under 94
kB compressed even for random data (real step functions compress far better).

## Design

### Backend: per-party boon series
- `metrics/timeline.py`:
  - `PlayerTimeline` gets `boon: dict[int, np.ndarray]`, sampled with the existing
    `sample_states(p.buff_states(id), times_ms)` for every id in `BOONS` except Stealth.
    The existing `stab/resist/prot/aegis` fields stay (detectors use them).
  - New `_boon_series(pts)`, reusing `_coverage`'s rule (share of **up** members that have the
    boon; NaN when nobody is up): per boon a coverage series, and for `INTENSITY_BOONS` also the
    average stacks of up members (as `_mean_up` does).
  - `Timeline.series_json()` adds `"boons": {"squad": {...}, "<group>": {...}}` with
    `{"<boon id>": [coverage 0–100 as int | null, ...]}` plus `"<id>s"` stacks (1 decimal) for
    Stability and Might. Integers keep it small; `null` where nobody in the party was up.
  - Labels come from `BOONS` (sent once as `"boonNames"`), so the frontend has no boon list.
- Bump `ANALYZER_VERSION` (stored fights get the series on the next start through the
  existing re-analysis). No detector or note changes: the zerg corpus snapshot must stay
  identical apart from the added series.

### Frontend
- **Boons tab: "Boons over time" chart** above the existing table (the tester's "own tab", in
  the tab that's already about boons):
  - Party picker as chips: **Squad**, **Party 1 … N** (member count and professions in the
    chip's tooltip, from `stats.parties`).
  - One line per boon (coverage %, left axis); Might and Stability average stacks on a right
    axis (0–25). Legend starts with the defensive and core ones on (Stability, Aegis,
    Protection, Resistance, Quickness, Alacrity, Might) and the rest off (Resolution, Fury,
    Regeneration, Vigor, Swiftness, Superspeed); clicking toggles.
  - A marker lane below with that party's downs and deaths (`squadDowns` / `squadDeaths`
    already carry `group`), plus the GvG round shading, so drops line up with what happened.
  - New component `frontend/src/lib/components/BoonTimeline.svelte`, reusing
    `FightTimeline.svelte`'s ECharts setup, colors, `pct()` helper, tooltip and resize handling.
- **Debrief timeline:** replace the **Stability per party** checkbox with a **Party** select:
  `Squad` (today's chart), `Party 1 … N` (the top chart's stability, resistance, protection
  and avg boons switch to that party's existing series, markers filtered to that party), and
  `All parties: stability` (today's checkbox view). Next to it an **All boons →** link opens
  the Boons tab on the same party.
- The selected party is kept in the URL (`?party=2`) like `?tab=`, so links and reloads keep it.
- Types in `frontend/src/lib/api.ts` (`Timeline.boons`, `boonNames`). A fight analyzed before
  this change has no `boons`: the chart shows "Re-analyze this fight to see boons over time".

### Out of scope
Per-player boon timelines, boon generation over time (who gave it), the overlay and the session
pages.

## Files
- `backend/wvw_analyzer/metrics/timeline.py` (sampling, `_boon_series`, `series_json`)
- `backend/wvw_analyzer/analysis.py` (`ANALYZER_VERSION`)
- `frontend/src/lib/components/BoonTimeline.svelte` (new), `FightTimeline.svelte` (party mode)
- `frontend/src/routes/fights/[id]/+page.svelte` (party select, Boons tab chart, `?party=`)
- `frontend/src/lib/api.ts` (types)
- `tests/test_analysis.py` or a new test file; `tests/factory.py` if boon states are needed
- Docs: `docs/plans/07-party-boon-timeline.md`, `docs/DECISIONS.md` section, `README.md`
  (fight page description)

## Verification
- Python test with `tests/factory.py`: a party where 2 of 4 up members have Quickness gives 50;
  a downed member doesn't count; nobody up gives `null`; Might stacks average; every BOONS id
  except Stealth is present for squad and each party.
- `uv run pytest` (corpus included), `uv run ruff check backend tests scripts`,
  `cd frontend && npm run check && npm run build`.
- Corpus snapshot before/after: notes and summaries identical (only the new series added); size
  of the largest fight's stats before/after recorded in DECISIONS.
- In the dev app (`uv run wvw-analyzer --no-window`, fight 3): pick each party on the Boons tab,
  toggle boons in the legend, check that a party's downs line up with its boon drops; Debrief
  select switches the top chart and "All boons →" lands on the same party; reload keeps
  `?party=`. You check it in the browser or app window.
