//! The states the preview draws, from synthetic payloads. The wording follows the mockups and
//! the analyzer's templates; no real players or accounts.

use WvWAnalyzer::client::{Snapshot, Status};
use WvWAnalyzer::model::Overlay;
use WvWAnalyzer::view::{self, Tab, ViewState};
use imgui::Ui;
use serde_json::{Value, json};
use std::cell::RefCell;

pub struct State {
    pub name: String,
    /// Main window size; None leaves the default.
    pub size: Option<[f32; 2]>,
    pub draw: Box<dyn Fn(&Ui)>,
}

fn main_window(name: &str, size: [f32; 2], snap: Snapshot, view: ViewState) -> State {
    let view = RefCell::new(view);
    State {
        name: name.into(),
        size: Some(size),
        draw: Box::new(move |ui| {
            view::main_window(ui, &mut view.borrow_mut(), &snap, 1.0, 1.0);
        }),
    }
}

/// The small panel after a fight, for the payload's fight.
fn glance(name: &str, v: Value) -> State {
    let fight = Overlay::parse(&v.to_string()).expect("payload parses").fight.expect("fight");
    State {
        name: name.into(),
        size: None,
        draw: Box::new(move |ui| {
            view::glance::panel(ui, &fight, 1.0, 1.0);
        }),
    }
}

/// A long session: the strip wraps, the record has every result.
fn many() -> Value {
    many_with(40)
}

fn many_with(fights: usize) -> Value {
    let mut v = win();
    let s = &mut v["session"];
    let results = ["win", "loss", "even", "skirmish"];
    let strip: Vec<Value> = (0..fights)
        .map(|i| {
            let r = results[(i * 7 + i / 3) % 4];
            json!({"id": i + 1, "result": r, "letter": &r[..1].to_uppercase()})
        })
        .collect();
    s["strip"] = json!(strip);
    s["fights"] = json!(fights);
    s["record"] = json!("21W 12L 5E 2S");
    s["kills"] = json!(1874);
    s["deaths"] = json!(1203);
    s["problems"][0]["title"] =
        json!("Stability gap during enemy bomb, again and again in the second half");
    s["problems"][0]["count"] = json!(17);
    s["problems"][3]["severity"] = json!("info");
    v
}

fn connected(v: Value) -> Snapshot {
    let data = Overlay::parse(&v.to_string()).expect("preview payload parses");
    Snapshot { status: Status::Connected, data: Some(data), action_error: None }
}

fn issue(severity: &str, title: &str, short: &str, fix: &str) -> Value {
    json!({"severity": severity, "title": title, "short": short, "fix": fix})
}

fn fact(label: &str, value: &str, note: &str, tone: &str) -> Value {
    json!({"label": label, "value": value, "note": note, "tone": tone})
}

fn session() -> Value {
    let results = ["win", "loss", "win", "win", "even", "loss", "win"];
    let strip: Vec<Value> = results
        .iter()
        .enumerate()
        .map(|(i, r)| json!({"id": i + 1, "result": r, "letter": &r[..1].to_uppercase()}))
        .collect();
    json!({
        "id": 1, "name": "Raid, 21 Nov", "fights": 7, "record": "4W 2L 1E", "kills": 312,
        "deaths": 198, "kdr": 1.58, "duration": "48:12", "recording": true, "latestId": 7,
        "problems": [
            {"title": "Stability gap during enemy bomb", "severity": "critical", "count": 3, "losses": 2},
            {"title": "Parties without support", "severity": "major", "count": 5, "losses": 2},
            {"title": "Outnumbered", "severity": "major", "count": 2, "losses": 2},
            {"title": "Players in tiny parties", "severity": "minor", "count": 6, "losses": 1}
        ],
        "strengths": [
            {"title": "Won the strip war", "count": 4},
            {"title": "Finished enemy downs", "count": 3}
        ],
        "strip": strip
    })
}

/// The mockup "Main": a win, browsing fight 3 of 7.
fn win() -> Value {
    json!({
        "schema": 1, "version": "0.7.0",
        "recording": {"active": true, "logDirOk": true},
        "queue": {"pending": 0, "busy": false},
        "latest": {"id": 7, "addedAt": "2026-11-21T21:32:00"},
        "session": session(),
        "fight": {
            "id": 3, "status": "done", "mode": "zerg", "result": "win",
            "title": "20:03  Seared Borderlands  12:54",
            "resultLine": "Result: win - 73 kills for 29 deaths, 28 (+2 allies) vs 59 enemies, 12:54.",
            "framing": null,
            "badge": "WIN", "heading": "Seared Borderlands", "meta": "20:03 · 12:54 long",
            "facts": [fact("Kills", "73", "", "good"), fact("Deaths", "29", "", "bad"),
                      fact("Squad", "28", "+2 allies", ""), fact("Enemies", "59", "", "")],
            "headline": "73 kills for 29 deaths", "numbers": "28+2 vs 59",
            "issuesTitle": "What to improve", "moreCount": 0,
            "issues": [
                issue("critical", "Stability gap during enemy bomb (12:28)",
                      "10 downed in one burst, 10 of them died; stab was low in party 3 (47%), 5 (21%). It happened 3 times (12:10, 12:19, 12:28).",
                      "Stagger firebrands and hold stab for the enemy push."),
                issue("major", "Parties without support", "party 6 lacked cleanses; 16 downs in them.",
                      "Give each party a stab provider and a healer/cleanser."),
                issue("minor", "Players in tiny parties", "3 players sat in parties 1, 7 with fewer than 3 members.",
                      "Invite them into full parties with a support."),
                issue("minor", "Players underperforming in their role", "2 players dealt under a third of their role's median damage.",
                      "Check builds and positioning with them after the raid.")
            ],
            "positives": [issue("positive", "Won the strip war", "we stripped 412 boons and lost 268.", "")],
            "debrief": ["Result: win - 73 kills for 29 deaths, 28 (+2 allies) vs 59 enemies, 12:54.",
                        "- Why: stab ran out during the enemy bomb at 12:28 (10 downed).",
                        "- Change next time: stagger firebrands and hold stab for their push.",
                        "- Went well: we won the strip war (412 to 268)."],
            "debriefUnverified": 1,
            "index": 3, "count": 7, "prevId": 2, "nextId": 4
        }
    })
}

/// The mockup "A-Loss": a short lost fight.
fn loss() -> Value {
    let mut v = win();
    v["fight"] = json!({
        "id": 2, "status": "done", "mode": "zerg", "result": "loss",
        "title": "20:41  Eternal Battlegrounds  0:36",
        "resultLine": "Result: loss - 0 kills for 6 deaths, 7 vs 28 enemies, 0:36.",
        "framing": null,
        "badge": "LOSS", "heading": "Eternal Battlegrounds", "meta": "20:41 · 0:36 long",
        "facts": [fact("Kills", "0", "", "good"), fact("Deaths", "6", "", "bad"),
                  fact("Squad", "7", "", ""), fact("Enemies", "28", "", "")],
        "headline": "0 kills for 6 deaths", "numbers": "7 vs 28",
        "issuesTitle": "Why this fight was lost", "moreCount": 0,
        "issues": [
            issue("critical", "Lost the opening exchange", "4 downed within 2.0s from 0:26; enemy downs by then: 0.",
                  "Engage only with full boons, pre-stacked on the tag."),
            issue("major", "Outnumbered (4.0x)", "28 enemies against our 7 (4.0x).",
                  "Use chokes, walls and siege against bigger groups."),
            issue("major", "Losing the strip war", "we lost 63 boons to strips and stripped 6; real strippers: 2.",
                  "More strip builds; strip right before our bomb."),
            issue("minor", "Downed allies were not picked up", "6 of our 7 downs died; resurrects: 0.",
                  "Assign rezzers; use banners and downed heals.")
        ],
        "positives": [], "debrief": [], "debriefUnverified": 0,
        "index": 2, "count": 7, "prevId": 1, "nextId": 3
    });
    v
}

/// The mockup "A-Clean": the newest fight, a clean win.
fn clean() -> Value {
    let mut v = win();
    v["fight"] = json!({
        "id": 7, "status": "done", "mode": "zerg", "result": "win",
        "title": "21:32  Green Alpine Borderlands  3:10",
        "resultLine": "Result: win - 31 kills for 2 deaths, 30 vs 34 enemies, 3:10.",
        "framing": "Clean win, only small things to tidy up:",
        "badge": "WIN", "heading": "Green Alpine Borderlands", "meta": "21:32 · 3:10 long",
        "facts": [fact("Kills", "31", "", "good"), fact("Deaths", "2", "", "bad"),
                  fact("Squad", "30", "", ""), fact("Enemies", "34", "", "")],
        "headline": "31 kills for 2 deaths", "numbers": "30 vs 34",
        "issuesTitle": "What to improve", "moreCount": 0,
        "issues": [
            issue("minor", "Players in tiny parties", "3 players sat in parties 1, 7 with fewer than 3 members.",
                  "Invite them into full parties with a support."),
            issue("minor", "Players underperforming in their role", "2 players dealt under a third of their role's median damage.",
                  "Check builds and positioning with them after the raid.")
        ],
        "positives": [], "debrief": [], "debriefUnverified": 0,
        "index": 7, "count": 7, "prevId": 6, "nextId": null
    });
    v
}

/// Five open cards with long titles: the list scrolls; one more issue stays in the app.
fn long() -> Value {
    let mut v = loss();
    let f = &mut v["fight"];
    f["issues"] = json!([
        issue(
            "critical",
            "Stability gap during enemy bomb, and the second push right after it (12:28)",
            "10 downed in one burst, 10 of them died; stab was low in party 3 (47%), 5 (21%). It happened 3 times (12:10, 12:19, 12:28).",
            "Stagger firebrands and hold stab for the enemy push; call the second push before it lands."
        ),
        issue(
            "critical",
            "Lost the opening exchange",
            "4 downed within 2.0s from 0:26; enemy downs by then: 0.",
            "Engage only with full boons, pre-stacked on the tag."
        ),
        issue(
            "major",
            "Outnumbered (4.0x)",
            "28 enemies against our 7 (4.0x).",
            "Use chokes, walls and siege against bigger groups."
        ),
        issue(
            "major",
            "Losing the strip war",
            "we lost 63 boons to strips and stripped 6; real strippers: 2.",
            "More strip builds; strip right before our bomb."
        ),
        issue(
            "major",
            "Parties without support",
            "party 6 lacked cleanses; 16 downs in them.",
            "Give each party a stab provider and a healer/cleanser."
        )
    ]);
    f["moreCount"] = json!(1);
    f["heading"] = json!("Desert Borderlands");
    v
}

/// An app older than 0.7.0: none of the new fields.
fn old_app() -> Value {
    let mut v = loss();
    let f = v["fight"].as_object_mut().unwrap();
    for k in
        ["badge", "heading", "meta", "facts", "headline", "numbers", "issuesTitle", "moreCount"]
    {
        f.remove(k);
    }
    v
}

pub fn all() -> Vec<State> {
    let empty = {
        let mut v = win();
        v["fight"] = Value::Null;
        v["queue"] = json!({"pending": 2, "busy": true});
        v
    };
    let mut loss_view = ViewState::default();
    loss_view.set_open(2, "Downed allies were not picked up", true);
    let mut session_view = ViewState::default();
    session_view.tab = Tab::Session;
    vec![
        main_window("main", [460.0, 660.0], connected(win()), ViewState::default()),
        main_window("loss", [460.0, 640.0], connected(loss()), loss_view),
        main_window("clean", [460.0, 400.0], connected(clean()), ViewState::default()),
        main_window("empty", [460.0, 230.0], connected(empty), ViewState::default()),
        main_window(
            "not-running",
            [460.0, 190.0],
            Snapshot { status: Status::Searching, data: None, action_error: None },
            ViewState::default(),
        ),
        main_window(
            "problem",
            [460.0, 190.0],
            Snapshot {
                status: Status::Problem(
                    "WvW Analyzer 0.9.0 sends data this addon can't read. Update the in-game \
                     addon from WvW Analyzer > Settings."
                        .into(),
                ),
                data: None,
                action_error: None,
            },
            ViewState::default(),
        ),
        main_window("main-360", [360.0, 660.0], connected(win()), ViewState::default()),
        main_window("long-scroll", [460.0, 600.0], connected(long()), ViewState::default()),
        main_window("long-360", [360.0, 600.0], connected(long()), ViewState::default()),
        main_window("old-app", [460.0, 500.0], connected(old_app()), ViewState::default()),
        main_window("session", [460.0, 560.0], connected(win()), session_view),
        main_window("session-many", [460.0, 600.0], connected(many()), {
            let mut v = ViewState::default();
            v.tab = Tab::Session;
            v
        }),
        main_window("session-360", [360.0, 600.0], connected(many()), {
            let mut v = ViewState::default();
            v.tab = Tab::Session;
            v
        }),
        // A very long session in a short window: the strip scrolls with the lists.
        main_window("session-90-short", [360.0, 420.0], connected(many_with(90)), {
            let mut v = ViewState::default();
            v.tab = Tab::Session;
            v
        }),
        glance("glance", win()),
        glance("glance-clean", clean()),
        glance("glance-long", long()),
    ]
}
