# WvW Analyzer: crash reporting review fixes plan

> **Status:** approved 2026-11-21 (fix all 8 findings; detect Windows shutdowns; rename the
> button), implemented. Fix 2 was refined by plan 11: only a shutdown within minutes of the
> run's last heartbeat counts, not any shutdown after it started.

## Context

A light `/review-changes` run over plan 09 (crash reporting, per-run logs, the pywebview hang
fix) found 2 medium and 6 low issues. The user chose to fix all of them, to keep the
"closed unexpectedly" banner but detect Windows shutdowns, and to rename "Open log folder".

## Fixes

1. **Second launch pushes the crashed run out of the report.** A launch that only shows the
   running app no longer writes a run log: the log file is added after the port check, only for
   the instance that serves. The report picks "this run" as the current process's log and
   orders the others by last write (mtime), not by name (also robust to clock changes).
2. **False "closed unexpectedly" after a Windows shutdown.** Fast Startup keeps
   `GetTickCount64` running, so the boot-time check misses it. On Windows the next start also
   asks the System event log whether the PC shut down or restarted after the run started
   (User32 1074, EventLog 6006/6008, Kernel-General 13, Kernel-Power 41); if so it isn't
   reported. The marker is also removed as soon as the window closes, before the slower
   cleanup (LLM server, uvicorn join).
3. **SIGTERM on `--no-window` skipped cleanup.** uvicorn re-raises the signal after shutdown;
   a SIGTERM handler that raises `SystemExit` lets `finally: end_run` run.
4. **Names with spaces only partly redacted.** The report also removes every account and
   character name stored in the database (players of analyzed fights, commander, POV). The
   `Name.1234` pattern stays as a fallback for names not stored yet.
5. **Old `wvw_analyzer.log` left out after an upgrade.** It is a report candidate like a run
   log (ordered by mtime) and is pruned by the same rules.
6. **Live instance reported as crashed.** Markers are per process (`running-<pid>.json`). At
   start, a marker whose process is still alive (pid and creation time match) is skipped.
7. **Docs:** plan 09 names the real file (`lib/diagnostics.ts`); the docstring says records
   stay until dismissed.
8. **Button:** "Open app folder" (README too).

## Validation

A regression test per fix; pytest, ruff, svelte-check and the build; the event-log query run
once on Windows (read-only) to check its syntax and that it finds a recent shutdown.
