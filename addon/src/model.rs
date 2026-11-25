//! The `/api/overlay` payload (schema 1). Every string is written by the analyzer; the addon
//! only lays it out. Unknown fields are ignored and missing ones default, so the analyzer can
//! add fields without breaking older addons.

use serde::Deserialize;

/// Highest payload schema this addon understands.
pub const SUPPORTED_SCHEMA: u32 = 1;

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Overlay {
    pub schema: u32,
    pub version: String,
    pub recording: Recording,
    pub queue: Queue,
    /// The current session's newest fight, whatever fight is being browsed.
    pub latest: Option<Latest>,
    pub session: Option<Session>,
    pub fight: Option<Fight>,
}

#[derive(Debug, Clone, Default, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Latest {
    pub id: i64,
    /// When the analyzer picked up the newest log; unchanged by a re-analysis.
    pub added_at: String,
}

/// Decides when a newly analyzed fight should open the window: only when `latest.addedAt` moves
/// past everything seen before. The first payload only sets the baseline (no pop-up for fights
/// that were there when the game started), and deleting or re-analyzing fights never counts.
#[derive(Debug, Default)]
pub struct NewFights {
    /// None until the first payload; then the newest `addedAt` seen (None: no fights yet).
    seen: Option<Option<String>>,
}

impl NewFights {
    pub fn observe(&mut self, latest: Option<&Latest>) -> bool {
        let added = latest.map(|l| l.added_at.as_str());
        match &mut self.seen {
            None => {
                self.seen = Some(added.map(str::to_owned));
                false
            }
            Some(max) if added > max.as_deref() => {
                *max = added.map(str::to_owned);
                true
            }
            Some(_) => false,
        }
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Recording {
    pub active: bool,
    pub log_dir_ok: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Queue {
    pub pending: u32,
    pub busy: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Session {
    pub id: i64,
    pub name: String,
    pub fights: u32,
    pub record: String,
    pub kills: u32,
    pub deaths: u32,
    pub kdr: f64,
    pub duration: String,
    pub problems: Vec<Problem>,
    pub strengths: Vec<Strength>,
    pub recording: bool,
    pub latest_id: Option<i64>,
    /// The session's analyzed fights, oldest first (empty from an app before 0.7.0).
    pub strip: Vec<StripFight>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct StripFight {
    pub id: i64,
    pub result: Option<String>,
    pub letter: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Problem {
    pub title: String,
    pub severity: String,
    pub count: u32,
    pub losses: u32,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Strength {
    pub title: String,
    pub count: u32,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Fight {
    pub id: i64,
    pub mode: String,
    pub result: Option<String>,
    pub title: String,
    pub result_line: String,
    pub framing: Option<String>,
    pub issues: Vec<Note>,
    pub positives: Vec<Note>,
    pub debrief: Vec<String>,
    pub debrief_unverified: u32,
    pub index: Option<u32>,
    pub count: u32,
    pub prev_id: Option<i64>,
    pub next_id: Option<i64>,
    // From 0.7.0; empty from an older app, which falls back to `title` and `result_line`.
    pub badge: String,
    pub heading: String,
    pub meta: String,
    pub facts: Vec<Fact>,
    pub headline: String,
    pub numbers: String,
    pub issues_title: String,
    /// How many issues the app shows beyond the ones sent.
    pub more_count: u32,
}

impl Fight {
    /// Whether the app sent the result block (0.7.0 and newer).
    pub fn has_header(&self) -> bool {
        !self.badge.is_empty()
    }
}

/// One stat tile: "73" over "Kills". `tone` is "good", "bad" or empty.
#[derive(Debug, Clone, Default, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Fact {
    pub label: String,
    pub value: String,
    pub note: String,
    pub tone: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Note {
    pub severity: String,
    pub title: String,
    pub short: String,
    pub fix: String,
}

impl Overlay {
    pub fn parse(text: &str) -> Result<Self, String> {
        let o: Overlay = serde_json::from_str(text).map_err(|e| e.to_string())?;
        if o.schema > SUPPORTED_SCHEMA {
            return Err(format!(
                "WvW Analyzer {} sends data this addon can't read. Update the in-game addon \
                 from WvW Analyzer > Settings.",
                o.version
            ));
        }
        Ok(o)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn latest(id: i64, added_at: &str) -> Latest {
        Latest { id, added_at: added_at.into() }
    }

    #[test]
    fn new_fights_baseline_then_only_newer_fights() {
        let mut w = NewFights::default();
        // Fights already there when the addon starts: no pop-up.
        assert!(!w.observe(Some(&latest(7, "2026-11-21T20:00:00"))));
        assert!(!w.observe(Some(&latest(7, "2026-11-21T20:00:00"))));
        assert!(w.observe(Some(&latest(8, "2026-11-21T20:05:00"))));
        // Newest fight deleted (or re-queued for a re-analysis), then back: not new.
        assert!(!w.observe(Some(&latest(7, "2026-11-21T20:00:00"))));
        assert!(!w.observe(None));
        assert!(!w.observe(Some(&latest(8, "2026-11-21T20:05:00"))));
        // A new fight may reuse a deleted id; its time still moves forward.
        assert!(w.observe(Some(&latest(8, "2026-11-21T20:09:00"))));
    }

    #[test]
    fn new_fights_first_fight_of_an_empty_session_counts() {
        let mut w = NewFights::default();
        assert!(!w.observe(None)); // connected, no fights yet
        assert!(w.observe(Some(&latest(1, "2026-11-21T20:00:00"))));
    }

    const FIXTURE: &str = include_str!("../tests/fixtures/overlay.json");

    #[test]
    fn parses_the_analyzer_fixture() {
        let o = Overlay::parse(FIXTURE).expect("fixture parses");
        assert_eq!(o.schema, SUPPORTED_SCHEMA);
        let f = o.fight.expect("fight");
        assert!(f.result_line.starts_with("Result:"));
        assert!(!f.issues.is_empty() && !f.issues[0].title.is_empty());
        let latest = o.latest.expect("latest");
        assert!(latest.id == f.id && !latest.added_at.is_empty());
        assert!(f.has_header() && f.facts.len() == 4 && !f.issues_title.is_empty());
        assert!(!f.headline.is_empty() && !f.numbers.is_empty() && !f.meta.is_empty());
        let s = o.session.expect("session");
        assert_eq!(s.latest_id, Some(f.id));
        assert!(!s.problems.is_empty());
        assert_eq!(s.strip.len() as u32, s.fights);
        assert_eq!(s.strip.last().map(|x| x.id), Some(f.id));
    }

    #[test]
    fn an_older_app_without_the_new_fields_still_parses() {
        let o = Overlay::parse(
            r#"{"schema":1,"fight":{"id":3,"title":"20:00  EBG  1:00","resultLine":"Result: win"},
                "session":{"id":1,"fights":2}}"#,
        )
        .unwrap();
        let f = o.fight.unwrap();
        assert!(!f.has_header() && f.facts.is_empty() && f.more_count == 0);
        assert!(o.session.unwrap().strip.is_empty());
    }

    #[test]
    fn tolerates_missing_and_extra_fields() {
        let o = Overlay::parse(r#"{"schema":1,"extra":true,"fight":{"id":3,"new":1}}"#).unwrap();
        assert_eq!(o.fight.unwrap().id, 3);
        assert!(o.session.is_none());
        let s: Session =
            serde_json::from_str(r#"{"strengths":[{"title":"Won the strip war","count":2}]}"#)
                .unwrap();
        assert_eq!(s.strengths[0].count, 2);
    }

    #[test]
    fn rejects_newer_schema() {
        let err = Overlay::parse(r#"{"schema":99,"version":"9.0.0"}"#).unwrap_err();
        assert!(err.contains("Update the in-game addon"));
    }
}
