# WvW Analyzer

A local desktop app for Guild Wars 2 **WvW (zerg) fights**. It turns arcdps logs into:

- **A debrief.** Ranked notes on *why the fight was lost* and *what to change*, each with
  evidence and the moment on the fight timeline. Examples: stability gaps during the enemy bomb,
  losing the strip war, enemy strip bombs, lost openings, enemy downs escaping, downed allies not
  picked up, condition pressure, sustain running out, parties without support, players caught
  away from the tag.
- **Standard log stats.** Boon uptime and generation, damage, down contribution, damage to downed
  enemies, strips, cleanses, healing, defense and positioning. Each is shown per player, per party
  and for the squad.
- **Boons over time, per party or player.** The Boons tab charts every boon second by second for
  the squad or one party (share of its players who had it, plus might and stability stacks), with
  that party's downs and deaths. Pick a **player** to see their own boons as lanes, filled while
  they had each boon (might and stability darker with more stacks), and when they were downed or
  dead. On the Debrief tab the fight timeline can show one party, every party's stability, or
  one player (health, boons and conditions, damage dealt and taken, healing, distance to the tag
  and to the squad). Click a name in any stat table to open that player's boons. Hover a down or
  death marker to see who it was (profession, party, whether they got up, stability before the
  down, distance to the tag).
- **Sessions.** One per raid night, with recurring problems, strengths and leaderboards. Click a
  problem or strength to see the fights behind it, each with its numbers; a fight opens its
  debrief at that note. **See stats** on a note opens the stat table behind it, sorted by that
  column (for example strips for "Won the strip war").
  - **Session stats.** The same tabs as a fight (Overview, Boons, Offense, Support, Defense,
    Positioning) for the whole session, per player, per party and for the squad. Counts and
    amounts are totals (or **per minute** in fights); uptime, generation, stacks and distances
    are averages weighted by time in each fight; DPS is damage / time in fights. **Min. time in
    fights** hides players who were only there briefly.
  - **Session trend.** One stat fight by fight (stability uptime and given, strips, cleanses,
    boons lost, damage, downs, deaths, distance to tag) for the squad, a party or a player, with
    the squad's average player as a reference line. Click a fight to open it (for a player: at
    their boons). Click a name in a session stat table to see that player's trend.
- **Trends.** One point per session, oldest to newest: win rate, K/D or squad deaths per
  fight, with a table of every session's results and its top recurring problem. Click a
  session to open it.
- **My play.** Hints for one player (you, or anyone in your logs): what to work on and what to
  keep doing, over the last session, the last 5 sessions, 30 days or all fights, per spec if you
  like. Your survival is compared with the rest of the squad in the same fights, your output
  and cast time with players of the same spec *and the same job* (strips, damage, cleanses,
  healing, stability) in the same fights. Each hint shows its sample next to the squad's, a
  trend, and example fights that open on your charts at the moment. When nothing stands out it
  says so, with your numbers next to your peers' and the squad's. A fight's and a session's
  **You** tab show the same for that fight or session: each of your downs with the hint that
  matches it, what hit you and your top skills. See [My play](#my-play).
- **An in-game overlay (optional).** A small window inside Guild Wars 2 with the latest fight's
  notes and the session summary, so you don't have to alt-tab. It's a Raidcore Nexus addon,
  installed from Settings.
- **An optional local LLM debrief.** Qwen3 via llama.cpp rewrites the findings into a
  paste-ready text. Everything else is fully static and needs no LLM.

## How it works

```
arcdps .zevtc ──► Elite Insights CLI ──► EI JSON ──► metrics ──► detectors ──► ranked notes
     ▲ recorder watches the log folder                     │                      │
     └──────────── live updates over WebSocket ◄───────────┴── SQLite ◄───────────┘
```

- **Recording:** press **Start recording** before the raid. Every log arcdps finishes writing is
  picked up once its size has been stable for 3 seconds. Logs are parsed one at a time at low
  priority and appear in the UI live. **Import logs** handles logs you already have.
- **Filters:** non-WvW logs and tiny fights (under 20 s, under 5 enemies) are kept as *skipped*.
- **Who was in the fight:** squad members elsewhere on the map (scouts, players running back) are
  excluded from fight analysis. So are the first 3 seconds of boon data, because arcdps can't see
  boons applied before the log started.
- **Enemy boons aren't in WvW logs.** Strip analysis therefore compares strips out vs boons lost,
  and detects squad-wide boon wipes followed by downs.

## GvG mode

In a **GvG**, two guilds fight agreed rounds at an agreed spot. When one commander calls a round
off, both sides stop, walk away and rez everyone, downed enemies included, then regroup for the
next round. Analyzed as a normal zerg fight, that looks like mistakes: "enemy downs escaped",
"downed allies not picked up", a "skirmish" result.

In GvG mode:
- **Call-off:** a round ends at its last second of fighting. Kills up to 3 s after that still
  count.
- **Not counted:** downs still open at the call-off and kills after it are not held against
  either side. The fight page shows them as "left at call-off", and the chart shades what
  follows each call-off and draws left downs hollow.
- **Rounds:** a lull of 25 s or more inside one log starts a new round. Each round has its own
  opening and sustain checks.
- **Result:** each round is won or lost on players taken out (kills plus downs left at the
  call-off). The fight result is the round score. There are no "skirmishes" in GvG.
- **Where to switch it:**
  - Settings → *Fight type* sets the default for new fights.
  - The **GvG** switch in the header changes the same setting, so it can be flipped on before a
    GvG block and off after it.
  - Each fight stores its own mode. **Analyze as GvG / zerg** on a fight or a session page
    re-analyzes it.

The round gap and the grace time can be changed in Settings. Both are first guesses, set without
real GvG logs.

## In-game overlay (Nexus addon)

The overlay shows the analyzer's results in game:

- **Fight tab:** the latest fight's result, map and length, its numbers (kills, deaths, squad,
  enemies; GvG: rounds and players) and one card per issue, critical and major first. Critical
  and major cards are open (the fact, then *Next time* and the fix); minor and context notes
  are one line you can click open. Then what went well and the LLM debrief, if one was written.
  Older fights of the session with **<** / **>**, back to the newest with **Latest**.
- **Session tab:** record, kills, deaths and KDR, one square per fight (click one to open it),
  the recurring problems with how often they showed up, and the strengths.
- **After a fight:** a small panel with the result and the top three problems. It hides when
  combat starts; **Open debrief** opens the full window on that fight.
- A **Start / Stop** recording button in the window's header.

- **Requirements:** [Raidcore Nexus](https://raidcore.gg/Nexus) (it also loads arcdps), and
  WvW Analyzer 0.5.0 or newer running on the same PC. Players using arcdps without Nexus aren't
  supported yet.
- **Install:** Settings → *In-game overlay* → **Install**, with the game closed. The Guild Wars 2
  folder is found automatically for the standard and Steam default folders (otherwise enter
  it). The app copies `WvWAnalyzer.dll` into `<Guild Wars 2>\addons`
  and nothing else. **Remove** deletes that DLL and the addon's settings folder. After an app
  upgrade the addon is updated on the next start while the game is closed, or with **Update**.
- **In game:** the Quick Access icon or **ALT+SHIFT+W** (rebindable in Nexus) toggles the
  window; drag it by its header. Options in Nexus → Addons → WvW Analyzer: *After a fight*
  (show the small panel, open the full window, or do nothing; only once you're out of combat),
  *Size* (100%, 115% or 130%: text and window together), hide the window in combat, background
  opacity. The text uses Inter and follows the game's interface size.
- **Timing:** a fight shows up once the app has analyzed its log, usually within half a minute
  of the fight ending. The window follows the current session; while you browse older fights,
  **Latest** goes back to the newest one.
- **What it does and doesn't do.** It only draws a window through Nexus. Everything in it comes
  from the WvW Analyzer app over `127.0.0.1`, which works from finished arcdps logs like Elite
  Insights does. The only game state it reads is MumbleLink's "in combat" flag (ArenaNet's
  official interface, provided by Nexus), to hold back the auto-show. It doesn't read game
  memory, send keys or chat, or connect anywhere else.
- **At your own risk.** ArenaNet doesn't approve any third-party add-on, including arcdps and
  Nexus. The overlay adds nothing beyond what that setup already does, but using it is your
  decision.

## Detectors

| Detector | Finds |
|---|---|
| `stab_gap_deaths` | Down bursts that hit parties with low stability coverage |
| `boon_wipe` | Squad boons collapsing within seconds, followed by downs |
| `strip_balance` | Boons lost vs strips dealt; too few strippers |
| `early_cascade` | Several downs early, before the enemy lost anyone |
| `downstate` | Allied downs not rallied; enemy downs not converted to kills |
| `cleanse_pressure` | Many conditions on the squad; downs while carrying many conditions |
| `sustain_decline` | Healing + barrier vs damage taken dropping in the second half |
| `out_of_position` | Downs far from the tag or the stack |
| `comp_audit` | Parties without stability, cleanses or healing; players in tiny parties |
| `outnumbered` | Enemy count vs squad + nearby allies |
| `player_outliers` | Players far below others of the same profession in that profession's main output |

Thresholds can be edited in **Settings**. Use **Save & re-analyze all** to apply them to every
fight. To change the note wording, copy `backend/wvw_analyzer/notes/templates.yaml` to
`<data dir>/templates.yaml` and edit it.

**Calibrate against your own fights:** `scripts/calibrate.py` prints how often each detector fires
in won vs lost fights, plus metric medians per outcome. On the first 93 fights it was tuned with,
`strip_balance` fired in 71% of losses vs 6% of wins, and `early_cascade` in 46% vs 6%.

## My play

Personal hints are built only from your logs, with no outside data (no builds, no benchmarks):

- **When a log is analyzed**, every squad member gets a set of facts stored with the fight:
  their downs (stability, the party's stability, distance to the tag, other squad downs within
  4 s, health 3 s before, the death recap's skills), time dead, cast time without
  auto-attacks, cancelled casts, dodges, food and utility, top skills dealt and taken, their
  job in that fight (strongest output against the squad) and, per stat, the median of the other
  players with the same spec and job and of the squad. Older fights are re-analyzed once.
- **When the page opens**, the rules run over those facts, so changing a rule in Settings needs
  no re-analysis:

  | Rule | Fires when | On by default |
  |---|---|---|
  | `me_deaths` | your downs per minute are well above the rest of the squad's in the same fights (at least 1.5x and unlikely by chance), overall or on one spec | yes |
  | `me_low_output` | on a spec, your main job's output is below 65% of other players with that spec and job (median over fights with 2+ of them); above 140% is a strength | yes |
  | `me_low_activity` | on a spec, your cast time without auto-attacks is below 75% of those players'; above 135% is a strength | yes |
  | `me_no_food` | a quarter or more of your fights without food or a utility | yes |
  | `me_down_no_stab`, `me_down_far`, `me_caught_alone`, `me_first_down` | a cause of your downs (no stability while your party had it, far from the tag, picked off alone, among the first down) is well above the squad's share | no |
  | `me_far_from_tag`, `me_cc_taken` | much farther from the tag than the squad in most fights; CC'd far more than the squad with less stability than your party | no |

  The rules that are off by default fired for almost nobody, or no more often than chance, on
  the fights they were calibrated on. The down-rate hint still names a cause when one stands
  out, and **Your downs** shows how your downs split next to the squad's.
- **Same fight twice:** when two logs cover the same fight (a friend's log next to yours), the
  one the player recorded counts. A player split by Elite Insights into several rows in one
  fight counts once. Fights you led count for survival and food only (a commander has no
  distance to the tag and no peers).
- **Calibrate against your own logs:** `scripts/calibrate_personal.py` runs every rule over
  every player in a folder of EI JSON and prints how often each fires, how often a player's job
  changes between fights on one spec, and the recording player's profile.

## Replay and videos

Watch any fight again on the map, and, when you have a recording of it, the video at the same
moment. Recordings can be linked by hand, or by the app itself when it is connected to OBS.

### Replay a fight

1. Open a fight and pick the **Replay** tab. It works for every fight, also older ones.
2. **Play / Pause** (space), **◀ 5s / 5s ▶** (← / →), speed 0.5× to 4×, or drag the slider.
3. On the map:
   - dots are players in their profession's color, ringed blue (squad), green (allies not in
     the squad) or red (enemies; the logs don't name them, so they show their spec);
   - an orange ring is a downed player, ✕ a dead one, the yellow diamond the commander's tag,
     and the small tick the way your squad and allies face;
   - hover a dot for the name, scroll to zoom, drag to pan, **Fit** to see the squad again,
     **Follow tag** to keep the commander in the middle, and pick a party to dim the others.
4. Eternal Battlegrounds, the Alpine and Desert Borderlands and Edge of the Mists can show the
   real map: click **download the map images** under the map (about 8 MB, once; also in
   Settings > Replay and videos). Seared Borderlands has no map image and shows a grid. On every
   map, the bar bottom left shows a distance in game units ("range").

**Jump to a moment:** click anywhere on the Debrief's fight timeline, or a **▶ Replay** link
on a finding, in the Positioning tab's downs or on the You tab. The replay opens 3 s before the
moment (change it in Settings > Replay and videos). Back returns to where you clicked, and the
address keeps the moment, so a reload or a copied link opens it there.

### Set up OBS (optional, once)

With OBS connected, the app's **Record** button starts and stops OBS, and every recording links
itself to its fights. OBS 28 or newer has what's needed built in; no plugin.

1. In OBS: **Tools > WebSocket Server Settings**, tick **Enable WebSocket server**, **Apply**.
2. Still there, click **Show Connect Info** and copy the **Server Port** and **Server Password**.
3. In the app: **Settings > Replay and videos > OBS connection**. Tick **Connect to OBS**, enter
   the port (usually 4455) and paste the password.
4. Click **Test connection**: it should say "Connected to OBS" and its version. Then **Save**.

The header now shows the OBS state next to the Record button: **OBS ready**, **OBS recording**,
**OBS paused**, **OBS not running** or **OBS: password?**. The app only talks to OBS on this PC
(127.0.0.1), and the password stays in your settings file; the app never shows it again.

### A raid evening with OBS

1. Start OBS with your usual scene.
2. Press **Record** in the app (or let auto-record start it with the game). OBS starts
   recording too.
3. Play.
4. Press **Stop** in the app (or close the game when auto-record is on). OBS stops, and the
   recording is linked to every fight it covers.
5. Open a fight > **Replay**: the map and your video, at the same moment.

Good to know:

- The app only stops a recording it started. If you start recording in OBS yourself, the app
  links it but leaves it running.
- Pausing in OBS and OBS splitting long recordings into several files are both handled.
- If the app was closed while OBS kept recording, the next start shows "OBS is still recording
  from the last session" with **Stop OBS recording** and **Keep recording**.
- Two switches in Settings: **Start and stop OBS recording with the app's recording** (off: you
  start OBS yourself), and **Link OBS recordings to their fights automatically (also ones you
  start in OBS)** (off: only the ones the app starts are linked).

### Keep OBS recordings small

The app doesn't change OBS's settings: how big a recording gets is up to your OBS. WvW is hard
on video encoders (hundreds of players and effects on screen), and quality presets such as
"Indistinguishable Quality" or recording at 1440p / 4K can write 20 GB or more per hour. To
review fights, 1080p at a capped bitrate is plenty:

| Bitrate | Per hour | 3-hour evening |
|---|---|---|
| 6000 Kbps (AV1) | about 2.7 GB | about 8 GB |
| 10000 Kbps (H.264) | about 4.5 GB | about 14 GB |
| 44000 Kbps (what 50 GB for 2.5 hours means) | about 20 GB | about 60 GB |

**How the app helps:** while OBS records, the app measures how much it writes. Above the limit
(10 GB per hour by default) the header chip turns amber, for example **OBS recording · 20 GB/h**.
**Settings > Replay and videos > OBS connection > Recording size** shows the current or last
recording's rate and the limit (0 turns the warning off). Check it after a minute of recording
to see what a settings change did.

**Choose the encoder.** A hardware encoder costs the game almost no frames:

- **AV1** if OBS lists it: NVIDIA NVENC AV1 (RTX 40 and newer), AMD HW AV1 (RX 7000 and newer)
  or QuickSync AV1 (Intel Arc). Smallest files for the same picture.
- Otherwise **H.264**: NVIDIA NVENC H.264, AMD HW H.264 or QuickSync H.264. x264 (the CPU) works
  but takes frames from the game.
- Not **HEVC / H.265**: the app's window can't play it.

**OBS Simple mode** (Settings > Output, Output Mode: Simple):

1. **Recording** section: **Recording Quality: Same as stream** (the recording then uses the
   bitrate below), **Recording Format: Matroska Video (.mkv)**.
2. **Streaming** section: **Video Encoder** as above, **Video Bitrate: 10000** for H.264 or
   **6000** for AV1.
3. If you also stream with this OBS, the stream gets the same bitrate. Most stream sites take
   about 6000 Kbps at most, so 6000 suits both; or use Advanced mode, which keeps them apart.

**OBS Advanced mode** (Settings > Output, Output Mode: Advanced), **Recording** tab:

1. **Type: Standard**, **Recording Format: Matroska Video (.mkv)**, **Video Encoder** as above.
2. **Rate Control: CBR** (or VBR), **Bitrate: 10000** for H.264 or **6000** for AV1.
3. Leave the preset and the other encoder options as they are.

**Resolution and frame rate** (Settings > Video): playing at 1440p or 4K, set **Output (Scaled)
Resolution: 1920x1080**. **Common FPS Values: 30** halves the size again if you don't need
smooth motion.

MKV survives a crash or a full disk (an MP4 cut short can't be opened) and plays in the app. To
get an MP4 for sharing, use **File > Remux Recordings** in OBS: it is quick and keeps the
quality.

### Without OBS: link recordings yourself

Any recorder works: NVIDIA ShadowPlay, Windows Game Bar, OBS without the connection, or a video
a squad mate sends you.

1. Open the session and pick the **Videos** tab.
2. **Recordings from this session** lists the videos in your Videos folder (and one level of
   subfolders) whose time covers the session's fights. Click **Link**, or **Link all** (it shows how
   many). Other folders: Settings > Replay and videos > Recording folders.
3. Or click **Choose video files…** (in the app window), or paste a file's path and **Add path**.
4. Give it a label if you like ("Me", a squad mate's name).

The app reads the start time from the file name (OBS, NVIDIA and Game Bar names) or the file's
creation time, to about a second. Videos stay where they are: the app never copies, changes or
deletes them, and **Unlink** only removes the link. Fights with a linked video show a camera icon
in the fight lists.

### Fix the sync

A video can be a second or two off, or more for a squad mate's video (their PC clock or time
zone differs). Fix it once per video; it then fits every fight in that video.

- **−0.5s / +0.5s** (on the Replay tab or the session's Videos tab) moves the video in half
  seconds.
- **Sync here** fixes it exactly: in the replay, go to a moment you can recognize in the video
  (a down is easy: click its ▲ on the timeline), click **Sync here** on the video, scrub the
  video with its own controls to that same moment, and click **Save sync**.

A video marked **approximate** may be further off: use Sync here on it.

### Several videos

All videos that cover a fight play side by side, in step: one big, the others small. Click a
small one to make it the big one; only the big one has sound. **Map / Video / Both** switches
what the Replay tab shows.

### When something is off

| You see | Why | What to do |
|---|---|---|
| **OBS not running** in the header | OBS is closed, or its WebSocket server is off | Start OBS; check Tools > WebSocket Server Settings |
| **OBS: password?** | The password is missing or wrong | Copy it again from Show Connect Info, paste it in Settings, Save |
| **OBS recording · 20 GB/h** in amber | OBS writes more per hour than the limit in Settings | Lower OBS's bitrate or resolution: [Keep OBS recordings small](#keep-obs-recordings-small) |
| The video stays dark with a note about its format | The window can't read it: often HEVC / H.265, or a container it can't open | In OBS: File > Remux Recordings to MP4 (fixes the container), or record with H.264 or AV1 (fixes HEVC) |
| The video is a few seconds off | Times in file names are to the second; another PC's clock | −0.5s / +0.5s or Sync here |
| **file not found** on a video, or "could not be loaded" on the Replay tab | The recording was moved or renamed | Unlink it and link it again from its new place |
| "starts … after / ends … before this moment" on a video | That recording doesn't cover this moment | Nothing; another video or fight may have it |
| No camera icon on a fight | No linked video covers its time | Link the recording on the session's Videos tab |
| The map shows a grid | Seared Borderlands, or the map images aren't downloaded | Download them in Settings > Replay and videos |

## LLM debrief tuning

`scripts/llm_bench.py` compares prompt variants (`backend/wvw_analyzer/llm/prompts.py`) for the local
model:

- **Automatic checks:** ranking kept, fixes carried over, no invented numbers or names, no padding,
  format.
- **Reference comparison:** similarity to reference debriefs written by Claude (Opus 5.5).
- **Graded reads:** Claude's grades of every output, stored in `data/llm_bench/judgments-*.yaml`.

```bash
uv run python scripts/llm_bench.py prepare            # pick 30 fights from data/dev_corpus (--mode gvg)
uv run python scripts/llm_bench.py run --variants v8_header --temps 0.1 [--server PATH --ngl 99]
uv run python scripts/llm_bench.py sheet <results.jsonl>   # side-by-side sheet for grading
uv run python scripts/llm_bench.py report <results.jsonl ...>
```

Current default: `v8_header` at temperature 0.1. Code writes the result line, the framing (for
example "Clean win, only small things to tidy up") and a one-line fact and fix per problem. The model
only turns these into chat bullets, which removed the paraphrasing errors smaller prompts made
("downed" turned into "died", numbers mixed up).

| Prompt | Claude's grade (out of 10) |
|---|---|
| `v8_header` | 10.0 |
| `v7_short` | 9.6 |
| `v6_framed` | 8.4 |
| `v5_anchored` | 7.3 |
| `v1_json` (original) | lowest automatic score |

## Development (WSL / Linux)

```bash
uv sync                                        # Python 3.12 + deps
uv run python scripts/setup_tools.py           # Elite Insights CLI -> ./bin (add --llm for llama + model)
cd frontend && npm install && npm run build    # UI (or `npm run dev` for hot reload on :5173)
uv run wvw-analyzer --no-window                # http://127.0.0.1:8765
uv run pytest                                  # tests (+ corpus test if data/dev_corpus has EI JSON)
```

The in-game overlay addon (`addon/`, Rust) is cross-compiled from WSL to a Windows DLL with
[cargo-xwin](https://github.com/rust-cross/cargo-xwin). It needs rustup with the
`x86_64-pc-windows-msvc` target, `cargo install cargo-xwin`, and clang-cl + lld-link (LLVM 18+;
set `LLVM_BIN` if they aren't on `PATH`):

```bash
scripts/build_addon.sh                         # -> bin/addon/WvWAnalyzer.dll
cd addon && cargo test && cargo clippy         # model, client, settings and view tests run on Linux
cd addon && cargo run --example preview        # every overlay state as PNGs in addon/target/preview/
```

The preview draws the overlay with the addon's own drawing code in a headless ImGui and a small
CPU rasterizer, from synthetic payloads. It shows layout, wrapping and colors without the game;
it is not pixel-identical to it.

From WSL, the Windows `GuildWars2EliteInsights-CLI.exe` runs through interop. It needs the
.NET 10 runtime on Windows. Dev data (config, DB, EI cache) lives in `./data`.

## Install (Windows 10/11)

Run `WvWAnalyzer-Setup-<version>.exe`.

- **No admin rights needed.** It installs for your user only, in
  `%LOCALAPPDATA%\Programs\WvW Analyzer`, and creates a Start menu entry (a desktop shortcut is
  optional).
- **Nothing else to install.** The log parser (Elite Insights) and its private .NET runtime are
  included and nothing is installed system-wide. The installer only adds Microsoft WebView2 on
  the rare Windows install that lacks it.
- **SmartScreen warning:** the installer isn't code-signed, so Windows says "Windows protected
  your PC". Click **More info → Run anyway**.
- **First launch** shows a short setup screen: the arcdps log folder (usually found
  automatically), a parser check, and an optional download of the AI debrief model.
- **Updates:** from 0.8.0 on, the app checks GitHub for a newer release when it starts and once a
  day, and shows a banner. **Install and restart** downloads the update, checks that it is a
  release signed by the app's author, closes the app, runs the installer and starts the app
  again. Nothing is downloaded until you click. The check sends one request to GitHub (two more
  for the small signed manifest when a new version is out), with no account, folder or fight
  data. Turn it off in **Settings > Updates** (that also hides the banner). If an
  update doesn't finish, the next start offers to run the installer again.
- **Upgrading by hand:** run the newer setup. It closes the running app and keeps all your data.
  0.7.0 and older have no updater, so install the first version with it by hand.
- **Uninstalling** (Windows *Apps & features*) asks whether to also delete your analyzed fights
  and settings in `%LOCALAPPDATA%\WvWAnalyzer`. The default is to keep them. Your arcdps logs are
  never touched.

## Troubleshooting

If something goes wrong, open **Settings > Troubleshooting** and click **Copy diagnostics**,
then paste the result into a message to whoever helps you. It holds the app version, the setup
checks, recent errors and crashes, and the end of the app log, with your Windows user name and
account names removed. The diagnostics are never sent anywhere automatically. The same report is saved as
`diagnostics.txt` in `%LOCALAPPDATA%\WvWAnalyzer` (**Open app folder**). Each app start
writes its own log in the `logs` folder there, so the log of a run that crashed is still there
after a restart. Logs are kept for 14 days (at most 30 runs and 100 MB).

When the app crashed or closed unexpectedly, a banner offers the same button on the next start.

## Building the app and installer

Requires uv, Node.js 22.17+ (or `-SkipFrontend` with a prebuilt `frontend/build`) and Inno Setup 6
(`winget install JRSoftware.InnoSetup`). The overlay addon is built in WSL first
(`scripts/build_addon.sh`); copy `bin/addon/` along with the repo. In PowerShell, from the repo
root:

```powershell
./scripts/build_windows.ps1                # -> dist\WvWAnalyzer-Setup-<version>.exe
./scripts/build_windows.ps1 -NoInstaller   # only dist\WvWAnalyzer\ (portable folder)
```

The build does the following:
- downloads the pinned Elite Insights, .NET runtime and WebView2 bootstrapper, verifying their
  checksums or signature;
- builds the app with PyInstaller and bundles `bin\addon\WvWAnalyzer.dll`;
- compiles `packaging/installer.iss`.

### Releasing (signed for the in-app updater)

The app installs only a release whose `latest.json` is signed with a key listed in
`TRUSTED_KEYS` in `backend/wvw_analyzer/updater.py`. Once, in WSL:

```bash
uv run python scripts/release_sign.py keygen   # passphrase-protected key in ~/.wvw-analyzer/
```

Paste the printed public key into `TRUSTED_KEYS`, and back up the key file (never commit it).
Per release, after building the installer on Windows and copying it back to `dist/`:

```bash
uv run python scripts/release_sign.py sign dist/WvWAnalyzer-Setup-X.Y.Z.exe
gh release create vX.Y.Z dist/WvWAnalyzer-Setup-X.Y.Z.exe dist/latest.json \
    dist/latest.json.sig --notes-file notes.md
```

The release notes are shown in the app ("What's new"), as plain text. A release without the two
manifest files is still announced, with a link to the release page only. To test updates
against a local server, set `WVW_UPDATE_API` (the release JSON URL) and `WVW_UPDATE_TEST_KEY` (a
test public key; honoured only together with `WVW_UPDATE_API`).

The version comes from `backend/wvw_analyzer/__init__.py`.

## Layout

- `backend/wvw_analyzer/ingest`: recorder (folder watch), processor queue, EI runner, loader
- `backend/wvw_analyzer/metrics`: stat columns, per-second timeline, summary, session aggregation
- `backend/wvw_analyzer/detectors`: rules producing findings
- `backend/wvw_analyzer/coach`: personal rules and the review served to My play
- `backend/wvw_analyzer/notes`: ranking, merging and templates
- `backend/wvw_analyzer/llm`: llama-server lifecycle and debrief prompt
- `backend/wvw_analyzer/api`: FastAPI REST and WebSocket; serves the built UI
- `backend/wvw_analyzer/addon_install.py`: install, update and remove the in-game overlay
- `backend/wvw_analyzer/replay.py`, `videos.py`, `obs.py`: replay data, linked videos, the
  optional OBS connection
- `backend/wvw_analyzer/updater.py`: update check, signed manifest, download and installer
  hand-off (`scripts/release_sign.py` signs releases)
- `addon/`: the in-game overlay, a Rust Nexus addon (nexus-rs); `src/view` draws it,
  `examples/preview` renders it to images
- `frontend/`: SvelteKit + Tailwind + ECharts
- `scripts/`: tool setup, calibration, addon and Windows builds, release signing
- `packaging/`: PyInstaller spec, Inno Setup script, icon
- `docs/`: decisions (`DECISIONS.md`) and the approved plans (`plans/`)

## Credits

- The in-game overlay uses the [Inter](https://rsms.me/inter/) typeface by The Inter Project
  Authors, under the SIL Open Font License 1.1 (`addon/assets/fonts/OFL.txt`, shipped as
  `bin/addon/Inter-OFL.txt`). It is subset to Latin and Latin Extended.
