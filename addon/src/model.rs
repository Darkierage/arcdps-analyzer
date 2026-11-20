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
    pub session: Option<Session>,
    pub fight: Option<Fight>,
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

/// RGBA colors for severities and results.
pub fn severity_color(severity: &str) -> [f32; 4] {
    match severity {
        "critical" => [1.0, 0.36, 0.36, 1.0],
        "major" => [1.0, 0.62, 0.25, 1.0],
        "minor" => [0.95, 0.85, 0.35, 1.0],
        "positive" => [0.4, 0.85, 0.45, 1.0],
        _ => [0.7, 0.7, 0.7, 1.0],
    }
}

pub fn result_color(result: Option<&str>) -> [f32; 4] {
    match result {
        Some("win") => [0.4, 0.85, 0.45, 1.0],
        Some("loss") => [1.0, 0.36, 0.36, 1.0],
        Some("even") => [0.95, 0.85, 0.35, 1.0],
        _ => [0.7, 0.7, 0.7, 1.0],
    }
}

pub fn severity_label(severity: &str) -> &'static str {
    match severity {
        "critical" => "Critical",
        "major" => "Major",
        "minor" => "Minor",
        "positive" => "Went well",
        _ => "Context",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURE: &str = include_str!("../tests/fixtures/overlay.json");

    #[test]
    fn parses_the_analyzer_fixture() {
        let o = Overlay::parse(FIXTURE).expect("fixture parses");
        assert_eq!(o.schema, SUPPORTED_SCHEMA);
        let f = o.fight.expect("fight");
        assert!(f.result_line.starts_with("Result:"));
        assert!(!f.issues.is_empty() && !f.issues[0].title.is_empty());
        let s = o.session.expect("session");
        assert_eq!(s.latest_id, Some(f.id));
        assert!(!s.problems.is_empty());
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
