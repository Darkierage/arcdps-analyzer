# WvW Analyzer: in-app updater plan

> **Status:** implemented 2026-11-26 (see `DECISIONS.md`, "In-app updater"); the Windows
> end-to-end test is still to be run. Deviations: the signing key's default place is
> `~/.wvw-analyzer/release-signing.key` (the script runs in WSL); the version bump (step 7) is
> left for the release; the status also carries the installer `size` (shown in the confirm
> text); Error 740 falls back to ShellExecute; `WVW_SIGNING_PASSPHRASE` can supply the
> passphrase to the script. After the independent review: the "did not finish" banner can be
> hidden until the next start and gives way to a newer release; checks turned off also hide the
> banner; the page re-reads the update status after recording/queue events.
>
> Approved 2026-11-26. Before approval the draft was reviewed
> against the code, Inno Setup's source and docs, PyInstaller's docs and the GitHub API; the
> corrections are folded in (the relaunch switch must be `/RELAUNCH=1`, the relaunch entry's
> flags, PyInstaller's environment reset, a failed install after the app closed, a locked
> installer at cleanup, how "close the app" reaches the window, a test-only signing key).

## Context

The app is shared with friends as an Inno Setup installer attached to GitHub releases
(`vX.Y.Z`, asset `WvWAnalyzer-Setup-X.Y.Z.exe`). Today nobody learns about a new version unless
told, and updating means finding the release page and running the installer by hand.

The request: the app detects a new version, offers to download it and installs it.

Constraints from `DECISIONS.md` and `CLAUDE.md`:
- "No network beyond what's needed": crash reports are sent by hand; the overlay talks only to
  127.0.0.1. An update check is a new outgoing connection and must be visible and switchable.
- Local-only API: Host header must be localhost; state-changing requests need a localhost
  Origin or none.
- File cleanup only inside the data folder.
- The installer and exe are not code-signed (no paid certificate).

## What GitHub provides (checked 2026-11-26)

- `GET https://api.github.com/repos/<owner>/<repo>/releases/latest`, no auth. Excludes drafts
  and pre-releases. Returns `tag_name`, `body` (release notes, markdown), `html_url` and
  `assets[]` with `name`, `size`, `browser_download_url` and `digest` (`sha256:...`, computed by
  GitHub on upload). The v0.7.0 release already has the digest.
- Unauthenticated rate limit: 60 requests/hour per IP. A check at start + every 24 h is far
  below it.
- Asset downloads redirect from github.com to a `*.githubusercontent.com` host; `urllib`
  follows redirects (the same path `tools.py` already uses for Elite Insights and llama.cpp).
- No extra hosting is needed.

## Options considered

- **Own small updater on top of the existing Inno installer (chosen).** The installer already
  upgrades in place (fixed AppId), stops processes running from the app folder and keeps user
  data, and the app already refreshes an outdated overlay addon after an upgrade
  (`addon_install.auto_update`).
- Velopack: GitHub source, delta updates and a tested update/restart loop, but it replaces Inno
  Setup (WebView2 check, process stopping, uninstall data prompt would be redone).
- WinSparkle: appcast feed (could be a release asset) plus a native DLL wrapper; more moving
  parts than the custom updater.
- tufup (TUF): strongest model, too heavy for this app.

## Decisions (user, 2026-11-26)

- Update check **on by default**, with a switch in Settings.
- **One-click "Install and restart"**.
- **Ed25519-signed release manifest** from the first version.

## Security model

Files downloaded by Python get no Mark-of-the-Web, so SmartScreen's reputation check does not
run on them: our own verification is the only gate before an unsigned exe runs (Smart App
Control / Defender behaviour is checked in the Windows test). GitHub's digest protects against
a broken or swapped download but not against a compromised GitHub account or token (attacker
uploads a new release with a matching digest). So:

- A release carries two extra assets: `latest.json` (manifest) and `latest.json.sig`.
- Manifest (UTF-8 JSON, signed as exact bytes):
  `{"schema": 1, "version": "0.8.0", "installer": "WvWAnalyzer-Setup-0.8.0.exe",
  "size": 56539831, "sha256": "...", "published": "2026-12-01"}`.
- `latest.json.sig`: base64 of the raw 64-byte Ed25519 signature over the manifest bytes.
- The app embeds a **list** of trusted public keys (raw 32-byte, base64) in `updater.py`; one
  today, the list allows rotation (ship the new key in a release signed by the old one).
- The private key lives outside the repo, encrypted with a passphrase
  (`%USERPROFILE%\.wvw-analyzer\release-signing.key`, PKCS#8 + BestAvailableEncryption). Lost
  key: generate a new one; friends install that release by hand once.
- Verification in the app, all must hold before the installer runs:
  1. signature valid for one trusted key;
  2. `manifest.version` > running version (prevents replaying an old signed release) and equals
     the release tag without `v`;
  3. downloaded file size == `manifest.size`, sha256 == `manifest.sha256`, and also equals
     GitHub's `digest` when present;
  4. file name == `manifest.installer` and matches `WvWAnalyzer-Setup-<version>.exe`.
- A release without a valid manifest/signature (e.g. 0.7.0, or a tampered one) is shown as
  "new version available" with a link to the release page only; no install button. A failed
  signature is logged at WARNING and shown as "could not verify this update".
- Release notes (`body`) are unsigned display text: rendered as plain text in the UI (no
  `{@html}`), length-capped.
- Accepted: an attacker with the GitHub account can hide updates (freeze), not push code or a
  downgrade.
- Library: `cryptography` (Ed25519 verify; pulls in `cffi`, `pycparser`), a new runtime
  dependency. The standard library has no Ed25519; a hand-written verifier is not worth the
  risk.
- **Test key.** The production key never signs test manifests (a signed "newer" test release
  could later be published by anyone with the GitHub account, and a high test version would
  block real updates). `WVW_UPDATE_TEST_KEY` adds one extra trusted key, and is honoured only
  when the test-only `WVW_UPDATE_API` override is also set.

## Behavior

- **When it checks:** about 30 s after startup, then every 24 h while running; "Check now" in
  Settings. Not while `check_updates` is off. Network errors are logged at INFO and retried at
  the next interval; never shown as an error banner.
- **What is sent:** one HTTPS GET to `api.github.com` (and, for a new version, GETs for the two
  manifest assets) with `User-Agent: wvw-analyzer/<version>`. No account, path or player data.
- **Version compare:** `X.Y.Z` integer tuples; tags that don't parse are ignored.
- **Skip this version:** stored as `skipped_update`; the banner returns for a newer version.
  "Later" hides the banner until the next app start.
- **Running from source** (`paths.FROZEN` false): checks and reports, never downloads or
  installs (shows the release link).
- **Download:** on "Install and restart" (not in the background): streamed to
  `<data>/updates/<installer>.part`, renamed after verification. Progress over the existing
  WebSocket.
- **Cleanup:** at startup, old files in `updates/` are deleted; a file still locked (the
  installer that just relaunched the app is still running from there) is skipped and retried at
  the next start.
- **Busy app:** the install button is disabled while recording is on or the processor queue
  has pending/running fights, with a reason ("finish or stop recording first"). Downloading is
  allowed.
- **Before closing:** the confirm text says the app will close, the installer will run, and
  the app will restart; if the update fails, run the installer again from the shown path.
- **Install and exit:**
  1. The API stores `pending_install = <verified path>` and sets an exit request in
     `AppState` (a `threading.Event`). The API holds no window or server handle; `main.py`
     owns them: a watcher thread started in `_serve` waits for the event and then calls the
     pywebview window's `destroy()` (via the `WindowApi` it already keeps) or, in
     `--no-window`/browser mode, sets `server.should_exit`.
  2. The normal shutdown runs (`end_run` marks the run as closed normally, llama-server
     stops, server stops).
  3. Only after a **clean** shutdown (not from the `finally` after an exception), at the end of
     `main()`, the app re-hashes the file (verify-to-run gap) and starts the installer detached
     (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, `close_fds`) with
     `/SILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH=1`, then returns.
     - The child gets a copy of the environment with `PYINSTALLER_RESET_ENVIRONMENT=1`, and the
       app calls `SetDllDirectoryW(None)` first, so neither the installer nor the relaunched
       app inherits the bootloader's state (PyInstaller docs: a process that outlives the app;
       an inherited `_PYI_*` state could make the relaunched exe act as a worker).
  4. The installer's `PrepareToInstall` stops anything still running from the app folder.
- **Installer change:** the existing "launch app" `[Run]` entry has `skipifsilent`, so a silent
  install never restarts the app. Add a second entry:
  `Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: ShouldRelaunch`, where
  `ShouldRelaunch` is `ExpandConstant('{param:RELAUNCH|0}') = '1'`. Inno's `{param:}` only
  matches `/Name=Value`, so a bare `/RELAUNCH` would never be seen. `runasoriginaluser`
  matters for an all-users install: without it (default `runascurrentuser` for entries without
  `postinstall`) the app would restart elevated, possibly as the admin account with another
  data folder. Interactive installs are unchanged.
- **Installed for all users:** Inno reuses the previous install mode (`UsePreviousPrivileges`),
  so an admin install shows a UAC prompt during the update. Accepted.
- **Failed update:** if the user declines UAC, nothing changed but the app stays closed. If the
  install aborts after `[InstallDelete]` removed `{app}\_internal` (a risk manual upgrades
  already have), the app may not start. Handling: `<data>/update.json` records the attempted
  version before exit; at the next start, if the running version is lower, the banner says the
  update did not finish and offers to run the kept installer again in normal (non-silent) mode.
  A broken install is fixed by running the installer from `updates/` or the release page,
  which the pre-close text names.
- **Overlay addon:** unchanged; it is refreshed by the existing post-upgrade path.

## API

- `GET /api/update` → `{current, enabled, checking, lastCheck, latest: {version, notes,
  url, publishedAt, verified} | null, available, skipped, canInstall, blockedReason,
  download: {state, done, total} | null, unfinished: {version, installer} | null}`.
- `POST /api/update/check` → runs a check now.
- `POST /api/update/skip` → body `{version}`.
- `POST /api/update/install` → no body: uses only the release found by the app's own last
  check (never a URL or path from the request).
- `POST /api/update/retry` → reruns the kept installer interactively after an unfinished
  update (re-verified first).
- All POSTs fall under the existing localhost Origin rule. Types mirrored in
  `frontend/src/lib/api.ts`.

## Settings

`check_updates: bool = True`, `skipped_update: str | None = None`. The cached check result
(last check time, last release JSON, attempted install) lives in `<data>/update.json`, not in
settings.

## UI

- Banner in `+layout.svelte` (same pattern as the crash banner): "WvW Analyzer 0.8.0 is
  available. What's new · Install and restart · Skip this version · Later". "What's new"
  expands the notes as plain text. Download progress shown in the banner.
- Settings, new "Updates" section: current version, last check, switch, "Check now", link to
  the releases page.

## Release flow

- New `scripts/release_sign.py`:
  - `keygen` → writes the encrypted private key (refuses to overwrite) and prints the public
    key to paste into `updater.py`.
  - `sign dist/WvWAnalyzer-Setup-X.Y.Z.exe` → checks X.Y.Z matches `__version__`, writes
    `dist/latest.json` and `dist/latest.json.sig`, verifies the signature with the embedded
    public key before finishing.
  - Runs in WSL (`uv run`), on the installer copied back from Windows.
- Release: `gh release create vX.Y.Z dist/WvWAnalyzer-Setup-X.Y.Z.exe dist/latest.json
  dist/latest.json.sig --notes-file ...`. Notes are user-facing now (shown in the app).
- README "Building" gets the release steps.

## Steps

1. `updater.py`: fetch, parse, compare, cache, manifest verify; settings; background
   checker in `AppState` lifecycle. Tests: fake HTTP layer (monkeypatched opener) for new
   version, same version, bad tag, network error, missing manifest, bad signature, wrong key,
   version mismatch, replayed older manifest, size/hash mismatch, test key ignored without the
   API override.
2. API endpoints + Origin tests; frontend types.
3. UI banner + Settings section; `npm run check`, `npm test`.
4. Download, re-verify, exit request + watcher in `main.py`, installer spawn (environment
   reset, clean-shutdown only), unfinished-update detection, locked-file cleanup,
   `installer.iss` relaunch entry. Tests for download verification, the "busy" rule, cleanup
   and the spawn arguments/environment (spawn function injected).
5. `scripts/release_sign.py` + `cryptography` dependency; PyInstaller check that it bundles
   (note the size added).
6. Docs: `DECISIONS.md` (network stance change, security model, why not Velopack/WinSparkle),
   README (privacy: what is sent, how to turn it off; release steps), plan status, docs index.
7. Version bump in the four places.

## Validation

- `uv run pytest`, `ruff`, `npm run check`, `npm test`.
- `WVW_UPDATE_API` environment variable overrides the API URL, for testing only (ignored
  unless set). End-to-end on Windows (user), with a test key and a local HTTP server serving a
  fake newer release + signed manifest:
  - per-user install: check → download → install → relaunch, unelevated;
  - all-users install: the same, the app restarts unelevated as the original user, and
    starting the installer shows UAC (no error 740);
  - decline UAC; kill the install midway: the next start offers the retry;
  - a tampered installer and a bad signature: refused;
  - the relaunched app logs no inherited `_PYI*` variables;
  - Smart App Control / Defender do not block the downloaded installer.
- Zerg/GvG analysis untouched (no `ANALYZER_VERSION` bump).

## Out of scope

- Delta updates, background silent auto-install, a pre-release/beta channel, updating Elite
  Insights or llama.cpp separately (they ship pinned in the app).
- Users on 0.7.0 or older must install the first updater version by hand.
