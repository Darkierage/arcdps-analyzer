# WvW Analyzer: in-game overlay redesign plan

> **Status:** approved 2026-11-25, amended after a plan review the same day (debriefs survive a
> version bump, tiles that don't fit, fonts in practice, small-panel rules); not implemented yet.

## Context

Players like the in-game overlay most: it shows the debrief without alt-tabbing. It was built
as a small feature (plan 05) and looks it: every line is plain text at one size, with the
default spacing, so the window reads as compressed and flat. Two things are wrong beyond looks:

- **Order.** Critical and major notes are not always on top. `notes/ranker.py` treats critical
  and major as one group and orders by impact inside it, and does the same for minor and
  context. In the dev data, 3 of the 29 fights with issues are out of severity order (2 with a
  major above a critical, 1 with a context note above a minor).
- **Pop-up size.** After every fight the full window opens, though most of the time the result
  and the top problems are all a player wants between fights.

What was checked before planning:

- **The platform is not the limit.** The overlay is already its own Nexus addon. The ImGui
  bindings it links (ImGui 1.80, `arcdps-imgui` 0.8 through nexus-rs) have draw lists (rounded
  filled boxes, lines, circles, images), tables, style and font stacks, hover and click areas,
  and windows without a title bar. Nexus loads fonts an addon bundles (`font` API) and shares
  its UI scale (`NexusLink.scaling`). Blur and drop shadows don't exist; the design uses none.
- **Other platforms were turned down.** An arcdps extension uses the same toolkit with fewer
  services. A standalone transparent web window would allow HTML/CSS, but click-through and
  focus handling over a game are unreliable with WebView2 and it is a much heavier thing to
  keep over the game. A Blish HUD module needs Blish HUD and C#.
- **The UI can be previewed without the game.** A spike on 2026-11-25 built `arcdps-imgui`
  0.8.0 on Linux and ran a headless frame (context, font atlas, a window with a rounded box
  and text) down to draw data. So the addon's drawing code can run in a test program.

The look was agreed on mockups (direction "A, cards"): the fight tab for a win, a loss and a
clean win, the two empty states, the session tab and a small panel shown after a fight. The
mockups are HTML drawn only with things ImGui can do; this plan's "Design" is the reference
where they differ.

## Design

### 1. Order of notes (analysis change)

- `ranker.rank` sorts the kept issues by `(SEVERITY_ORDER[severity], -impact)`: critical,
  major, minor, context, and by impact inside each. The merge step before it is unchanged.
- The top five and `more` follow the new order, so which five are kept can only change between
  minor and context notes. `summary.topIssue` and `topSeverity` follow too.
- `ANALYZER_VERSION` goes to 8; stored fights are re-analyzed on startup.
- **Debriefs survive a version bump.** The keep rule in `store/db.py` compared the whole
  summary, which carries `analyzerVersion`, so every bump dropped every stored debrief (and
  auto-debrief only rewrites the latest recording session). The comparison now leaves
  `analyzerVersion` out: a debrief is dropped only when its notes or the other summary fields
  changed. Covered by a test. (Added in the plan review.)
- The app's fight page and the LLM prompt take the order as given; neither changes. The prompt
  text is untouched, so no benchmark run is needed.

### 2. Payload (`/api/overlay`, schema stays 1)

The addon stays a dumb renderer: every string is written by the analyzer. Fields are only
added, so an older addon keeps working, and the new addon falls back to `title` and
`resultLine` when the new fields are missing (an older app).

- `fight.badge`: the result word for the badge (`WIN`, `LOSS`, `EVEN`, `SKIRMISH`; GvG adds
  the round score, as its result line does).
- `fight.heading` (map) and `fight.meta` (`20:03 · 12:54 long`).
- `fight.facts`: up to four `{label, value, note, tone}` tiles. Zerg: Kills, Deaths, Squad
  (`note`: `+2 allies`), Enemies. GvG: Rounds, Kills, Deaths (counted ones, as in
  `gvg_result_line`), Players (`15 vs 15`). `tone` is `good`, `bad` or empty.
- `fight.headline` (`73 kills for 29 deaths`) and `fight.numbers` (`28 vs 59`) for the small
  panel.
- `fight.issuesTitle`: `Why this fight was lost`, `What to improve` or `Key issues`, the same
  wording as the app's fight page.
- `fight.moreCount`: how many issues the app has beyond the ones sent.
- `session.strip`: the session's analyzed fights, oldest first, as `{id, result, letter}`.
- `session.problems[].severity` becomes the worst severity seen across the problem's
  occurrences (today: the first fight's). Computed in `overlay.py` from the occurrences;
  `aggregate_session` and the app's session page are untouched.

### 3. Addon structure

- `arcdps-imgui` 0.8.0 (`tables-api`) becomes a direct dependency on every target. It is the
  crate nexus-rs uses, so the types are the same.
- Drawing moves to a platform-independent `view` module: `theme` (colors, metrics, fonts),
  `widgets` (card, chip, stat tile, bar, tab switch, icon button), `fight`, `session`,
  `glance`, `states`. `ui.rs` keeps the Nexus glue: windows, font registration, settings,
  actions.
- Decisions that aren't drawing are plain functions with unit tests: which cards start open,
  the small panel's show and hide rules, the settings migration, capitalizing a fact.
- **Preview program** (`cargo run --example preview`): creates a headless ImGui context, loads
  the bundled fonts, draws every state from synthetic fixture payloads with the same `view`
  code, turns the draw data into images with a small CPU triangle rasterizer (vertex color
  times font-atlas alpha, clip rectangles, alpha blending) and writes PNGs under
  `addon/target/preview/`. It shows layout, wrapping, sizes and colors; it is not
  pixel-identical to the game (Nexus's renderer and UI scale differ).

### 4. Look

- **Colors.** Window `#15171c` (at the opacity setting), header band `#1b1e25`, card
  `#1e222a`, hovered or opened-by-click card `#232832`, lines `#2a2f3a`, active tab `#303744`,
  button border `#3a4150`; text `#e6e8ec`, secondary `#c9ced8`, muted `#9aa3b2`.
- **Severity** (text / chip fill): critical `#ff8080` / `#ff6b6b` at 16%; major `#ffb066` /
  `#ffa348` at 16%; minor `#e8d470` / `#e8d15a` at 14%; context `#9aa3b2` at 14%; positive
  `#6fdc8c` / `#5fd47a` at 16%. Results use the same green, red and yellow. Severity is always
  written as a word too, never shown by color alone.
- **Type.** Inter (SIL Open Font License, bundled with its license file): Regular 12 and 13;
  SemiBold 11 (chips, badges and section labels, upper case), 13 (card titles, open or closed,
  and the small panel's headline), 15 (heading and the empty-state titles) and 18 (stat
  values). The mockups' Medium, Bold and 14 px map onto these. Sizes are multiplied by Nexus's
  UI scale. Until Nexus hands a font over, the current font is used. Glyphs: Latin and Latin
  Extended.
- **Fonts in practice.** The static `Inter-Regular.ttf` and `Inter-SemiBold.ttf` (ImGui 1.80
  ignores a variable font's axes). The OFL text ships in the repo and with the installer. Nexus
  hands back a raw `ImFont` pointer, which imgui-rs's `FontId` can't wrap, so fonts are pushed
  with `imgui::sys::igPushFont`/`igPopFont`; the preview uses the same path with its own atlas.
  A UI scale change calls `resize_font` for each font. Fonts are added with
  `FontDataOwnedByAtlas = false`, so ImGui never frees the bytes embedded in the DLL.
- **Metrics**, in font-size units so they follow the scale: window padding 12, card padding
  10 by 12, radius 6 (chips 4), 6 between cards, four equal stat tiles with a 6 gap.
- **Stat tiles that don't fit** (a record like `4W 2L 1E 1S`, `15 vs 15` at 360 wide): a
  tile's note goes on its label line ("Squad · +2 allies"); a value still too wide for its tile
  drops to the 15 heading size, and only then is clipped.
- **Window.** No native title bar. A header row carries the name, the queue state
  ("Analyzing (2 queued)"), the recording state with Start/Stop, and Close. Without the app
  the header shows "Not connected" with a gray dot and no Start/Stop. Default size 460 by 600
  (existing users keep their saved size: the window id `###wvw_analyzer` stays), minimum 360
  by 200. The header, the tab switch and the result block stay put; the list under them
  scrolls.

### 5. Fight tab

- Tab switch (Fight, Session) on the left; older, "Fight n of N", newer and **Latest** on the
  right, with today's rules.
- Result block: badge, heading, meta, then the stat tiles.
- A section label (`issuesTitle`) with the number of cards shown, or the framing line when the
  analyzer sends one ("Clean win, only small things to tidy up:").
- One card per issue: severity chip, title, the fact, a line, then "NEXT TIME" and the fix.
  - Critical and major cards start open. Minor and context cards start as one line (chip,
    title, chevron). If a fight has nothing serious, its first card starts open.
  - A click on a card's header opens or closes it. The state is kept per fight while the game
    runs and is not saved.
  - The fact's first letter is capitalized by the addon; templates stay as they are.
  - A title keeps its time when the template writes one ("... (12:28)").
- "N more in the app" under the cards when `moreCount` is above zero.
- "WENT WELL" with one card per positive (green dot, title, fact).
- The LLM debrief stays a closed row at the bottom, with today's "couldn't be checked" note.
  It is the last item inside the scrolling list, so it can open.
- States: app not running, a problem message from the app, no analyzed fights yet. Each is a
  centered title with one muted line under it.

### 6. Session tab

- Meta line: session name and fight time. Tiles: record with the fight count, Kills, Deaths,
  KDR.
- A strip of the session's fights, one small square per fight with its result letter and
  color, wrapping onto more lines. A click opens that fight on the Fight tab.
- Recurring problems keep the analyzer's order (how often they show up in losses). Each is a
  card with the worst-severity chip, the title, "3 of 7 · 2 lost" and a bar for the share of
  fights. Strengths are rows with "4 of 7 fights".

### 7. Small panel after a fight

- A second window: no title bar, sized to its content (360 wide), movable, and it never takes
  keyboard focus.
- Content: badge, `headline`, `numbers`, the first three issue titles with their severity
  word, "N more" when there are more, **Open debrief** and a dismiss button.
- It shows when a new fight has been analyzed (today's `NewFights` rule), the player is out of
  combat and the full window is closed. It hides when combat starts, on dismiss, and on Open
  debrief, which opens the full window on the newest fight. A newer fight replaces its content.
- It shows only once the payload's fight is the newest one (no flash of the fight before). It
  also hides when the full window opens. A hide by combat or dismiss is for that fight: the
  panel doesn't come back after combat, only for a newer fight.
- With the full window open, a new fight only moves it to the newest fight, as today.
- **Setting** "After a fight": show the small panel (default), open the full window, or do
  nothing. It replaces "Show the window when a new fight is analyzed": a saved `false` becomes
  "do nothing", anything else becomes the small panel.
- "Hide the window in combat" and the opacity slider keep working for the full window.

## Not in this plan

- A standalone overlay window, a Blish HUD module or an arcdps extension.
- Charts, player names or per-player rows in the overlay.
- Opening the app's fight page from the overlay.
- Translations and fonts for non-Latin scripts.
- Changing how the session ranks recurring problems, or the app's pages.

## Steps

1. **Order.** The ranker change with a test (a major with more impact than a critical; a
   context note with more impact than a minor), `ANALYZER_VERSION` 8, and a before/after
   snapshot of `data/dev_corpus`: only the order of notes, which minor and context notes make
   the top five (versus `more`), `topIssue`, `topSeverity` and `analyzerVersion` may differ.
   The debrief keep rule ignores `analyzerVersion`, with a test.
2. **Payload.** The new fields, `tests/test_overlay_api.py` (zerg and GvG facts, the strip,
   worst severity, the old fields still present), the fixture regenerated.
3. **Groundwork.** The direct `arcdps-imgui` dependency, the `view` and glue split with no
   visible change, and the preview program drawing today's window. This proves the preview
   before any redesign depends on it.
4. **Fight tab.** Fonts, theme, widgets, the header, the fight tab and its states, checked
   against the mockups in the preview images.
5. **Session tab and small panel.** Including the setting, its migration and the options
   section.
6. **Finish.** `cargo clippy` for both targets, `scripts/build_addon.sh`, the version bump in
   the four files, `README.md` (overlay section, the Inter credit), `DECISIONS.md` and this
   plan's status line.

## Validation

- **Python:** the ranker test, the overlay API tests, the corpus tests and the snapshot
  compare.
- **Rust (Linux):** fixture parsing with the new fields and without them (older app), the
  default-open rule, the small panel's show and hide rules, the settings migration, and the
  preview program producing an image for every state without a panic.
- **Preview images** compared with the mockups by eye: order, wrapping at 360 and 460 wide,
  long titles, five open cards (scrolling), a session with many fights (the strip wraps).
- **In game (needs the player):**
  - the fonts are sharp at their UI scale;
  - the window drags by its header (if Nexus only allows dragging by a title bar, the native
    title bar comes back and the status row moves under it);
  - the small panel appears after a fight without taking keyboard focus, and hides when combat
    starts;
  - the full window scrolls, resizes and hides in combat;
  - the options section saves, and an existing `settings.json` migrates;
  - frame time is unchanged with the window open.
