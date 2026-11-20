//! The in-game window and the addon's options section (ImGui through Nexus).

use crate::client::{Client, Command, Snapshot, Status};
use crate::model::{Fight, Overlay, Session, result_color, severity_color, severity_label};
use crate::settings::Settings;
use nexus::imgui::{Condition, Slider, TreeNodeFlags, Ui, Window};
use std::path::PathBuf;

const GRAY: [f32; 4] = [0.65, 0.65, 0.65, 1.0];
const RED: [f32; 4] = [1.0, 0.36, 0.36, 1.0];
const ORANGE: [f32; 4] = [1.0, 0.62, 0.25, 1.0];
const GREEN: [f32; 4] = [0.4, 0.85, 0.45, 1.0];

pub struct App {
    pub client: Client,
    pub settings: Settings,
    settings_path: Option<PathBuf>,
    /// Fight being browsed; None follows the latest one.
    selected: Option<i64>,
    /// Latest fight id seen, to notice new fights for auto-show.
    last_latest: Option<i64>,
    show_when_out_of_combat: bool,
}

impl App {
    pub fn new(client: Client, settings_path: Option<PathBuf>) -> Self {
        let settings = settings_path.as_deref().map(Settings::load).unwrap_or_default();
        Self {
            client,
            settings,
            settings_path,
            selected: None,
            last_latest: None,
            show_when_out_of_combat: false,
        }
    }

    pub fn toggle(&mut self) {
        self.settings.open = !self.settings.open;
        self.save();
    }

    pub fn save(&self) {
        if let Some(path) = &self.settings_path
            && let Err(e) = self.settings.save(path)
        {
            log::warn!("could not save settings: {e}");
        }
    }

    fn select(&mut self, id: Option<i64>) {
        self.selected = id;
        self.client.send(Command::Select(id));
    }

    /// Notice a newly analyzed fight; with auto-show, open on it once out of combat.
    fn track_new_fights(&mut self, in_combat: bool) {
        let latest = {
            let snap = self.client.snapshot();
            snap.data.as_ref().and_then(|d| d.session.as_ref()).and_then(|s| s.latest_id)
        };
        if latest.is_some() && latest != self.last_latest {
            if self.last_latest.is_some() && self.settings.auto_show {
                self.show_when_out_of_combat = true;
                if self.selected.is_some() {
                    self.select(None);
                }
            }
            self.last_latest = latest;
        }
        if self.show_when_out_of_combat && !in_combat {
            self.show_when_out_of_combat = false;
            if !self.settings.open {
                self.settings.open = true;
                self.save();
            }
        }
    }

    pub fn render(&mut self, ui: &Ui, in_combat: bool) {
        self.track_new_fights(in_combat);
        if !self.settings.open || (self.settings.hide_in_combat && in_combat) {
            return;
        }
        let mut open = true;
        let mut actions: Vec<Action> = Vec::new();
        Window::new("WvW Analyzer###wvw_analyzer")
            .opened(&mut open)
            .size([460.0, 420.0], Condition::FirstUseEver)
            .bg_alpha(self.settings.opacity)
            .collapsible(false)
            .build(ui, || {
                let snap = self.client.snapshot();
                draw(ui, &snap, self.selected.is_some(), &mut actions);
            });
        for a in actions {
            match a {
                Action::Select(id) => self.select(id),
                Action::Record(on) => self.client.send(Command::SetRecording(on)),
            }
        }
        if !open {
            self.settings.open = false;
            self.save();
        }
    }

    pub fn render_options(&mut self, ui: &Ui) {
        let before = self.settings.clone();
        ui.text("WvW Analyzer");
        ui.checkbox("Show the window when a new fight is analyzed", &mut self.settings.auto_show);
        ui.checkbox("Hide the window in combat", &mut self.settings.hide_in_combat);
        Slider::new("Background opacity", 0.0, 1.0)
            .display_format("%.2f")
            .build(ui, &mut self.settings.opacity);
        ui.text_colored(
            GRAY,
            "Toggle the window with the Quick Access icon or ALT+SHIFT+W (Nexus keybinds).",
        );
        if self.settings != before {
            self.save();
        }
    }
}

enum Action {
    Select(Option<i64>),
    Record(bool),
}

fn draw(ui: &Ui, snap: &Snapshot, browsing: bool, actions: &mut Vec<Action>) {
    match &snap.status {
        Status::Searching => {
            ui.text_wrapped("WvW Analyzer isn't running.");
            ui.text_colored(GRAY, "Start the WvW Analyzer app (0.5.0 or newer) on this PC.");
            return;
        }
        Status::Incompatible(msg) => {
            ui.text_colored(ORANGE, "");
            ui.same_line();
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
                Some(f) => fight_tab(ui, f, browsing, actions),
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

fn fight_tab(ui: &Ui, f: &Fight, browsing: bool, actions: &mut Vec<Action>) {
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
    if browsing && f.next_id.is_some() {
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
