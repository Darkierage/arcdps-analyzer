# WvW Analyzer: OBS recording size plan

> **Status:** approved and implemented 2026-11-27 (see `DECISIONS.md`, "OBS recording size").
> Deviation: on stop, OBS's last sample is kept and the finished file is used only without one
> (a row's span can be off); approximate rows never give a rate. After the light review: a
> disconnect ends the live rate, a recording too short to measure leaves no rate, an empty limit
> saves as 0, and the newest OBS file that gives a rate is used after a restart.

## Problem

A user reported 2-3 hour OBS recordings taking about 50 GB (about 20 GB per hour, 44 Mbps).
The app's OBS connection only starts and stops recording; every video setting (resolution,
frame rate, encoder, quality, container) is the user's own OBS profile. Busy WvW footage at a
quality-based setting, or at 1440p/4K, easily reaches that size. Nothing in the app or the
README says what a sensible setting is, or that the files are this big.

## Decision: the user owns OBS's settings; the app guides and measures

The app does **not** change OBS's settings:

- OBS is the user's tool (they may also stream with it); the connection already follows "the
  app only stops a recording it started" and leaves the rest of OBS alone.
- OBS WebSocket can write Simple-mode profile keys and the video size, but not an Advanced-mode
  recording encoder's rate control (that lives in a separate JSON file), encoder ids depend on
  the GPU and the OBS version, and it isn't clear a change applies before OBS rebuilds its
  outputs.
- Re-encoding the files afterwards is ruled out: linked videos are only read, never changed.

Instead:

1. **README guide**, "Keep OBS recordings small": what size to expect per hour, Simple-mode and
   Advanced-mode steps with a bitrate cap, a hardware encoder (AV1 where the GPU has it, else
   H.264; not HEVC, which the window can't play), MKV, and 1080p.
2. **Measure the real rate and warn.** `GetRecordStatus` returns `outputBytes` and
   `outputDuration` (both leave pauses out), so the app knows the GB per hour of what OBS writes,
   whatever the encoder or mode:
   - While OBS records, the worker asks every 30 s; a rate counts once 60 s are recorded.
   - When a tracked recording stops, the rate comes from the finished file: its size over its
     length minus pauses. Otherwise the last sample is kept.
     *(Changed in implementation: the last sample comes first, the file only without one;
     see DECISIONS.)*
   - On connecting while OBS is idle, the newest finished OBS recording's file gives the rate,
     so Settings shows it after a restart.
   - `status()` carries `rate` (`gbPerHour`, `live`, `seconds`) and `rateWarning`
     (rate at or above `obs.warn_gb_per_hour`, default 10 GB per hour; 0 turns it off).
3. **UI:** the header chip turns amber with "· N GB/h" while a recording is above the limit;
   Settings > OBS connection shows "This recording / Last recording: N GB per hour (about M GB
   for 3 hours)", the warning with three short tips and a link to the README guide, and the
   limit field.

No analysis change: no `ANALYZER_VERSION` bump.

## Validation

- pytest against the fake OBS server: the live rate from `outputBytes` / `outputDuration`, no
  rate under 60 s, the warning above the limit and not with 0, the finished file's rate with
  pauses left out, the newest recording's rate on connecting while idle, a recording OBS isn't
  tracked for still measured live.
- `npm run check`, `npm test`, ruff; the zerg path is untouched (OBS only).
