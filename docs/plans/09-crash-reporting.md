# WvW Analyzer: crash and error reporting plan

> **Status:** approved 2026-11-21, implemented (not released). Deviations: the WebView version
> comes from the page's user agent, not the registry; worker crash dumps get a footer line
> written by the parent (faulthandler writes no time or context).
> Follow-up (same day): a friend's crash report was reproduced and fixed (the window deadlocked
> on start because pywebview walked the .NET UI through a public `js_api` attribute), and the
> single rotating log became one log per run with retention. See "Follow-up" below.

## Context

Friends now run the installer on their own PCs. When something breaks there, the only trace
is `%LOCALAPPDATA%\WvWAnalyzer\wvw_analyzer.log`, and only for errors the code already
catches (a failed fight, a failed recording scan). Nobody knows the file exists, and several
kinds of failure leave nothing at all:

- Uncaught exceptions: there is no `sys.excepthook` / `threading.excepthook`, and the packaged
  app has no console (`console=False`), so a dying background thread prints to a missing
  stderr. A startup crash only shows PyInstaller's dialog.
- Native crashes (WebView2/pythonnet, an analysis worker killed by the OS): no trace; a dead
  worker shows up as an unclear `BrokenProcessPool` fight error.
- Frontend errors: no `window.onerror` / `unhandledrejection` handler; they stay in a
  WebView console nobody can open.
- No way to hand the information over.

## Design

Everything stays on the PC (no upload service): the user copies a report and sends it
themselves. This keeps the "no network beyond what's needed" stance and doesn't ship other
people's data anywhere.

1. **`backend/wvw_analyzer/diagnostics.py`** (new):
   - `install(data_dir)`: `sys.excepthook` and `threading.excepthook` log the traceback at
     CRITICAL and add a crash record. Off Windows, `faulthandler` writes native crashes to
     `crash.log`. On Windows the main process doesn't use it: pythonnet (pywebview's WinForms
     backend) raises CLR exceptions (code 0xE0434352) that are handled, but faulthandler dumps
     every one of them as a "fatal exception", so the file would fill with false alarms.
   - `begin_run` / `end_run`: `running.json` exists while the app runs. If it is still there
     on the next start, the previous run did not end normally. It counts as a crash only if
     the PC wasn't restarted since (boot time from `GetTickCount64` / `/proc/uptime`), so
     shutting Windows down with the app open is not reported.
   - Crash records in `crashes.json` (last 20; `seen` flag), shown in the UI until dismissed.
   - `worker_init(path)`: analysis workers enable `faulthandler` into `crash.log` (no pythonnet
     there). When a worker dies, the processor appends a line naming the fight and reports
     "The analysis process crashed" instead of `BrokenProcessPool`.
   - `build_report(state, user_agent)`: plain text for a chat message: version, OS, Python,
     WebView (user agent from the page), Elite Insights self-test, LLM state, setup state,
     fight counts by status, the latest failed fights with their errors, crash records,
     Windows Error Reporting / .NET Runtime events for our processes (`wevtutil`, last 30
     days), the end of `crash.log` and the end of the log. Redacted: the user
     folder becomes `%USERPROFILE%`, the Windows user name `<user>`, GW2 account names
     (`Name.1234`) `<account>`.
2. **API** (`api/app.py`), all behind the existing local-only checks:
   - `GET /api/status` gains `crashes` (unseen records).
   - `POST /api/diagnostics` builds the report, saves `diagnostics.txt` next to the database
     and returns `{text, path}`.
   - `POST /api/diagnostics/open-folder` opens the app's data folder (fixed path, nothing from
     the request).
   - `POST /api/diagnostics/dismiss` marks crash records as seen.
   - `POST /api/client-error` logs a frontend error (truncated; at most 50 per run).
3. **`main.py`**: install the hooks right after logging is set up; `begin_run`/`end_run`
   around the server and window (not for a second launch that only shows the running app).
4. **Frontend**:
   - `lib/diagnostics.ts`: `window.onerror` + `unhandledrejection` → `/api/client-error`
     (deduplicated, ignores the harmless ResizeObserver warning).
   - Layout: a dismissable banner when `crashes` is non-empty ("WvW Analyzer closed
     unexpectedly last time" / "hit an error") with **Copy diagnostics**.
   - Settings: a **Troubleshooting** section with the data folder path, **Copy diagnostics**
     and **Open app folder** (named "Open log folder" until the review fixes, plan 10).
5. **Docs**: README troubleshooting section, DECISIONS entry.

## Validation

- Tests (temp dirs only): hooks record crashes; unclean exit detected, ignored after a reboot;
  redaction; report sections; the endpoints (incl. origin checks for the POSTs); client-error
  truncation and cap; worker crash message.
- `ruff`, `pytest`, `svelte-check`, frontend build.
- Not testable from WSL: the Windows event-log query and the packaged app; checked on Windows
  by the user.

## Follow-up: the friend's crash (2026-11-21)

Report: 0.5.2 crashed "when it started analyzing yesterday's session". No useful log (one
rotating file for all runs). The friend shared the 87 arcdps logs.

1. **Reproduce** with the real logs: from source in WSL (processor + spawn workers, memory per
   fight), the packaged 0.5.2 exe on Windows with `--no-window`, then the friend's flow with the
   window: import, app killed mid-queue, windowed start that resumes the queue.
2. **Result:** analysis is fine everywhere; the windowed packaged app deadlocks on every start
   (pywebview walks `WindowApi.window` → the .NET UI tree). Fix: `WindowApi._window`.
3. **Orphaned workers:** a killed app left its analysis worker running; workers now exit when
   the app process is gone.
4. **Logs:** one file per run under `logs/` with retention (14 days / 30 runs / 100 MB, newest 3
   kept), and the report shows the previous run's log.
