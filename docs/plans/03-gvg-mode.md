# WvW Analyzer: GvG mode plan

> **Status:** approved 2026-11-19, implemented in v0.3.0. Deviations: `fights.mode` is never NULL (old fights migrate to `zerg`); `calloff_quiet_s` was dropped; the call-off uses 1% of peak damage from players at the fight (not 5% from the whole squad); continued EI state intervals are merged. This is the plan as approved; it is kept as history and not
> updated. Current behavior and later decisions are in [`../DECISIONS.md`](../DECISIONS.md).

## Context

GvG = two organized guilds meet at an agreed spot and time. A round ends with a **call-off**: one commander
calls it, everyone stops, walks away, and both sides rez everyone (enemies included), then regroup and go again.

The analyzer assumes open-field zerg fights, so a GvG round produces false notes:
- **downstate_enemy** "Enemy downs escaped": downs left on purpose at the call-off count as failed cleaves.
- **downstate_own**: our downs left at the call-off look like "not picked up"; after-call rezzes inflate the
  resurrect numbers.
- **Result** (deaths trade): a round ends with downs, not deaths, so a clear round win can read "even" or "skirmish".
- **Multi-round logs** (if combat doesn't drop during the regroup): `early_cascade` only sees round 1 and
  `sustain_decline` compares halves of the whole log instead of each round.
- **LLM debrief**: may call left downs a mistake and calls small rounds "Small skirmish, nothing important".

Corpus check (142 real zerg logs): logs end ~7 s (median) after the last damage, so the call-off tail is inside the
log. 23/142 normal zerg fights have a 20 s+ damage lull, so lulls can only split rounds when GvG mode is on.
**There are no GvG logs in the corpus**, so the call-off thresholds are first guesses and need a check on real GvG logs.

Decisions (user, 2026-11-19): a default in Settings **plus** a per-fight / per-session override; handle one round
per log **and** several rounds per log.

## Design

### 1. Mode per fight
- `Settings.fight_mode: Literal["zerg", "gvg"] = "zerg"` (config.py) plus a `gvg` block with the thresholds:
  `round_gap_s=25`, `calloff_grace_s=3`, `calloff_quiet_s=8`.
- New column `fights.mode TEXT NULL` (NULL = follow the setting). It's a migration in `store/db.py` (ALTER TABLE if
  missing). The mode a fight was analyzed with goes into `summary["mode"]`.
- Recording/import: a new fight is stamped with the current `fight_mode` when queued, so flipping the setting later
  doesn't silently change old fights.
- `analysis_job` / `analyze_ei` get a `mode` argument. Bump `ANALYZER_VERSION` to 3: stored fights get
  `mode="zerg"` behavior, the same as today.

### 2. Call-off and rounds (new `metrics/rounds.py`, used by `build_timeline` in GvG mode only)
- **Rounds:** split `[engage_start, engage_end]` at damage lulls ≥ `round_gap_s`, reusing the activity series and
  5% threshold already in `metrics/timeline.py:build_timeline`. One round = the zerg window as today.
- **Call-off per round** = the round's last second of meaningful damage (same rule as `engage_end`), followed by
  ≥ `calloff_quiet_s` of quiet or the end of the log.
- **Down classification**, for each squad down and enemy down:
  - `left_at_calloff`: still downed at call-off + grace, i.e. no death or rally within the round. Rezzed later or
    killed after the grace.
  - deaths after call-off + grace are **not counted** as kills or losses.
- `Timeline` gains `rounds: [{start, calloff, end}]`, `left_squad`, `left_enemy`. Squad-down events get a `round`
  index and `left` flag; enemy downs get the same (enemy down/dead intervals are already in `_collect_events`).

### 3. Summary and result (`metrics/summary.py`)
- GvG adds `rounds`, `leftSquad`, `leftEnemy`, `counted*` downs/deaths (excluding the left ones), and per-round
  results.
- **GvG result per round = "taken out" trade:** deaths + downs left at the call-off per side, same 1.5× thresholds
  as `classify_result`. No "skirmish" in GvG (a round is a round). The fight result is the round tally, e.g. "won
  2–1".
- The fights list/session show `GvG` badges and the round tally. Session aggregation (`metrics/aggregate.py`)
  counts rounds W/L as well as fights.

### 4. Detectors (they read the counted fields, so the zerg path is unchanged)
- `downstate`: conversion = counted enemy deaths / (enemy downs − left); own death rate likewise. Evidence adds
  `left_enemy` / `left_squad`, and the template says "N left at the call-off (not counted)".
- `early_cascade`, `sustain_decline`: run per round (loop over `tl.rounds`; in zerg mode there is one round = today).
- `out_of_position`: ignore downs after the call-off (people walking away).
- `outnumbered`: unchanged (numbers matter in GvG too).
- Boons/strips/cleanses/comp/outliers: unchanged; damage after the call-off is ~0.
- Known limit: per-player `resurrects` comes from EI totals for the whole log, so it includes after-call rezzes.
  GvG mode leaves `resurrects` out of the downstate evidence.

### 5. Notes and LLM
- `notes/templates.yaml`: GvG wording for the downstate keys and result phrases ("Round won", "2–1 over 3 rounds").
- `llm/prompts.py` (`result_line`, `framing_line`, `header_v8`): the GvG result line plus a fixed code-written
  line: "GvG: downs left when the round was called off are agreed and never a mistake." The skirmish framing
  doesn't apply in GvG. The model still only phrases bullets.
- `scripts/llm_bench.py`: allow `--mode gvg` to re-run the v8 check on GvG fights. Claude grades as before.

### 6. API and UI
- `PUT /api/fights/{id}/mode` and `PUT /api/sessions/{id}/mode` ({"mode": "gvg"|"zerg"|null}) store the override
  and queue a re-analysis from the cached EI JSON (existing `reanalyze` path in `api/app.py`).
- Settings: a "Fight type" select (Zerg / GvG) with a short explanation, and the GvG thresholds under Detectors.
- Header: a small **GvG** toggle next to Start recording (it flips the setting, so a GvG block can be marked live).
- Fight page: a mode chip with "Analyze as GvG/Zerg"; round bands and call-off markers on the timeline chart; left
  downs drawn as hollow markers.
- Session page: "Analyze session as GvG/Zerg".

### 7. Docs and tests
- README section "GvG mode"; DECISIONS.md (call-off rule, result rule, mode per fight).
- Tests (`tests/test_gvg.py`, using the synthetic fight factory):
  - a round ending with 3 enemy downs left → no `downstate_enemy` in GvG mode, still present in zerg mode;
  - a death after call-off + grace isn't counted;
  - a 2-round log splits into 2 rounds, and `early_cascade` fires for round 2;
  - the GvG result uses the taken-out trade;
  - the mode override API re-analyzes;
  - the prompt header contains the GvG line;
  - zerg results across the whole corpus are unchanged (`test_corpus`).

## Verification
1. `uv run pytest`, including an unchanged zerg corpus test.
2. Run the 142 corpus fights in GvG mode: no crash, and the split/call-off stats look sane (rounds per fight, left
   downs).
3. **Real GvG logs:** analyze some in both modes and compare the notes. Tune `round_gap_s` / `calloff_*` if needed.
4. Browser: Settings toggle, header toggle, fight/session override, round bands on the chart.
5. LLM: one debrief for a GvG fight from the local model. Check that left downs aren't called a mistake.

## Not in scope
- Auto-detecting GvG (balanced numbers, one enemy guild, same spot). This could become a "looks like GvG" hint later.
- Third-party detection inside a GvG round.
