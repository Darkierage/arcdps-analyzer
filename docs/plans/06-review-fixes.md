# WvW Analyzer: whole-app review fixes plan

> **Status:** approved 2026-11-21 ("fix high and medium"), released in 0.5.1.
> Deviation: a down kept only because it was near the tag is judged by its tag distance alone
> (its stack distance is dropped), otherwise `out_of_position` would always call it far.
> This is the plan as approved; it is kept as history and not updated. Current behavior and
> later decisions are in [`../DECISIONS.md`](../DECISIONS.md).

## Context

After 0.5.0 the whole app was reviewed by area (ingest and recording, zerg analysis, GvG and
sessions, API and frontend, LLM and packaging). Each reviewer checked its area against
DECISIONS.md as use cases and read the code. Nothing failed security-wise; the high and medium
findings below are fixed here. Low ones stay open (listed in DECISIONS.md).

## Fixes

Analysis (changes stored results: bump `ANALYZER_VERSION`, compare `data/dev_corpus` before
and after):
1. Downs near the commander were dropped as "another fight" when the stack center (median of
   everyone alive, including players at a waypoint) was over 5000 away. Keep downs within 5000
   of the tag.
2. Squad downs and deaths summed every squad member, including those flagged as not in the
   fight. Count only players in the fight.
3. "No healing" was flagged for parties where nobody ran the arcdps healing addon (healing not
   recorded). Judge healing only where it was recorded, in `comp_audit` and `player_outliers`.
4. GvG: a down or death in the lull between rounds counted toward the next round. It belongs to
   no round (like events after the last call-off). Session totals leave out kills and deaths
   after a call-off, like the fight page.

Data and robustness:
5. A re-analysis kept the old LLM debrief. Keep it only if the new notes and summary are
   identical.
6. Stopping recording dropped a log still being written (e.g. auto-stop as the game closes).
   The scan thread finishes such logs, then ends the session; Stop returns at once.
7. A second launch started a second instance when the first was on a fallback port. Check busy
   ports up to the first free one for a running instance.
8. A damaged `config.yaml` stopped the app from starting. Load it leniently (drop only invalid
   values), back up an unreadable file and start with defaults; write the config atomically.
9. Settings accepted harmful values: a cleared detector threshold was saved as 0, a 0 poll
   interval spun the CPU, and the API could set `host: 0.0.0.0`. Range-check settings,
   validate detector overrides against their defaults, keep host on loopback and host/port out
   of the API, and treat a cleared field as "default" in the UI.
10. Parallel uploads could create duplicate "Import <day>" sessions. Serialize imports.
11. Closing the window while a debrief was being written could leave llama-server running.
    Stop it (for good) as soon as the window closes.

## Verification

- Regression tests for each fix (`tests/test_review_fixes_2.py`, the recorder drain test).
- Full suite, ruff, svelte-check, frontend build.
- `data/dev_corpus` analyzed before and after in zerg and GvG mode, differences reviewed.
