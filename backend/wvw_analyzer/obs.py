"""Optional OBS connection: start/stop OBS recording with the app's recording and link the
recordings to the fights they cover.

OBS 28+ has a WebSocket server built in (OBS WebSocket v5, Tools > WebSocket Server Settings);
no plugin is needed. The app connects to 127.0.0.1 only. Rules (docs/DECISIONS.md):

- OBS records while the app records: the app's recording start (by hand or with the game)
  starts OBS, unless OBS already records (that recording is used). When OBS connects while the
  app already records, OBS is started then.
- The app stops only a recording it started. One the user started in OBS is never stopped.
- OBS failing (not running, wrong password, refusing to record) never affects log recording.
- The events carry no time stamps: a recording's start is the app's clock when it learns of
  it minus OBS's own recorded duration (`GetRecordStatus.outputDuration`).
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import videos as vid

log = logging.getLogger(__name__)

HOST = "127.0.0.1"  # never another machine
RPC_VERSION = 1
SUB_OUTPUTS = 1 << 6  # EventSubscription::Outputs (record state, file changes)
AUTH_FAILED = 4009  # WebSocketCloseCode::AuthenticationFailed
REQUEST_TIMEOUT_S = 5.0
ADOPT_MATCH_MS = 3000  # an open OBS row this close to a recording's start is that recording
LABEL = "OBS"


class ObsError(RuntimeError):
    pass


class ObsAuthError(ObsError):
    pass


def auth_string(password: str, salt: str, challenge: str) -> str:
    """OBS WebSocket v5 authentication:
    base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def now_ms() -> int:
    return int(time.time() * 1000)


def _norm(path: str | None) -> str | None:
    """A path as the app stores every video path (absolute, this OS's separators), so a file
    OBS names "C:/Users/.../x.mkv" matches the same file found or linked as "C:\\...\\x.mkv"."""
    if not path:
        return None
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(Path(path))


class ObsConnection:
    """One connection to OBS: handshake, requests from any thread, events to a callback.

    `run()` reads until the connection closes (call it on one thread); `request()` may be
    called from others while it runs."""

    def __init__(self, port: int, password: str,
                 on_event: Callable[[str, dict[str, Any]], None] | None = None,
                 timeout: float = 3.0):
        self.port = port
        self.password = password
        self.on_event = on_event
        self.timeout = timeout
        self.version: str | None = None
        self._ws: Any = None
        self._send_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[str, tuple[threading.Event, list[dict[str, Any]]]] = {}
        self._closed = threading.Event()

    def open(self) -> None:
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect

        try:
            # legacy=True: a plain connection closed by close() (it lives across threads, so
            # it can't be a `with` block).
            self._ws = connect(f"ws://{HOST}:{self.port}", open_timeout=self.timeout,
                               close_timeout=1, max_size=4 * 1024 * 1024, legacy=True)
        except Exception as e:  # refused, timed out, not a WebSocket server...
            raise ObsError(f"OBS is not reachable on port {self.port} ({e})") from e
        try:
            hello = json.loads(self._ws.recv(timeout=self.timeout))
            if hello.get("op") != 0:
                raise ObsError("Not an OBS WebSocket server")
            d = hello.get("d") or {}
            self.version = d.get("obsWebSocketVersion")
            ident: dict[str, Any] = {"rpcVersion": RPC_VERSION, "eventSubscriptions": SUB_OUTPUTS}
            auth = d.get("authentication")
            if auth:
                if not self.password:
                    raise ObsAuthError("OBS asks for a password: copy it from OBS (Tools > "
                                       "WebSocket Server Settings > Show Connect Info)")
                ident["authentication"] = auth_string(self.password, auth.get("salt", ""),
                                                      auth.get("challenge", ""))
            self._ws.send(json.dumps({"op": 1, "d": ident}))
            ok = json.loads(self._ws.recv(timeout=self.timeout))
            if ok.get("op") != 2:
                raise ObsError("OBS did not accept the connection")
        except ConnectionClosed as e:
            self.close()
            code = e.rcvd.code if e.rcvd else None
            if code == AUTH_FAILED:
                raise ObsAuthError("OBS refused the password") from e
            raise ObsError(f"OBS closed the connection ({code})") from e
        except (TimeoutError, ValueError) as e:
            self.close()
            raise ObsError(f"OBS did not answer the handshake ({e})") from e
        except ObsError:
            self.close()
            raise

    def run(self) -> None:
        """Read messages until the connection closes."""
        from websockets.exceptions import ConnectionClosed

        ws = self._ws  # close() may clear self._ws from another thread at any moment
        try:
            while ws is not None:
                msg = json.loads(ws.recv())
                op, d = msg.get("op"), msg.get("d") or {}
                if op == 7:  # RequestResponse
                    slot = self._pending.get(str(d.get("requestId")))
                    if slot:
                        slot[1].append(d)
                        slot[0].set()
                elif op == 5 and self.on_event:  # Event
                    try:
                        self.on_event(str(d.get("eventType")), d.get("eventData") or {})
                    except Exception:
                        log.exception("OBS event handler failed")
        except (ConnectionClosed, OSError, ValueError):
            pass
        finally:
            self._closed.set()
            for ev, _ in list(self._pending.values()):
                ev.set()

    def request(self, request_type: str, data: dict[str, Any] | None = None,
                timeout: float = REQUEST_TIMEOUT_S) -> dict[str, Any]:
        if self._ws is None or self._closed.is_set():
            raise ObsError("Not connected to OBS")
        rid = str(next(self._ids))
        slot: tuple[threading.Event, list[dict[str, Any]]] = (threading.Event(), [])
        self._pending[rid] = slot
        try:
            with self._send_lock:
                self._ws.send(json.dumps({"op": 6, "d": {
                    "requestType": request_type, "requestId": rid, "requestData": data or {}}}))
            if not slot[0].wait(timeout) or not slot[1]:
                raise ObsError(f"OBS did not answer {request_type}")
            resp = slot[1][0]
        except OSError as e:
            raise ObsError(f"Lost the connection to OBS ({e})") from e
        finally:
            self._pending.pop(rid, None)
        status = resp.get("requestStatus") or {}
        if not status.get("result"):
            raise ObsError(status.get("comment") or f"OBS refused {request_type} "
                                                    f"(code {status.get('code')})")
        return resp.get("responseData") or {}

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # closing a broken socket must not raise
                pass
        self._closed.set()
        for ev, _ in list(self._pending.values()):  # requests waiting for an answer fail now
            ev.set()


def check_connection(port: int, password: str) -> dict[str, Any]:
    """Settings' "Test connection": connect once and ask OBS for its version."""
    conn = ObsConnection(port, password)
    try:
        conn.open()
        reader = threading.Thread(target=conn.run, daemon=True, name="obs-test")
        reader.start()
        v = conn.request("GetVersion")
        return {"ok": True, "version": v.get("obsVersion") or conn.version, "error": None}
    except ObsError as e:
        return {"ok": False, "version": None, "error": str(e)}
    finally:
        conn.close()


class ObsService:
    """Keeps the connection while enabled and turns OBS's record events into `videos` rows.

    Everything that changes state runs on one worker thread (`_work`), in order: OBS events,
    the app's recording start/stop, the API's actions. The connection's reader is a separate
    thread, so requests made on the worker never wait on themselves."""

    def __init__(self, config: Any, db: Any, bus: Any, recorder: Any):
        self.config = config
        self.db = db
        self.bus = bus
        self.recorder = recorder
        self._work = ThreadPoolExecutor(max_workers=1, thread_name_prefix="obs")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: ObsConnection | None = None
        self._state = "off"
        self._error: str | None = None
        self._version: str | None = None
        self._recording = False
        self._paused = False
        self._leftover = False
        self._current: int | None = None  # videos row of the file OBS is writing
        self._pause_start: int | None = None
        self._start_requested: float | None = None
        self._record_dir: Path | None = None

    # ---- lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="obs-connect", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._work.shutdown(wait=True, cancel_futures=False)
        if self._conn:
            self._conn.close()

    def settings_changed(self) -> None:
        """Reconnect with the new port / password, or disconnect when turned off."""
        if self._conn:
            self._conn.close()
        self._wake.set()

    def status(self) -> dict[str, Any]:
        enabled = self.config.settings.obs.enabled
        return {"enabled": enabled, "state": self._state if enabled else "off",
                "recording": self._recording, "paused": self._paused,
                "version": self._version, "error": self._error, "leftover": self._leftover}

    def _publish(self) -> None:
        self.bus.publish({"type": "obs", "obs": self.status()})

    def _set_state(self, state: str, error: str | None = None) -> None:
        if (state, error) != (self._state, self._error):
            self._state, self._error = state, error
            self._publish()

    def _loop(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            s = self.config.settings.obs
            if not s.enabled:
                self._set_state("off")
                self._wake.wait(5)
                self._wake.clear()
                continue
            self._set_state("connecting")
            conn = ObsConnection(s.port, s.password, on_event=self._on_event)
            try:
                conn.open()
            except ObsAuthError as e:
                self._set_state("auth", str(e))
                self._wake.wait(30)  # a wrong password won't fix itself: wait for a settings change
                self._wake.clear()
                continue
            except Exception as e:
                self._set_state("offline", str(e))
                self._wake.wait(backoff)
                self._wake.clear()
                backoff = min(backoff * 1.5, 15.0)
                continue
            backoff = 2.0
            self._conn = conn
            self._version = conn.version
            self._set_state("connected")
            log.info("connected to OBS (WebSocket %s)", conn.version)
            self._submit(self._on_connected)
            try:
                conn.run()  # until OBS closes or settings change
            except Exception:  # never let the connection thread die: reconnect instead
                log.exception("OBS connection reader failed")
            conn.close()
            self._conn = None
            self._recording = self._paused = False
            # Forget the file being tracked: OBS may come back idle, and a recording started
            # by hand then must not be written into the old row. A reconnect while OBS still
            # records finds that row again by its start (_adopt).
            self._submit(self._on_disconnected)
            if not self._stop.is_set():
                log.info("OBS connection closed")
                self._set_state("offline", "OBS closed the connection")
            self._wake.wait(1)
            self._wake.clear()

    def _submit(self, fn: Callable[..., None], *args: Any) -> None:
        def run() -> None:
            try:
                fn(*args)
            except ObsError as e:
                log.warning("OBS: %s", e)
                self._error = str(e)
                self._publish()
            except Exception:
                log.exception("OBS handling failed")
        try:
            self._work.submit(run)
        except RuntimeError:  # shutting down
            pass

    def _request(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        conn = self._conn
        if conn is None or conn.closed:
            raise ObsError("Not connected to OBS")
        return conn.request(request_type, data)

    # ---- inputs ------------------------------------------------------------------------------
    def on_recording(self, recording: bool) -> None:
        """The app's recording started or stopped (Recorder callback, any thread)."""
        self._submit(self._app_started if recording else self._app_stopped)

    def _on_event(self, event_type: str, data: dict[str, Any]) -> None:
        at = now_ms()  # when it happened, before it waits in the queue
        if event_type == "RecordStateChanged":
            self._submit(self._record_state, str(data.get("outputState") or ""),
                         data.get("outputPath"), at)
        elif event_type == "RecordFileChanged":
            self._submit(self._file_changed, data.get("newOutputPath"), at)

    def leftover(self, action: str) -> dict[str, Any]:
        """The "still recording from the last session" notice: stop OBS, or keep it running
        (then the app no longer stops it)."""
        done = threading.Event()

        def run() -> None:
            try:
                if action == "stop" and self._recording:
                    self._request("StopRecord")
                elif self._current is not None:
                    self.db.update_video(self._current, started_by_app=False)
                self._leftover = False
                self._publish()
            finally:
                done.set()
        self._submit(run)
        done.wait(REQUEST_TIMEOUT_S + 1)
        return self.status()

    # ---- handlers (worker thread) ---------------------------------------------------------------
    def _settings(self) -> Any:
        return self.config.settings.obs

    def _on_connected(self) -> None:
        try:
            self._record_dir = Path(self._request("GetRecordDirectory").get("recordDirectory")
                                    or "")
        except ObsError:
            self._record_dir = None
        st = self._request("GetRecordStatus")
        self._recording = bool(st.get("outputActive"))
        self._paused = bool(st.get("outputPaused"))
        if self._recording:
            # First the row of the file being written, so tidying up below leaves it open.
            row = self._adopt(st, now_ms())
            if row and row.get("started_by_app") and not self.recorder.recording:
                # The app was closed (or crashed) while its recording ran.
                self._leftover = True
        self._resolve_pending()
        if not self._recording and self.recorder.recording and self._settings().control_recording:
            self._start_obs()
        self._publish()

    def _on_disconnected(self) -> None:
        self._current = None
        self._pause_start = None
        self._start_requested = None

    def _app_started(self) -> None:
        if not self._settings().control_recording or self._conn is None:
            return
        st = self._request("GetRecordStatus")
        if st.get("outputActive"):
            self._recording = True
            self._adopt(st, now_ms(), link=True)
            self._publish()
        else:
            self._start_obs()

    def _app_stopped(self) -> None:
        if not self._settings().control_recording or self._conn is None:
            return
        row = self.db.video(self._current) if self._current is not None else None
        if self._recording and row and row.get("started_by_app"):
            self._request("StopRecord")

    def _start_obs(self) -> None:
        self._start_requested = time.monotonic()
        try:
            self._request("StartRecord")
        except ObsError as e:
            self._start_requested = None
            raise ObsError(f"OBS did not start recording: {e}") from e

    def _record_state(self, state: str, path: str | None, at: int) -> None:
        if state.endswith("_STARTED"):
            self._recording, self._paused = True, False
            st = self._request("GetRecordStatus")
            by_app = self._start_requested is not None and \
                time.monotonic() - self._start_requested < 30
            self._start_requested = None
            self._adopt(st, at, started_by_app=by_app)
        elif state.endswith("_PAUSED"):
            self._paused = True
            self._pause_start = at
        elif state.endswith("_RESUMED"):
            self._paused = False
            self._close_pause(at)
        elif state.endswith("_STOPPED"):
            self._close_pause(at)
            self._recording = self._paused = False
            self._leftover = False
            if self._current is not None:
                self._finish(self._current, path, at)
            self._current = None
        self._publish()

    def _file_changed(self, new_path: str | None, at: int) -> None:
        """OBS split the recording: the current file ends now and the new one starts now."""
        prev = self.db.video(self._current) if self._current is not None else None
        if prev:
            self._close_pause(at)
            self._finish(prev["id"], None, at)
        if not new_path or (not prev and not self._settings().auto_link):
            self._current = None
            return
        self._current = self._link(path=_norm(new_path), start_ms=at,
                                   started_by_app=bool(prev and prev.get("started_by_app")),
                                   approximate=False)

    # ---- rows --------------------------------------------------------------------------------
    def _adopt(self, st: dict[str, Any], at: int, started_by_app: bool = False,
               link: bool = False) -> dict[str, Any] | None:
        """The row of the recording OBS is writing now: an open one that matches, else a new one
        (when auto-linking, or `link`, or the app started it)."""
        start = at - int(st.get("outputDuration") or 0)
        paused = bool(st.get("outputPaused"))
        for v in self.db.videos():
            if v["sync_source"] == "obs" and v.get("end_ms") is None and \
                    abs(v["start_ms"] - start) <= ADOPT_MATCH_MS:
                self._current = v["id"]
                if paused:
                    self._pause_start = at
                return v
        if not (self._settings().auto_link or link or started_by_app):
            self._current = None
            return None
        path = self._find_file(start)
        # A recording paused before the app saw it: OBS's duration leaves the pause out, so the
        # start comes out late by that much. Mark it for "Sync here".
        approximate = paused
        if path and (named := vid.name_time_ms(Path(path).name)) is not None:
            approximate = approximate or abs(named - start) > 2000
        self._current = self._link(path=path, start_ms=start, started_by_app=started_by_app,
                                   approximate=approximate)
        if paused:
            self._pause_start = at
        return self.db.video(self._current) if self._current is not None else None

    def _link(self, *, path: str | None, start_ms: int, started_by_app: bool,
              approximate: bool) -> int | None:
        if path:
            existing = self.db.video_by_path(path)
            if existing:  # already linked (by hand, or before): that row is this recording
                self.db.update_video(existing["id"], end_ms=None)
                return existing["id"]
        vid_id = self.db.add_video(path=path, label=LABEL, start_ms=start_ms, end_ms=None,
                                   sync_source="obs", approximate=approximate,
                                   started_by_app=started_by_app, pauses=[])
        log.info("OBS recording linked (%s)", Path(path).name if path else "file name pending")
        return vid_id

    def _finish(self, video_id: int, path: str | None, at: int) -> None:
        v = self.db.video(video_id)
        if not v:
            return
        fields: dict[str, Any] = {"end_ms": at}
        path = _norm(path)
        if path and not v.get("path"):
            other = self.db.video_by_path(path)
            if other and other["id"] != video_id:
                # The user linked that file by hand meanwhile: keep theirs, drop ours.
                self.db.delete_video(video_id)
                self.db.update_video(other["id"], end_ms=other.get("end_ms") or at)
                return
            fields["path"] = path
        self.db.update_video(video_id, **fields)
        if not (fields.get("path") or v.get("path")):
            self._resolve_pending()

    def _close_pause(self, at: int) -> None:
        if self._pause_start is None or self._current is None:
            self._pause_start = None
            return
        v = self.db.video(self._current)
        if v:
            self.db.update_video(v["id"], pauses=[*v["pauses"], [self._pause_start, at]])
        self._pause_start = None

    def _find_file(self, start_ms: int) -> str | None:
        """The recording file that started at `start_ms` (OBS creates it when recording starts)."""
        folders = [self._record_dir] if self._record_dir else []
        best: tuple[float, Path] | None = None
        for f in vid.scan_folders([d for d in folders if d and d.is_dir()]):
            try:
                t = vid.file_timing(f)
            except OSError:
                continue
            if t["approximate"]:
                continue
            d = abs(t["start_ms"] - start_ms)
            if d <= 5000 and (best is None or d < best[0]):
                best = (d, f)
        return str(best[1].resolve()) if best else None

    def _resolve_pending(self) -> None:
        """Rows whose file name or end is still unknown (the app was closed while OBS recorded,
        or OBS split a file): find the file by its time; close rows OBS no longer writes."""
        for v in self.db.videos():
            if v["sync_source"] != "obs":
                continue
            fields: dict[str, Any] = {}
            path = v.get("path")
            if not path and (found := self._find_file(v["start_ms"])):
                if not self.db.video_by_path(found):
                    fields["path"] = path = found
            writing = v["id"] == self._current and self._recording
            if v.get("end_ms") is None and not writing:
                if path and Path(path).is_file():
                    fields["end_ms"] = int(Path(path).stat().st_mtime * 1000)
                elif not self._recording:
                    # Unknown: a zero-length span, which covers no fight (videos.covers).
                    fields["end_ms"] = v["start_ms"]
            if fields:
                self.db.update_video(v["id"], **fields)
