# WvW Analyzer: run heartbeat and second review fixes plan

> **Status:** approved 2026-11-21 (add a heartbeat; fix all five low findings), implemented.

## Context

A second light `/review-changes` run (over plans 09 and 10) found that any Windows shutdown
after a run started hid that run's crash, even when the app died hours before the shutdown:
the friend's case (the app hangs in the evening, gets closed, the PC is shut down for the
night) would show no banner. It also found five small issues. The user chose a heartbeat and
all five fixes.

## Fixes

1. **Heartbeat.** While the app runs, its marker gets `lastSeen` every 2 minutes. At the next
   start a stale marker counts as ended by Windows only if the System event log has a
   shutdown/restart event between `lastSeen` and 5 minutes after it. Off Windows, or if the
   event log can't be read, the boot-time check stays (PC started after `lastSeen`). A hung
   app stops its heartbeat too, so a later shutdown doesn't hide the hang. `end_run` stops the
   heartbeat before removing the marker, so it can't be written again during the cleanup.
2. **Reused pid.** `begin_run` runs before this process writes its marker, so a marker with
   this process's pid is an old run whose pid Windows reused; it is checked like any other.
3. **Redaction order.** Stored player names are replaced before the Windows user name (a
   character name containing it was left half visible), and the `Name.1234` fallback accepts
   non-English letters.
4. **DECISIONS:** remove the stale sentence about the old log being "left alone".
5. **faulthandler reason:** CPython already ignores the CLR's 0xE0434352. The false alarms come
   from exceptions .NET raises and handles itself, such as access violations for null
   references (faulthandler sees them before .NET does). DECISIONS and the code comment say so.
6. **Report:** "Elite Insights: NOT INSTALLED" instead of the expected version when it's missing.

## Validation

Regression tests (heartbeat writes and stops, shutdown inside/outside the window, reused pid,
redaction order and non-English accounts, EI line), all checks, and the windowed event-log
query run once on Windows (read-only).
