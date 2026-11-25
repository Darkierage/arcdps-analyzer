//! The Session tab.

use super::theme::{self, Font, Metrics};
use super::widgets::{self, Block};
use super::{Frame, Tab};
use crate::model::Session;
use imgui::Ui;

/// "Raid · 48:12 of fighting", right-aligned in the tab row (dropped when there's no room).
pub fn meta(ui: &Ui, m: &Metrics, s: &Session, left: f32, right: f32, y: f32, row_h: f32) {
    let text = format!("{} · {} of fighting", s.name, s.duration);
    let w = widgets::text_size(ui, Font::Body12, &text)[0];
    if right - w >= left {
        widgets::text_mid(ui, Font::Body12, right - w, y, row_h, theme::MUTED, &text);
    }
    let _ = m;
}

pub fn tab(ui: &Ui, m: &Metrics, s: &Session, top: f32, _frame: &mut Frame, _tab: &mut Tab) {
    let pos = ui.window_pos();
    let w = ui.window_size()[0] - m.px(24.0);
    let x = pos[0] + m.px(12.0);
    let text = format!(
        "{} fights: {}   Kills {}   Deaths {}   KDR {:.2}",
        s.fights, s.record, s.kills, s.deaths, s.kdr
    );
    Block::new(ui, Font::Body13, &text, w).draw(ui, [x, top + m.px(4.0)], theme::TEXT);
}
