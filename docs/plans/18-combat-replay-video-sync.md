# WvW Analyzer: combat replay, timeline jumps and synced video plan

> **Status:** written as plan 17, renumbered 18 on merging (17 went to the in-app updater).
> Draft (2026-11-26), reviewed once and the review's fixes applied: replay cache
> kept by the startup cleanup, precise sync dropped (DECISIONS: no `.zevtc` parsing), OBS
> edge cases, map images as an on-demand download, one-decimal positions. Approved and
> implemented 2026-11-26 (see `DECISIONS.md`, "Combat replay and synced video"). Deviations:
> no drag and drop for videos (the page can't learn a dropped file's path; picker, path field
> and folder suggestions instead); a fourth start source, `filetime` (creation time, else one
> length before the last write); map images need no coordinate bounds (EI's positions are
> already in the image's pixels) and download from the Replay tab or Settings; phase 5 dropped:
> EI frames Seared Borderlands fights in a per-fight box whose origin isn't in the JSON, so no
> fixed image can be aligned; `logStartOffset` not added (0 in every corpus fight).

## Goal

See what actually happened at a moment of a fight without scrubbing through anything:

1. A **combat replay** of the fight (positions on the map, downs and deaths) in the app.
2. **Click the fight timeline** to jump the replay to that second.
3. **Videos** of the evening, synced to every fight, opening at the clicked second.
4. **Several videos** at once (for example the user's own and a squad mate's), all on the
   same moment.
5. **Optional OBS connection:** when connected, starting a recording in the app also starts
   the OBS recording, and the video is linked and synced with no further steps. Without it,
   everything above still works through the manual flow.

## Done when

- The fight page has a Replay tab that plays any fight, also those recorded before this
  change, with no re-parse.
- A click on the Debrief fight timeline opens the replay at that second (minus a lead-in).
- A video added once is synced to every fight it covers, within about ±2 s, and can be fixed
  for all of them with one nudge or one "Sync here".
- With OBS connected and "start OBS with recording" on, a whole evening needs no video steps:
  Record → play → Stop, then every fight of the session has its video.
- With OBS not configured, not running or failing, recording logs works exactly as today.
- The zerg and GvG analysis output is unchanged (corpus snapshot before/after is identical).

## Out of scope

- Skill effects (AoE circles, fields) in the replay: Elite Insights only draws them in its HTML
  report; its JSON has positions, facing and down/dead/dc intervals only.
- Editing, trimming, transcoding or copying videos. The app never writes to a video file.
- OBS on another computer. The connection is to `127.0.0.1` only.
- Chapter markers in the video file (`CreateRecordChapter`): fight logs arrive after the fight
  ends, so markers would land at the wrong time, and they only work with Hybrid MP4.
- Uploading or sharing videos. A squad mate's video is a file they send the user.
- Sub-second automatic sync. It would need the log-start event's millisecond time from the
  `.zevtc`, and DECISIONS says the app never parses `.zevtc` itself (only the header check in
  `ingest/evtc.py`). ±1 s plus "Sync here" is enough for finding a moment.

## UI

No new item in the main menu.

### Fight page: new "Replay" tab

After Debrief: Debrief, **Replay**, Overview, Boons, ...

```
┌─────────────────────────────┬──────────────────────────┐
│  Map replay                 │  Video (main)            │
│                             ├────────────┬─────────────┤
│                             │ Video 2    │ Video 3     │
├─────────────────────────────┴────────────┴─────────────┤
│ ◀5s  ▶/❚❚  5s▶   0.5× 1× 2× 4×   1:23 / 3:22   Map│Video│Both │
│ ───── fight timeline (same chart as Debrief) ──|playhead|────── │
└───────────────────────────────────────────────────────────────┘
```

- **Map:** squad dots in profession colors, commander tag, allies and enemies in team colors,
  downed and dead states, facing. Hover: name (squad and allies) or profession (enemies have
  no names in the logs). Zoom, pan, "follow commander", the page's party filter.
- **Background:** Elite Insights' map image for Eternal Battlegrounds, Alpine Borderlands,
  Desert Borderlands and Edge of the Mists, once downloaded (one click, see Design); a plain
  grid until then and for maps without one (Seared Borderlands, most of the current corpus).
- **Controls:** play/pause, ±5 s, speed, keys (space, arrows), layout Map / Video / Both.
  The map and every video follow one clock.
- **Videos:** one big, the rest small; click a small one to swap. Only the big one has sound.
  A video that doesn't cover this fight is hidden with a note ("ends 2 min before this fight").
- **Deep link:** `?tab=replay&t=83`, with Back behaving like the other tab links.

### Jumps into the replay

- A click on the Debrief fight timeline opens Replay at that second minus the lead-in (3 s by
  default). On the Replay tab the timeline shows a playhead and a click seeks.
- Small "▶ replay" links where the app already shows a moment: the downs list on Positioning,
  downs on the You tab, and debrief findings that carry a time.

### Session page: new "Videos" tab

- **Add video:** file picker or drag and drop. The file stays where it is.
- **Suggestions:** files in the recording folders (Settings) whose time span covers fights of
  this session: "2 recordings from this evening found. Link them?"
- **One row per video:** file name, label ("Me", a squad mate's name, any text), fights it
  covers, how it was synced (OBS / file name / manual), format status, nudge −/+ 0.5 s,
  "Sync here", remove link (never deletes the file).
- **Fights list:** a camera icon on fights that have video.

### Settings: new "Videos" section

- Recording folders (for suggestions), default `%USERPROFILE%\Videos`.
- Jump lead-in (s), default 3.
- **OBS connection (optional):**
  - Enable (off by default), port (default 4455), password, "Test connection" (shows the OBS
    version, or the reason it failed).
  - "Start and stop OBS recording with the app's recording" (default on once enabled).
  - "Link OBS recordings automatically" (default on once enabled).
  - A short how-to: OBS → Tools → WebSocket Server Settings → Enable, copy the password.
- The recording bar shows a small OBS status: not set up / not running / connected /
  recording.

## Design

### Replay data

- Source: the stored EI JSON of the fight (`fights.ei_json`, kept until the fight is
  deleted). `ParseCombatReplay=true` is already set, so old fights work.
- `GET /api/fights/{id}/replay` returns a compact payload: actors (kind squad/ally/enemy,
  name or profession, party, team, commander flag), positions with one decimal (one EI pixel
  is 60-100 game units, too coarse for close fights as whole numbers) and facing in whole
  degrees at the polling rate, down/dead/dc intervals, polling rate, map rect and map id.
- Extraction runs in the analysis worker process (the EI JSON is tens of MB unpacked; the
  main process must not hold it) and is cached next to the EI JSON as
  `<EI JSON name without .json.gz>.replay.json.gz`.
- **Cleanup:** `cleanup_orphans` today deletes every `.json` / `.json.gz` in `ei/` that no
  fight row references, which would wipe the cache on every start. It changes to: a
  `*.replay.json.gz` file is kept while the EI JSON it was made from is referenced, and
  deleted with it. A cache from an older payload version (version field inside) is rebuilt.
- Size: a 12.5-minute fight with ~140 actors is a few MB of JSON before gzip. Fine to load on
  demand; nothing goes into SQLite.
- Not part of the analysis: no `ANALYZER_VERSION` bump, zerg/GvG results untouched.

### Map images and coordinates

- The map bounds per map id are copied from Elite Insights' `WvWLogic.GetCombatMapInternal`
  (its source is MIT licensed); positions in the JSON are already in its pixel space
  (`combatReplayMetaData.inchToPixel`, `sizes`).
- The images are **not** loaded from imgur by the page (DECISIONS: nothing is sent anywhere
  except pinned downloads). They become pinned, checksummed downloads in `tools.py`, fetched
  on demand like the LLM files (a "Download map images" prompt on the first Replay, and in
  Settings), and saved in the data folder. They are not shipped in the installer: they are
  derived from ArenaNet's maps, and fetching them from where Elite Insights publishes them
  avoids redistributing them ourselves. Not downloaded or offline: grid.
- A Seared Borderlands image is a later step (needs a source and our own coordinate fit).

### Time model and sync

All times are UTC milliseconds.

- **Fight start:** `timeStartStd` of the EI JSON (the log start; second precision, with time
  zone). Fight second `t` happens at `fight_start + t`. Not `instanceTimeStartStd`, which is
  when the player entered the map (minutes earlier). Checked on the corpus: all 142 fights have
  `logStartOffset` 0 and `isLateStart` false. A fight with a non-zero `logStartOffset` adds it.
- **Video start:** when the first frame of the file was recorded.
- **Video time** for fight second `t`:
  `video_t = fight_start + t − video_start − paused_before(t) + offset`, where `offset` is
  the user's nudge / "Sync here" correction (one value per video, applied to all fights).
- **Coverage:** a video covers a fight if `[video_start, video_end]` overlaps the fight.
  Videos are linked by time, not to a session: a video added on one session page also serves
  every other fight it overlaps. The session Videos tab lists the videos overlapping its
  fights.
- **Video start, in order of preference:**
  1. OBS connection: exact (see below).
  2. File name: OBS's default `%CCYY-%MM-%DD %hh-%mm-%ss`, plus a few common patterns
     (NVIDIA ShadowPlay, Windows Game Bar). Local time of this PC.
  3. Manual: "Sync here" on a recognizable moment.
- **Video end:** OBS duration; else the browser's `video.duration` once loaded; until then,
  the file's modification time (recorders write until the end).
- **Accuracy:** the log start is only known to the second, so even with OBS the automatic
  sync is about ±1 s; file names add up to another second. "Sync here" fixes it exactly.
  A squad mate's video from another time zone or with a skewed clock needs one "Sync here".

### Video playback

- `GET /api/videos/{id}/file` streams the file with HTTP Range support (Starlette
  `FileResponse`), looked up by id only: the API never takes a path from the request.
  The localhost Host rule applies as for every route.
- Format check: the page tries to play and, on a decode error, the row says why and suggests
  OBS → File → Remux to MP4 or H.264/AV1. H.264 and AV1 play in WebView2; HEVC needs an
  extension and may not. **To test on Windows before phase 3 is built:** whether an OBS MKV
  with H.264 plays in the app window. If not, MKV gets the same remux hint.
- Several videos: one shared clock; each video is re-seeked when it drifts more than
  ~0.25 s. Only the main video decodes sound.

### OBS connection (optional)

- **Protocol:** OBS WebSocket v5, built into OBS 28 and later; no plugin. RPC version 1.
  `Hello` → `Identify` (auth: `base64(sha256(base64(sha256(password + salt)) + challenge))`,
  event subscription `Outputs` = `1 << 6`) → `Identified`.
- **Client:** a small one of our own on `websockets` (already installed through
  `uvicorn[standard]`; listed as a direct dependency), running in its own thread like the
  recorder, reconnecting with backoff while enabled. Host fixed to `127.0.0.1`.
- **Used messages:**
  - `RecordStateChanged` (`outputState` STARTED / PAUSED / RESUMED / STOPPED;
    `outputPath` only when stopped).
  - `RecordFileChanged` (`newOutputPath` when OBS splits the file; OBS WebSocket 5.5+).
  - `StartRecord`, `StopRecord` (its response has `outputPath`), `GetRecordStatus`
    (`outputActive`, `outputPaused`, `outputDuration` ms), `GetRecordDirectory`.
- **Exact start:** the events carry no timestamp. On STARTED the app takes the wall clock
  and right after calls `GetRecordStatus`: `video_start = now − outputDuration`. When the
  app connects while OBS is already recording, the same call gives the start of the current
  file.
- **Adopting a recording that was paused before the app connected:** `outputDuration` most
  likely counts recorded time only, so the start would come out late by the paused time
  (unverified). If `outputPaused` is true at that moment, or OBS's reported duration and the
  file name's time disagree by more than 2 s, the video is marked "approximate sync" and its
  row suggests "Sync here".
- **The file path** is only known on STOPPED / `StopRecord` / `RecordFileChanged`. Until then
  the video is a pending row (start known, path not). If the app is closed before OBS stops,
  the pending row is completed at next start by matching the recording folder
  (`GetRecordDirectory`) and the file-name time.
- **Splits:** each `RecordFileChanged` ends the current file's row (end = now) and starts a
  new one (start = now).
- **Pauses:** PAUSED/RESUMED wall times are stored per video and subtracted in `video_t`.
- **With "start and stop OBS with recording" on:**
  - App recording starts (manually or with the game) → `StartRecord`, unless OBS is already
    recording; then that recording is adopted.
  - OBS starts or the connection comes up **while the app is already recording** → the app
    starts the OBS recording then (or adopts the one running). Fights before that have no
    video, as without OBS.
  - App recording stops (manually, game closed, app closed) → `StopRecord`, **only if the app
    started it**. A recording the user started in OBS is never stopped by the app.
  - Auto-record starts with the game, so OBS also records loading and character select.
    Accepted: it keeps the rule simple (OBS records exactly while the app records), and
    starting at the first fight log instead would miss that whole fight, since logs arrive
    only after a fight ends.
  - **Left running after a crash:** if the app was closed without stopping a recording it
    started (the `videos` row has `started_by_app` and no end), the next start finds OBS
    still recording and shows "OBS is still recording from the last session" with Stop and
    Keep buttons. It never stops it on its own.
- **Without that option:** recordings the user starts in OBS are still linked by time
  ("Link OBS recordings automatically").
- **Failure never blocks logs:** OBS not running, wrong password, a refused `StartRecord`
  (for example no free disk) → a status message, and log recording carries on.
- **Password:** stored in `config.yaml` next to the database (OBS keeps it in plain text in
  its own config too), never written to the app log, and never returned by the API (the
  settings response says only whether one is set).

### Data

New table `videos`: id, path (nullable while pending), label, start_ms, end_ms (nullable),
sync_source (`obs` / `filename` / `manual`), approximate (bool), offset_ms, pauses (JSON list
of `[start_ms, end_ms]`), started_by_app (bool), created_at. No video data in the table, no
change to `fights`. Removing a link deletes the row only.

New settings: `videos.folders`, `videos.lead_in_s`, `obs.enabled`, `obs.port`,
`obs.password`, `obs.control_recording`, `obs.auto_link`.

## Phases

1. **Replay + timeline jumps.** Replay endpoint and cache (with the cleanup change), map
   images (on-demand pinned download), Replay tab with controls, click-to-jump from Debrief,
   "▶ replay" links, deep link.
2. **One video.** `videos` table, add by picker/drop, file-name start, Range endpoint,
   coverage, nudge and "Sync here", format check, camera icon.
3. **Several videos + suggestions.** Main/small layout and swap, shared clock with drift
   correction, folder scan suggestions, Settings → Videos.
4. **OBS connection.** Client, Settings section with test, status in the recording bar,
   start/stop with the app's recording (also when OBS connects late), auto-linking, pending
   rows, splits, pauses, approximate-sync marking, the "still recording" notice.
5. **Later / optional.** Seared Borderlands map image.

Each phase is usable on its own.

## Tests and validation

- **Backend (pytest, temp dirs):**
  - Replay extraction on `tests/factory.py` fights: shapes, intervals, map rect; cache reuse,
    rebuild on a version change, `cleanup_orphans` keeping a cache whose EI JSON is
    referenced and deleting it with the fight.
  - Time model: fight → video time with offsets, pauses, splits, time zones, coverage.
  - File-name parsing for each supported pattern; files that don't match.
  - Range requests on the video endpoint; unknown id → 404; no path parameters.
  - OBS client against a fake OBS WebSocket server: auth, subscriptions, start/stop only what
    the app started, adopting a running recording (and a paused one → approximate), OBS
    connecting while the app already records, pending rows, splits, pauses, the "still
    recording from the last session" case, OBS missing or wrong password with log recording
    still working.
  - Settings API never returns the OBS password.
- **Frontend:** `npm run check`, `npm test` for the sync math and timeline click mapping.
- **Corpus:** analysis snapshot of `data/dev_corpus` before and after: identical.
- **By hand on Windows (needs the user):** replay of a real fight; MKV and MP4 from OBS play;
  a real evening with OBS connected (Record → fights → Stop) and the measured offset of a
  visible event; two videos side by side.

## Docs

- `DECISIONS.md`: replay data source and cache (and the cleanup rule for it), map images as
  an on-demand pinned download, video linking by time, OBS connection rules (localhost only,
  start with the app's recording, stop only what the app started, password handling), why
  there is no sub-second sync (no `.zevtc` parsing), measured sync accuracy.
- `README.md`: Replay tab, adding videos, OBS setup.
- `CLAUDE.md` data rules: videos are never modified, copied or deleted.
