# WvW Analyzer: session stats and per-player charts plan

> **Status:** approved 2026-11-21, implemented (unreleased). Deviations: the reference line on
> a player's trend is the squad's **average player** (`trend.playerAvg`), not the squad line
> (squad totals are on another scale than one player's damage or strips); the trend is one stat
> at a time (picker), on a category axis of fight times; deaths in the per-player series are
> `[start, end]` like downs; the fight timeline's player view shades downed / dead time instead
> of separate marker lanes; no engagement shading on the player boon chart. Review fixes
> (2026-11-21): per-row series keys for split players, split rows merged in the session, death
> intervals clamped, tooltip escaping, a lighter overlay poll, the time column shown as "Time in
> fights" and the party number as its usual size; `ANALYZER_VERSION` 7. Second round: session
> distances without EI's -1 / commander 0, split rows weighted by their own time, the average
> player per player, the trend stat in the URL (see DECISIONS). This is the plan as approved; it is kept as history and not updated. Current behavior is in
> [`../DECISIONS.md`](../DECISIONS.md).

## Context

A fight page has full stat tabs (Overview, Boons, Offense, Support, Defense, Positioning) with
player, party and squad rows. A session only has a Summary (problems, strengths, ten
leaderboards) and a Players tab with 12 fixed columns. There is no way to see, for the whole
raid night, everyone's boon uptime and generation, cleanses, strips, defense or positioning.

Charts only exist for groups: the fight timeline (Debrief) and Boons over time (Boons tab) can
show the squad or one party, never one player.

**No log combining is needed.** Every analysis already stores its per-player rows
(`analyses.players`, all `ALL_COLUMNS` keys plus `group`, `in_fight`, `active_s`,
`fight_dist_tag`), and `aggregate_session` already reads them. Session stats are built from
those rows: no Elite Insights re-run, no re-parse. Per-player charts need per-second data that
the timeline already computes (`PlayerTimeline`) but does not store; see section 5.

**The current combine is wrong for rate columns.** `aggregate_session` sums every column with
`agg == "sum"` and takes an unweighted per-fight mean of the rest:
- Generation columns (`gen_*`, `agg="sum"` so party rows add up their members) are summed over
  fights: three fights at 40% stability generation show 120%. The "Stability given"
  leaderboard ranks by that sum.
- `dps` is summed over fights.
- Uptimes, average conditions and distances are a plain mean per fight, so a 20 s skirmish
  weighs as much as a 6 min fight.
- `active_s` is averaged, when the session total (time in fights) is what matters.

## Design

### 1. How a column combines over a session (`metrics/columns.py`)
- `Column` gets `session: Literal["sum", "time", "dps"]`, derived from `fmt` and key unless set:
  - `sum`: counts and amounts (`int`, `num`, `sec` formats): damage, strips, cleanses,
    healing, downs, deaths, res time, and `active_s` (total time in fights).
  - `time`: rates and shares (`pct`, `stacks`, `dist`, and every `gen_*` column): weighted mean
    over the player's fights, weight = that fight's `active_s` (fallback: fight duration).
    40% stab generation for 5 min and 10% for 1 min gives 35%.
  - `dps`: total damage / total active seconds.
- Exposed in `Column.meta()` as `session` so the UI can label columns.
- Per-fight stat tables do not use it.

### 2. Session rows (`metrics/aggregate.py`)
- **Players**, one row per account, as now, combined per the rule above, only fights where the
  player was `in_fight`. Extra fields: `fights`, `activeS` (total), professions played (as now),
  and `perMin` values for `sum` columns (total / active minutes), so players who joined late
  compare fairly.
- **Squad**: one row for the session. `sum` columns add up; `time` columns are the
  duration-weighted mean of each fight's squad row (rebuilt from the stored player rows with
  `table.squad_row`, in-fight players only); squad generation stays "what the squad gave".
- **Parties**: by party number, the same way as squad, with the accounts that were in that
  party listed for the row tooltip. Parties are usually stable over a raid night; when they are
  not, the tooltip shows it.
- Leaderboards use the corrected values. `time` boards (Stability given) only rank players with
  at least 25% of the session's fight time, so one short fight can't top them.
- **Per-fight trend**: one value per fight for a short list of stats (stab uptime, stab
  generation, strips, cleanses, boons lost, damage, downs, deaths, dist. to tag), for:
  - the squad and each party (rebuilt from the stored player rows),
  - each player (their own stored row; fights they missed are gaps).
  Shape: `trend: {fights: [{fightId, start, result}], squad: {key: [v…]},
  parties: {g: {key: [v…]}}, players: {account: {key: [v…]}}}`. Only the listed keys, so it
  stays small (~60 fights x 50 players x 9 values).
- The response grows from 12 columns to all of them; on a 60-fight, 50-player session that is
  ~50 rows x ~150 values, fine. `session_analyses` already loads the rows.

### 3. API
- `GET /api/sessions/{id}` keeps its shape; `aggregate` gains `squad`, `parties`, `trend`, and
  full player rows.
- `GET /api/fights/{id}` no longer sends the per-player series (section 5); a new
  `GET /api/fights/{id}/players/{account}/timeline` returns one player's.
- `api.ts` types updated.

### 4. Session page (`routes/sessions/[id]`)
- Tabs mirror the fight page: **Summary · Overview · Boons · Offense · Support · Defense ·
  Positioning · Fights**. The old Players tab becomes Overview (same column list as the fight
  Overview, plus Fights and Time in fights).
- Each stat tab reuses `StatTable` with session players / parties / squad and the
  Players / Parties toggle. Boons keeps the Uptime / Self / Group / Off-group / Squad
  generation switch.
- A **Total / Per minute** toggle for `sum` columns (rates are unaffected).
- "Hide players not in the fight" becomes **Min. time in fights** (off, 5, 15, 30 min) to hide
  people who tagged along for one fight.
- **Session trend** chart on Summary (ECharts): x = fight time, points coloured by result,
  click opens the fight. A stat picker, and a **Squad · Party N · Player** picker (player: a
  searchable select). For a player, the squad's line stays as a faint reference, so "below the
  squad" is visible at a glance.
- Clicking a player's name in any session table opens the trend chart for that player.
- Footnote per tab saying how values combine ("Totals over the session; uptime and
  generation weighted by time in each fight").
- `?tab=`, `?player=` deep links and history handling like the fight page.

### 5. Per-player charts on the fight page
**Data** (`metrics/timeline.py`, `series_json`): a `players` entry per squad member, keyed by
account:
- **Boons as runs**, not per-second arrays: per boon `[[start, end], …]`, and for might and
  stability `[[start, end, stacks], …]`. A single player either has a boon or not, so runs are
  both the right chart form and tiny.
- **Per-second series**: health %, damage out, damage in, healing, barrier, number of boons,
  conditions, distance to tag and to the squad's center. Health and distances as integers.
- Their own downs and deaths (already in `squadDowns` / `squadDeaths`, filtered by player).
- Stored in the stats blob like the rest; the fight endpoint drops `players` before sending
  (a 50-player fight would otherwise add a few hundred KB), and the per-player endpoint serves
  one. Bumps `ANALYZER_VERSION` to 6, so stored fights are re-analyzed on startup (from the
  kept EI JSON; no re-parse).

**Boons tab, Boons over time**: the chip bar becomes **Squad · Party N · Player ▾**. A player
shows a band chart (one lane per boon, filled while the boon was on; might and stability
lanes shaded by stacks) over the same time axis, with the player's own down / death markers
and the engagement shading. Party and squad stay the coverage lines they are now.

**Debrief, fight timeline**: the party select gains the players (grouped by party). A player
shows health %, damage out / in, healing + barrier, boons and conditions, and distance to tag,
with their downs and deaths. Squad / party views are unchanged.

**Tables**: clicking a player's name in a fight stat table opens Boons over time for that
player (`?tab=boons&player=<account>`).

### 6. Not in this plan
- Boons over time across the whole session (a per-second chart across separate fights has
  gaps and no shared time axis; the per-fight trend covers it).
- Cross-session trends (still out of scope, see `DECISIONS.md`).

### 7. Validation and docs
- Unit tests with `tests/factory.py` fights of different lengths: generation and uptime are
  time-weighted, `dps` = damage / time, counts sum, `perMin`, min-time leaderboard rule,
  squad and party rows, a player absent from a fight, trend gaps.
- Timeline tests: boon runs match the per-second boon states (stacks included), a boon held
  to the end of the log closes its run, the fight endpoint omits `players`, the per-player
  endpoint returns one player and 404s for an unknown account.
- `test_api.py`: the session response carries the new fields; overlay fixture unchanged.
- Zerg path: snapshot `data/dev_corpus` analyses before and after; the only difference may be
  the new `timeline.players`. Spot-check one real session: session squad stab uptime lies
  between the fights' values, no generation over 100% per target; and one real fight: a
  player's band chart agrees with their uptime in the Boons table. Note the stats blob size
  before and after.
- `ruff`, `pytest`, `npm run check`, `npm run build`; check both pages in the app.
- `DECISIONS.md` entry (combine rules, boon runs, why the per-player series has its own
  endpoint), README session and fight sections, docs index.
