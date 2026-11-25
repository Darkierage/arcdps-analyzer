# WvW Analyzer: overlay redesign review fixes

> **Status:** approved 2026-11-25 (user: "fix all what is needed", with the recommended options
> for F1 and F4); implemented and committed 2026-11-25, as planned. A first look in game
> (2026-11-26) found the fonts built too large by Nexus and a flooded Nexus.log; both fixed
> after this plan, see DECISIONS "Overlay: first look in game".

## Context

A full review (`/review-changes full`, performance, security and use cases) of plan 14's branch
found two medium and four low issues. Analysis output doesn't change: no corpus snapshot or
`ANALYZER_VERSION` bump is needed.

## Fixes

- **F1, session lists pushed out (medium).** The session tab kept the tiles and the whole fight
  strip fixed above the scrolling list. With a long session or a short window (90 fights at
  360 by 420, about 40 near the 200 minimum) the list got no height. Decided: the strip moves
  into the scrolling list; only the tiles stay fixed, like the fight tab's result block.
- **F2, font memory after an unload (medium, plausible).** The font bytes
  (`FontDataOwnedByAtlas = false`) and the glyph ranges handed to Nexus pointed into the DLL's
  static data. If Nexus keeps a font after the addon is unloaded or hot-reloaded, a later atlas
  rebuild would read freed memory. Fix: hand Nexus copies on the process heap (and the font
  config as a heap copy too), leaked on purpose, so they outlive the DLL. About 80 KB per load.
- **F3, long unspaced words (low).** Cutting a word wider than the line re-measured the prefix
  one character at a time (roughly cubic); a 1,800-character LLM debrief line cost about 11 ms
  per frame. Fix: one pass that adds up character widths.
- **F4, record hidden by the ellipsis (low).** `21W 12L 5E 2S` showed as `21W…` at 360 wide.
  Decided: a tile value too wide at 15 px wraps at spaces onto more lines (the row of tiles
  grows); only a single word too wide is clipped. The whole-word ellipsis goes.
- **F5, "dumb renderer" wording (low).** DECISIONS listed only some of the strings the addon
  writes. It now lists them all (session tiles' fight count and KDR format, "3 of 7 · 2 lost",
  "4 of 7 fights", "N more in the app", the small panel's "N more · …", "Fight n of N",
  "Analyzing (N queued)").
- **F6, wrong comments (low).** Chip padding (7 by 2, badges 8 by 3) and the window style's
  lifetime (pushed for the whole window, so the lists' scrollbars use it).

## Validation

- Rust tests: cutting a very long word (pieces fit, nothing lost, fast), a too-wide tile value
  wrapping at spaces, the heap copies (same bytes, not the DLL's statics).
- Preview: a 90-fight session at 360 by 420 (problems reachable by scrolling), the record tile
  at 360 and 460.
- All checks: pytest, ruff, cargo test, clippy for Linux and Windows, the preview, the DLL build.
