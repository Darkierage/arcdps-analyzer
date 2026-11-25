//! The Nexus glue around `view`: when the window shows, its settings, and carrying out what
//! the player clicked. The options section lives here too.

use crate::client::{Client, Command};
use crate::model::NewFights;
use crate::settings::{AfterFight, Settings};
use crate::view::glance::{self, GlanceAction, GlanceRules};
use crate::view::{self, Action};
use imgui::{Slider, Ui};
use std::path::PathBuf;

const GRAY: [f32; 4] = [0.65, 0.65, 0.65, 1.0];

pub struct App {
    pub client: Client,
    pub settings: Settings,
    settings_path: Option<PathBuf>,
    /// Options changed but not written yet (waits until no slider is being dragged).
    settings_dirty: bool,
    new_fights: NewFights,
    show_when_out_of_combat: bool,
    view: view::ViewState,
    glance: GlanceRules,
}

impl App {
    pub fn new(client: Client, settings_path: Option<PathBuf>) -> Self {
        let settings = settings_path.as_deref().map(Settings::load).unwrap_or_default();
        Self {
            client,
            settings,
            settings_path,
            settings_dirty: false,
            new_fights: NewFights::default(),
            show_when_out_of_combat: false,
            view: view::ViewState::default(),
            glance: GlanceRules::default(),
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

    /// Show a fight; picking the current session's newest one means following the latest again.
    fn select(&mut self, id: Option<i64>, latest: Option<i64>) {
        let id = if id.is_some() && id == latest { None } else { id };
        self.client.send(Command::Select(id));
    }

    /// Notice a newly analyzed fight and do what "After a fight" says: show the small panel,
    /// open the full window on it once out of combat, or nothing. With the full window open, a
    /// new fight only moves it to the newest fight.
    fn track_new_fights(&mut self, in_combat: bool) {
        let is_new = {
            let snap = self.client.snapshot();
            match &snap.data {
                Some(d) => self.new_fights.observe(d.latest.as_ref()),
                None => false,
            }
        };
        if is_new {
            match self.settings.after_fight {
                AfterFight::Panel => {
                    self.glance.new_fight(self.settings.open);
                    self.view.tab = view::Tab::Fight;
                    self.client.send(Command::Select(None));
                }
                AfterFight::Window => {
                    self.show_when_out_of_combat = true;
                    self.view.tab = view::Tab::Fight;
                    self.client.send(Command::Select(None));
                }
                AfterFight::Nothing => {}
            }
        }
        if self.show_when_out_of_combat && !in_combat {
            self.show_when_out_of_combat = false;
            if !self.settings.open {
                self.settings.open = true;
                self.save();
            }
        }
    }

    pub fn render(&mut self, ui: &Ui, in_combat: bool, scale: f32) {
        self.track_new_fights(in_combat);
        self.render_glance(ui, in_combat, scale);
        if !self.settings.open || (self.settings.hide_in_combat && in_combat) {
            return;
        }
        let snap = self.client.snapshot();
        let frame = view::main_window(ui, &mut self.view, &snap, scale, self.settings.opacity);
        drop(snap);
        for a in frame.actions {
            match a {
                Action::Select(id) => self.select(id, frame.latest),
                Action::Record(on) => self.client.send(Command::SetRecording(on)),
            }
        }
        if !frame.open {
            self.settings.open = false;
            self.save();
        }
    }

    /// The small panel after a fight, while its rules say so.
    fn render_glance(&mut self, ui: &Ui, in_combat: bool, scale: f32) {
        let snap = self.client.snapshot();
        let latest = snap.data.as_ref().and_then(|d| d.latest.as_ref()).map(|l| l.id);
        let fight = snap.data.as_ref().and_then(|d| d.fight.as_ref());
        let ready = fight.is_some_and(|f| Some(f.id) == latest);
        if !self.glance.update(in_combat, self.settings.open, ready) {
            return;
        }
        let Some(f) = fight else { return };
        let action = glance::panel(ui, f, scale, self.settings.opacity);
        drop(snap);
        match action {
            Some(GlanceAction::Dismiss) => self.glance.hide(),
            Some(GlanceAction::OpenDebrief) => {
                self.glance.hide();
                self.view.tab = view::Tab::Fight;
                self.client.send(Command::Select(None));
                self.settings.open = true;
                self.save();
            }
            None => {}
        }
    }

    pub fn render_options(&mut self, ui: &Ui) {
        let before = self.settings.clone();
        ui.text("WvW Analyzer");
        ui.text("After a fight:");
        ui.radio_button(
            "Show a small panel with the result",
            &mut self.settings.after_fight,
            AfterFight::Panel,
        );
        ui.radio_button("Open the full window", &mut self.settings.after_fight, AfterFight::Window);
        ui.radio_button("Do nothing", &mut self.settings.after_fight, AfterFight::Nothing);
        ui.checkbox("Hide the window in combat", &mut self.settings.hide_in_combat);
        Slider::new("Background opacity", 0.0, 1.0)
            .display_format("%.2f")
            .build(ui, &mut self.settings.opacity);
        ui.text_colored(
            GRAY,
            "Toggle the window with the Quick Access icon or ALT+SHIFT+W (Nexus keybinds).",
        );
        // Saved once the slider is let go, not on every frame of a drag.
        self.settings_dirty |= self.settings != before;
        if self.settings_dirty && !ui.is_any_item_active() {
            self.settings_dirty = false;
            self.save();
        }
    }
}
