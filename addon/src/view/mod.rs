//! Everything the overlay draws, independent of Nexus: the same code runs in the game and in
//! the preview program (`cargo run --example preview`). It only reads the payload and reports
//! what the player clicked as [`Action`]s; `ui.rs` carries them out.

use crate::client::{Snapshot, Status};
use crate::model::{Fight, Overlay, Session, result_color, severity_color, severity_label};
use imgui::{Condition, TreeNodeFlags, Ui, Window};

const GRAY: [f32; 4] = [0.65, 0.65, 0.65, 1.0];
const RED: [f32; 4] = [1.0, 0.36, 0.36, 1.0];
const ORANGE: [f32; 4] = [1.0, 0.62, 0.25, 1.0];
const GREEN: [f32; 4] = [0.4, 0.85, 0.45, 1.0];

/// What the player asked for this frame.
#[derive(Debug, Clone, PartialEq)]
pub enum Action {
    /// Show this fight, or the latest one.
    Select(Option<i64>),
    Record(bool),
}

/// Result of drawing the main window for one frame.
#[derive(Debug, Default)]
pub struct Frame {
    pub actions: Vec<Action>,
    /// The current session's newest fight, as the payload says.
    pub latest: Option<i64>,
    /// False once the player closed the window.
    pub open: bool,
}

/// The main window.
pub fn main_window(ui: &Ui, snap: &Snapshot, opacity: f32) -> Frame {
    let mut open = true;
    let mut actions = Vec::new();
    let latest = snap.data.as_ref().and_then(|d| d.latest.as_ref()).map(|l| l.id);
    Window::new("WvW Analyzer###wvw_analyzer")
        .opened(&mut open)
        .size([460.0, 420.0], Condition::FirstUseEver)
        .bg_alpha(opacity)
        .collapsible(false)
        .build(ui, || draw(ui, snap, latest, &mut actions));
    Frame { actions, latest, open }
}

fn draw(ui: &Ui, snap: &Snapshot, latest: Option<i64>, actions: &mut Vec<Action>) {
    match &snap.status {
        Status::Searching => {
            ui.text_wrapped("WvW Analyzer isn't running.");
            ui.text_colored(GRAY, "Start the WvW Analyzer app (0.5.0 or newer) on this PC.");
            return;
        }
        Status::Problem(msg) => {
            ui.text_wrapped(msg);
            return;
        }
        Status::Connected => {}
    }
    let Some(data) = &snap.data else { return };
    status_line(ui, data, actions);
    if let Some(err) = &snap.action_error {
        ui.text_colored(RED, err);
    }
    ui.separator();
    if let Some(_bar) = ui.tab_bar("tabs") {
        if let Some(_tab) = ui.tab_item("Fight") {
            match &data.fight {
                Some(f) => fight_tab(ui, f, latest, actions),
                None => ui.text_colored(GRAY, "No analyzed fights in this session yet."),
            }
        }
        if let Some(_tab) = ui.tab_item("Session") {
            match &data.session {
                Some(s) => session_tab(ui, s),
                None => ui.text_colored(GRAY, "No sessions yet."),
            }
        }
    }
}

fn status_line(ui: &Ui, data: &Overlay, actions: &mut Vec<Action>) {
    if data.recording.active {
        ui.text_colored(GREEN, "Recording");
        ui.same_line();
        if ui.small_button("Stop") {
            actions.push(Action::Record(false));
        }
    } else {
        ui.text_colored(GRAY, "Not recording");
        ui.same_line();
        if ui.small_button("Start recording") {
            actions.push(Action::Record(true));
        }
    }
    if data.queue.busy || data.queue.pending > 0 {
        ui.same_line();
        let queued = if data.queue.pending > 0 {
            format!("  Analyzing ({} queued)", data.queue.pending)
        } else {
            "  Analyzing...".to_string()
        };
        ui.text_colored(GRAY, queued);
    }
}

fn fight_tab(ui: &Ui, f: &Fight, latest: Option<i64>, actions: &mut Vec<Action>) {
    // Navigation: older < Fight n of N > newer, Latest.
    if let Some(prev) = f.prev_id {
        if ui.small_button("<") {
            actions.push(Action::Select(Some(prev)));
        }
    } else {
        ui.text_colored(GRAY, " ");
    }
    ui.same_line();
    match f.index {
        Some(i) => ui.text(format!("Fight {i} of {}", f.count)),
        None => ui.text("Fight"),
    }
    if let Some(next) = f.next_id {
        ui.same_line();
        if ui.small_button(">") {
            actions.push(Action::Select(Some(next)));
        }
    }
    // Browsing anything but the current session's newest fight (maybe in an older session).
    if latest.is_some_and(|id| id != f.id) {
        ui.same_line();
        if ui.small_button("Latest") {
            actions.push(Action::Select(None));
        }
    }

    ui.text(&f.title);
    for line in f.result_line.lines() {
        ui.text_colored(result_color(f.result.as_deref()), line);
    }
    if let Some(framing) = &f.framing {
        ui.text_wrapped(framing);
    }
    ui.spacing();

    if f.issues.is_empty() {
        ui.text_colored(GRAY, "No problems found.");
    }
    for n in &f.issues {
        ui.text_colored(severity_color(&n.severity), format!("[{}]", severity_label(&n.severity)));
        ui.same_line();
        ui.text_wrapped(&n.title);
        ui.indent();
        if !n.short.is_empty() {
            ui.text_wrapped(&n.short);
        }
        if !n.fix.is_empty() {
            ui.text_colored(GRAY, "Next time:");
            ui.same_line();
            ui.text_wrapped(&n.fix);
        }
        ui.unindent();
    }
    if !f.positives.is_empty() {
        ui.spacing();
        for n in &f.positives {
            ui.text_colored(GREEN, "[Went well]");
            ui.same_line();
            ui.text_wrapped(&n.title);
            if !n.short.is_empty() {
                ui.indent();
                ui.text_wrapped(&n.short);
                ui.unindent();
            }
        }
    }
    if !f.debrief.is_empty() {
        ui.spacing();
        if ui.collapsing_header("Debrief (worded by the local LLM)", TreeNodeFlags::empty()) {
            for line in &f.debrief {
                ui.text_wrapped(line);
            }
            if f.debrief_unverified > 0 {
                ui.text_colored(ORANGE, "Some numbers in this debrief couldn't be checked.");
            }
        }
    }
}

fn session_tab(ui: &Ui, s: &Session) {
    ui.text(&s.name);
    if s.recording {
        ui.same_line();
        ui.text_colored(GREEN, "(recording)");
    }
    ui.text(format!("{} fights: {}   fight time {}", s.fights, s.record, s.duration));
    ui.text(format!("Kills {}   deaths {}   KDR {:.2}", s.kills, s.deaths, s.kdr));
    ui.spacing();
    if !s.problems.is_empty() {
        ui.text("Recurring problems");
        for p in &s.problems {
            ui.text_colored(severity_color(&p.severity), "-");
            ui.same_line();
            ui.text_wrapped(format!("{}: {} fights ({} lost)", p.title, p.count, p.losses));
        }
    }
    if !s.strengths.is_empty() {
        ui.spacing();
        ui.text("Strengths");
        for p in &s.strengths {
            ui.text_colored(GREEN, "-");
            ui.same_line();
            ui.text_wrapped(format!("{}: {} fights", p.title, p.count));
        }
    }
}
