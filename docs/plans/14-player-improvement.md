# WvW Analyzer: personal improvement ("My play") plan

> **Status:** approved 2026-11-25, not implemented yet. Before approval the proposal was
> reviewed against the corpus and the code; the corrections are folded in (down causes must be
> measured against the squad's rate, same spec is not same job, storage size, split rows, the
> commander). The thresholds are starting values; step 2 calibrates them on the corpus before
> any UI is built.

## Context

Everything the app says today is about the squad: why the fight was lost and what the group
should change. The only per-player note is `player_outliers`, a list of names for the
commander. A player who wants to know "what did *I* do wrong, and what should I work on" has
to read the stat tables himself.

The request: hints for one player, for a single fight, a session, or many fights, built only
from the logs the user already has. No outside data (no build sites, no benchmarks).

### What the logs hold (dev corpus: 142 logs, 93 analyzed fights, 2,910 in-fight player rows)

- **Squad members have nearly the same detail as the recording player:** skill casts with
  times (`rotation`, dodges included), damage dealt and taken per skill (`totalDamageDist`,
  `totalDamageTaken`), a death recap per death (`deathRecap`: every hit in the seconds before
  the down, with skill and enemy spec), consumables with their class (`Nourishment`,
  `Enhancement`), cast uptime and cancelled casts (`statsAll`), dodges, blocks, CC received,
  time downed and dead (`defenses`). Missing in the corpus: skill casts for 20 rows, the recap
  for 1 of 679 deaths, damage taken per skill for 336 rows (12%). Facts must allow for gaps.
  None of this is used or stored today.
- **Already stored per fight:** every player's stat row (`analyses.players`), every squad down
  with stability stacks, distance to tag and stack, boons and conditions just before
  (`timeline.squadDowns`), and each player's per-second series.
- **Not in the logs:** traits, gear and stats beyond weapon types, enemy boons, enemy names.
  So no build advice and no "correct rotation" advice: both would need outside knowledge.

### What the numbers say

For the recording player (92 fights in the fight, 3 raid days, 6 specs, three of them in 85
fights):

- **One fight rarely holds a personal pattern.** 45 downs in total; the median fight has 0.
- **How a player's downs split says little on its own.** The player's split is the squad's:

  | Of the downs | Recording player (45) | Whole squad (1,026) |
  |---|---|---|
  | no stability | 44% | 53% |
  | over 900 from the tag | 13% | 15% |
  | at most one other squad down within 4 s | 24% | 24% |
  | ended in death | 62% | 65% |

  In fights with 6+ squad downs the player was among the first three in 6 of 26; chance
  alone gives 5.0. So "44% of your downs had no stability" is not a finding. A finding is a
  share or a rate clearly **above the squad's in the same fights**, and for this player the
  honest result on down causes is "nothing stands out".
- **Downs are bursts:** median health 3 s before is 94%, the recap spans 1.0 s from 9 enemies,
  and the top skill is 30% of the damage. "You died to skill X" is weak advice in a zerg.
- **Same spec is not same job.** In 126 of 329 spec groups of 3+ players, a third or more had
  a different main output (damage, strips, cleanses, stability given) than the spec's
  majority. Comparing a player with "the other players of his spec" would tell a support
  build that its damage is low.
- **Peers are not always there:** same-spec squadmates in the same fight: median 2, none in a
  quarter of the fights.
- **Small things:** cast uptime without auto-attacks is above 100% in 78 rows (3%); 5% of rows
  have no food and 25% no utility (the recording player always had both).

## Recommendation

The idea is sound and the data is there. Four points shape the design:

1. **Two concepts, as the request suggests, because the data forces it.**
   - **Recap** (one fight, one session): *what happened to you here*. Facts about this
     player's downs and numbers next to comparable players in the same fight, each with a
     one-line hint. It never claims a habit: one fight can't show one.
   - **Profile** (many fights): *what to work on*. Habits that repeat, ranked, each with its
     sample ("14 of 31 downs over 48 fights, squad: 6 of 31"), a trend, and links to example
     fights. Below a minimum sample a rule stays silent and the page says how much data is
     missing.
2. **Every rule is a comparison, never a bare share.** Baselines come from the user's own
   logs, in this order: players with the same spec *and the same job* in the same fight (for
   output), the squad in the same fights (for what every role shares: survival, distance,
   stability at the down), and the player's own earlier fights (the trend).
3. **"Nothing stands out" is a result.** The page then shows the numbers and the strengths,
   and does not invent a weakness.
4. **Facts at analysis time, rules at request time.** Extracting the facts needs the EI JSON
   (the worker). The rules only read the stored facts, so the same code serves a fight, a
   session or all fights, and thresholds can change without a re-analysis.

Facts stay code-written (hard requirement 1): rules are pure and deterministic, wording comes
from `notes/templates.yaml`. No LLM in this plan.

## Design

### 1. Per-fight player facts (`metrics/personal.py`, analysis worker)

For each squad row, keyed by its `series_key`:

- **Downs** (from `timeline.squad_downs`, so the "another fight" and GvG rules stay the same):
  time, stability stacks, distance to tag and stack, conditions, `died`, plus new: health 3 s
  before, other squad downs within ±4 s, the down's rank among the squad's downs, the party's
  stability coverage at that second, and from the death recap the span, the number of enemies
  and the top 3 skills with their share and enemy spec. Downs left at a GvG call-off or after
  one are marked and never judged.
- **The squad's side of each down measure in this fight:** squad downs, and how many had no
  stability, were far, were alone; players downed, and the order. Without these a rule has
  no baseline.
- **Scalars:** time dead and downed (clamped to the log), cast uptime without auto-attacks
  (dropped when above 100), cancelled casts and their time, dodge casts, food and utility
  present (by buff class).
- **Skills:** top 5 damage dealt (hits, share that connected, blocked, evaded) and top 5
  damage taken, by name; absent when the log has none.
- **Job:** the output this row is strongest in relative to the squad median (damage, strips,
  cleanses, healing where recorded, squad stability given), or none when all are low.
- **Peer references** for a fixed metric list (damage, down contribution, strips, cleanses,
  healing where recorded, squad stability given, damage taken, deaths, dodges, CC received,
  cast uptime, distance to tag, stability uptime): the player's value (counts per minute in
  the fight; rates as they are), the median and count of the other in-fight players with the
  same spec and job, and the squad median. Stored as ingredients, not verdicts. The commander
  is left out of peer medians, as in `player_outliers`.

**Storage.** A new table, so a profile over hundreds of fights doesn't unpack stat blobs or
parse every fight's full player rows:

```sql
player_fights(fight_id REFERENCES fights ON DELETE CASCADE, key, account, name, profession,
              party, is_pov, is_commander, in_fight, active_s, facts BLOB,  -- zlib(JSON)
              PRIMARY KEY (fight_id, key))
-- index on account
```

- Written by `save_analysis` (replacing the fight's rows); removed in `set_skipped`.
- **Size.** A fight stores about 52 kB of stats and 53 kB of player rows today (dev database).
  The facts are compressed and must stay well below that; step 1 measures it on the corpus.
- `ANALYZER_VERSION` 8; stored fights are re-analyzed from the kept EI JSON on startup, as for
  earlier bumps. Summaries, notes and stat tables must not change.

### 2. Rules (`coach/`, a second registry next to the fight detectors)

A rule takes one player's `player_fights` rows for a scope and returns `Finding`s (same
schema, templates under `me_*` keys, thresholds in `defaults`). Each rule states its gate:
minimum fights and minimum events. `registry.check_overrides` and the Settings list are
extended to the new registry; changing a personal threshold needs no re-analysis.

**Survival** is led by one rate; the causes only explain it.

| Key | Fires when | Hint is about |
|---|---|---|
| `me_deaths` | downs and deaths per 10 min, and time dead, clearly above the squad's per-player rate in the same fights | survival overall; names whichever cause below stands out |
| `me_down_no_stab` | share of downs with 0 stability, while the party had coverage, above the squad's share in the same fights by a margin | range of the party's stability, timing |
| `me_down_far` | the same for downs far from tag (`out_of_position.far_tag`) | positioning |
| `me_caught_alone` | the same for downs with at most one other squad down within 4 s | being picked: flanks, over-extending, late retreat |
| `me_first_down` | among the first three players downed more often than chance (3 / players downed) by a margin, in fights with 6+ squad downs | the opening: entering too early or too deep |

**The rest:**

| Key | Fires when | Hint is about |
|---|---|---|
| `me_far_from_tag` | time-weighted distance to tag above the squad median by a factor, in most fights | positioning outside downs |
| `me_low_output` | median ratio to same-spec, same-job peers on that job's metric below a share, in fights with 2+ such peers | the role's main output |
| `me_low_activity` | cast uptime without auto-attacks below those peers by a margin; many cancelled casts | pressing skills, fewer interrupted casts |
| `me_cc_taken` | CC received per minute well above the squad, with stability uptime below the party's | range of stability, stun breaks |
| `me_no_food` | fights without food or utility | preparation |

Positives use the same measures the other way (`me_survivor`, `me_top_output`, ...).

- **The player's job** per spec is the job he had in most of his fights on that spec in the
  scope; peers are the same-spec players with that job in the same fight. Without a job, or
  with fewer than 2 such peers in too many fights, the output rules stay silent.
- **Scopes.** `fight`: per-event hints only (each down gets its matching hint; this fight's
  numbers next to the peers'). `session`: the rules with lower gates and "this session"
  wording. `profile`: full gates, plus a trend per rule: the latest third of the scope
  against the rest (better / same / worse), shown only when both parts pass a gate.
- **Ranking.** Impact is the downs and deaths a rule explains beyond the squad's rate. The
  profile shows the top 3 to work on and up to 2 strengths; the rest is under "more".
- **Nothing fires:** "Nothing stands out in N fights", with the numbers and strengths.
- **Per spec.** Output and activity rules run per elite spec; survival and positioning run
  over all fights and say so when one spec stands out.
- **Fights that count.** `in_fight` rows only. A player EI split into several rows in one
  fight is one player in one fight (counts add up, as in the session aggregate). When two
  logs cover the same fight (a friend's log imported next to the user's own), the one where
  the player recorded wins.
- **The commander** has no distance to tag and no peers: fights where the player led count for
  survival only.
- **Examples.** Each finding lists its fights and event times, for deep links.

### 3. API

- `GET /api/players` : accounts seen, with fight counts, names and specs (for the picker).
- `GET /api/players/{account}/review` with one of `fight=ID`, `session=ID`,
  `sessions=N` (latest N), `from=&to=` or nothing (all), and optional `profession=`. Returns
  the scope (fights, sessions, time, specs), `advice` (ranked findings with evidence, trend and
  examples), `gates` (what each silent rule still needs), `numbers` (the metric table: you,
  peers, squad, trend) and for a fight the down list and skill tables.
- `Settings.my_account` (optional). Default: the account that recorded the most analyzed
  fights (`is_pov`).
- Types in `frontend/src/lib/api.ts`. Same local-only checks as every endpoint. `/api/overlay`
  and its fixture don't change.

### 4. UI

- **My play** (new page and navigation entry): player picker (starts on "me"), scope picker
  (last session, last 5 sessions, last 30 days, all), spec chips. Sections: **Work on** (top 3
  cards: what, the sample next to the squad's, the hint, trend, example fights), **Keep
  doing**, **Your downs** (how they split next to the squad's split, and the recent ones with
  links), **Your numbers** (you, peers, squad, trend). Scope and player are kept in the URL.
  With too little data: the facts, and what is still missing.
- **Fight page, "You" tab:** the recap for this fight: each down as one line with its context
  and hint, your numbers next to the peers here, what hit you, your top skills. A link to My
  play. Its own player select (the page already keeps `?player=`).
- **Session page, "You" tab:** the session recap, with a note when the sample is too small
  for a pattern.
- Deep links open the fight on that player's chart at the down (`?player=` exists; add `?t=`).
- Names from logs go through `escapeHtml` wherever a chart tooltip shows them.

### 5. Steps (each ends runnable and tested)

1. Facts, table, `ANALYZER_VERSION` 8, corpus snapshot, database size before and after.
2. Rules, templates and `scripts/calibrate_personal.py`: every rule over **every** account in
   the corpus (2,910 player rows). A threshold is accepted when the rule fires for a minority
   of the players who pass its gate and its examples hold up when opened by hand. The user
   reads his own profile: he is the one person who can say whether it is true. Then the API.
3. Fight "You" tab.
4. My play page, session "You" tab, the setting.
5. `DECISIONS.md`, `README.md`, the docs index, this plan's status line.

## Not in this plan

- Build, trait, gear or rotation-order advice (needs outside knowledge).
- Advice about specific enemies (anonymous, partial data).
- LLM wording of the profile; the in-game overlay showing personal hints.
- Goals or progress tracking beyond the trend per rule.
- Party-level or commander-level coaching.

## Risks

- **Too little signal.** The corpus has one recording player on three days. If step 2 shows
  that most rules fire for almost nobody, or for almost everybody, the profile shrinks to the
  rules that hold, and the recap (facts next to peers) is the feature.
- **Job detection is a heuristic.** A weak player's "strongest output" can be an accident.
  Taking the job from most of his fights steadies it; step 2 checks how often a player's job
  flips between fights on one spec.
- **Other players' rows can be partial** when they were far from the recorder (12% lack
  damage taken per skill). Rules use `in_fight` rows and skip missing values.

## Validation

- Unit tests with `tests/factory.py`: each fact (a down with and without stability, alone and
  in a bomb, GvG call-off downs ignored, clamped times, cast uptime above 100 dropped, missing
  recap or skills, no peers, a split player, the commander), each rule at, below and above its
  gate and exactly at the squad's rate (must not fire), the trend, the same-fight-twice rule,
  and every `me_*` template's placeholders present in its evidence.
- API tests: each scope, an unknown account (404), a player with too little data, a player
  with nothing to work on, the default account.
- Zerg path: corpus snapshot before and after in zerg and GvG mode; summaries, notes and
  stats identical apart from the version.
- Calibration report from step 2 kept in the `DECISIONS.md` entry (fire rates per rule).
- Browser check on the dev database: My play for the recording player and one other player,
  a fight's "You" tab against its Defense table and timeline, a deep link to a down.
- `ruff`, `pytest`, `npm run check`, `npm test`, `npm run build`.

## Decisions (confirmed by the user, 2026-11-25)

1. **Any player can be reviewed**, not only "me": the stat tables already show everyone, and
   commanders and friends will want it.
2. **GvG and zerg fights count together**, as on the other pages, with call-off downs left out.
3. **Page name:** "My play".
4. **Specs are judged separately** for output and activity, together for survival and
   positioning.
