//! Background connection to the analyzer on 127.0.0.1. The render thread never does I/O: it
//! reads the latest snapshot and sends commands; this thread polls `/api/overlay` with an ETag
//! (an unchanged payload costs a 304) and finds the analyzer's port on its own.

use crate::model::Overlay;
use std::ops::RangeInclusive;
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread::JoinHandle;
use std::time::Duration;

/// The analyzer picks the first free port from 8765 (see `choose_port` in `main.py`).
pub const PORTS: RangeInclusive<u16> = 8765..=8785;
const POLL: Duration = Duration::from_secs(2);
const SEARCH: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, PartialEq)]
pub enum Status {
    /// No analyzer found yet.
    Searching,
    Connected,
    /// The analyzer is newer than this addon understands.
    Incompatible(String),
}

#[derive(Debug, Clone)]
pub struct Snapshot {
    pub status: Status,
    pub data: Option<Overlay>,
    /// Error from the last button action (e.g. recording could not start).
    pub action_error: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Command {
    /// Show this fight, or the latest one.
    Select(Option<i64>),
    SetRecording(bool),
}

enum Msg {
    Cmd(Command),
    Stop,
}

pub struct Client {
    tx: Sender<Msg>,
    shared: Arc<Mutex<Snapshot>>,
    handle: Option<JoinHandle<()>>,
}

impl Client {
    pub fn start(ports: RangeInclusive<u16>) -> Self {
        let shared = Arc::new(Mutex::new(Snapshot {
            status: Status::Searching,
            data: None,
            action_error: None,
        }));
        let (tx, rx) = mpsc::channel();
        let worker = Worker::new(ports, shared.clone());
        let handle = std::thread::Builder::new()
            .name("wvw-analyzer-client".into())
            .spawn(move || worker.run(rx))
            .ok();
        Self { tx, shared, handle }
    }

    pub fn send(&self, cmd: Command) {
        let _ = self.tx.send(Msg::Cmd(cmd));
    }

    pub fn snapshot(&self) -> MutexGuard<'_, Snapshot> {
        self.shared.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Stops the thread; returns once it has exited (at most one request timeout).
    pub fn stop(&mut self) {
        let _ = self.tx.send(Msg::Stop);
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}

impl Drop for Client {
    fn drop(&mut self) {
        self.stop();
    }
}

enum Fetch {
    New(Box<Overlay>),
    Unchanged,
}

enum FetchError {
    /// Lost the analyzer: search again.
    Gone,
    Incompatible(String),
}

struct Worker {
    agent: ureq::Agent,
    ports: RangeInclusive<u16>,
    port: Option<u16>,
    etag: Option<String>,
    selected: Option<i64>,
    shared: Arc<Mutex<Snapshot>>,
}

impl Worker {
    fn new(ports: RangeInclusive<u16>, shared: Arc<Mutex<Snapshot>>) -> Self {
        let agent = ureq::Agent::config_builder()
            .timeout_connect(Some(Duration::from_millis(300)))
            .timeout_global(Some(Duration::from_secs(3)))
            .http_status_as_error(false)
            .proxy(None)
            .build()
            .into();
        Self { agent, ports, port: None, etag: None, selected: None, shared }
    }

    fn update(&self, f: impl FnOnce(&mut Snapshot)) {
        let mut s = self.shared.lock().unwrap_or_else(|e| e.into_inner());
        f(&mut s);
    }

    fn run(mut self, rx: Receiver<Msg>) {
        loop {
            if self.port.is_none() {
                self.port = self.discover();
            }
            if let Some(port) = self.port {
                match self.fetch(port) {
                    Ok(Fetch::New(o)) => self.update(|s| {
                        s.status = Status::Connected;
                        s.data = Some(*o);
                    }),
                    Ok(Fetch::Unchanged) => {}
                    Err(FetchError::Incompatible(msg)) => self.update(|s| {
                        s.status = Status::Incompatible(msg);
                        s.data = None;
                    }),
                    Err(FetchError::Gone) => {
                        self.port = None;
                        self.etag = None;
                        self.update(|s| {
                            s.status = Status::Searching;
                            s.data = None;
                        });
                    }
                }
            } else {
                self.update(|s| {
                    s.status = Status::Searching;
                    s.data = None;
                });
            }
            let wait = if self.port.is_some() { POLL } else { SEARCH };
            match rx.recv_timeout(wait) {
                Ok(Msg::Stop) | Err(RecvTimeoutError::Disconnected) => return,
                Ok(Msg::Cmd(cmd)) => self.handle(cmd),
                Err(RecvTimeoutError::Timeout) => {}
            }
        }
    }

    fn handle(&mut self, cmd: Command) {
        match cmd {
            Command::Select(id) => self.selected = id,
            Command::SetRecording(on) => {
                let Some(port) = self.port else { return };
                let path = if on { "start" } else { "stop" };
                let url = format!("http://127.0.0.1:{port}/api/recording/{path}");
                let error = match self.agent.post(&url).send_empty() {
                    Ok(r) if r.status().is_success() => None,
                    Ok(mut r) => Some(detail(&r.body_mut().read_to_string().unwrap_or_default())),
                    Err(e) => Some(e.to_string()),
                };
                self.update(|s| s.action_error = error);
            }
        }
        self.etag = None; // always fetch fresh data after an action
    }

    fn discover(&self) -> Option<u16> {
        self.ports.clone().find(|&port| {
            let url = format!("http://127.0.0.1:{port}/api/status");
            self.agent
                .get(&url)
                .call()
                .ok()
                .filter(|r| r.status().is_success())
                .and_then(|mut r| r.body_mut().read_to_string().ok())
                .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
                .is_some_and(|v| v["app"] == "wvw-analyzer")
        })
    }

    fn fetch(&mut self, port: u16) -> Result<Fetch, FetchError> {
        let mut url = format!("http://127.0.0.1:{port}/api/overlay");
        if let Some(id) = self.selected {
            url.push_str(&format!("?fight={id}"));
        }
        let mut req = self.agent.get(&url);
        if let Some(etag) = &self.etag {
            req = req.header("If-None-Match", etag);
        }
        let mut resp = req.call().map_err(|_| FetchError::Gone)?;
        match resp.status().as_u16() {
            304 => Ok(Fetch::Unchanged),
            404 if self.selected.is_some() => {
                // The fight was deleted or re-queued: fall back to the latest one.
                self.selected = None;
                self.etag = None;
                self.fetch(port)
            }
            200 => {
                let etag =
                    resp.headers().get("etag").and_then(|v| v.to_str().ok()).map(str::to_owned);
                let text = resp.body_mut().read_to_string().map_err(|_| FetchError::Gone)?;
                let overlay = Overlay::parse(&text).map_err(FetchError::Incompatible)?;
                self.etag = etag;
                Ok(Fetch::New(Box::new(overlay)))
            }
            _ => Err(FetchError::Gone),
        }
    }
}

/// FastAPI error body `{"detail": "..."}` -> the message.
fn detail(body: &str) -> String {
    serde_json::from_str::<serde_json::Value>(body)
        .ok()
        .and_then(|v| v["detail"].as_str().map(str::to_owned))
        .unwrap_or_else(|| "The analyzer refused the request.".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;
    use std::time::Instant;

    const FIXTURE: &str = include_str!("../tests/fixtures/overlay.json");

    /// A tiny fake analyzer: answers /api/status, /api/overlay (with ETag) and recording POSTs.
    fn fake_analyzer() -> (u16, Arc<Mutex<Vec<String>>>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let seen = Arc::new(Mutex::new(Vec::new()));
        let log = seen.clone();
        std::thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut first = String::new();
                reader.read_line(&mut first).unwrap();
                let mut etag_match = false;
                loop {
                    let mut line = String::new();
                    reader.read_line(&mut line).unwrap();
                    if line.trim().is_empty() {
                        break;
                    }
                    etag_match |= line.to_ascii_lowercase().starts_with("if-none-match: \"v1\"");
                }
                log.lock().unwrap().push(first.trim().to_string());
                let (status, body) = if first.contains("/api/status") {
                    ("200 OK", r#"{"app":"wvw-analyzer","version":"0.5.0"}"#.to_string())
                } else if first.contains("/api/recording/start") {
                    ("400 Bad Request", r#"{"detail":"arcdps log folder not found"}"#.into())
                } else if etag_match {
                    ("304 Not Modified", String::new())
                } else {
                    ("200 OK", FIXTURE.to_string())
                };
                let mut out = stream;
                let _ = write!(
                    out,
                    "HTTP/1.1 {status}\r\nETag: \"v1\"\r\nContent-Type: application/json\r\n\
                     Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
            }
        });
        (port, seen)
    }

    fn wait_for(client: &Client, cond: impl Fn(&Snapshot) -> bool) -> bool {
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(10) {
            if cond(&client.snapshot()) {
                return true;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        false
    }

    #[test]
    fn finds_the_analyzer_polls_and_reports_action_errors() {
        let (port, seen) = fake_analyzer();
        let mut client = Client::start(port..=port);
        assert!(wait_for(&client, |s| s.status == Status::Connected && s.data.is_some()));

        client.send(Command::SetRecording(true));
        assert!(
            wait_for(&client, |s| s.action_error.as_deref() == Some("arcdps log folder not found"))
        );

        client.send(Command::Select(Some(1)));
        assert!(wait_for(&client, |_| seen
            .lock()
            .unwrap()
            .iter()
            .any(|l| l.contains("/api/overlay?fight=1"))));
        let started = Instant::now();
        client.stop();
        assert!(started.elapsed() < Duration::from_secs(4));
    }

    #[test]
    fn stays_searching_without_an_analyzer() {
        // Bind and drop to get a port nothing listens on.
        let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let client = Client::start(port..=port);
        std::thread::sleep(Duration::from_millis(300));
        assert_eq!(client.snapshot().status, Status::Searching);
    }
}
