//! Empty and error states: a centered title with one muted line under it.

use super::theme::{self, Font, Metrics};
use super::widgets::Block;
use imgui::Ui;

/// Centers `title` and `line` in the window below `top`.
pub fn centered(ui: &Ui, m: &Metrics, top: f32, title: &str, line: &str) {
    let pos = ui.window_pos();
    let size = ui.window_size();
    let width = (size[0] - m.px(64.0)).max(m.px(120.0));
    let t = Block::new(ui, Font::Heading15, title, width);
    let l = Block::new(ui, Font::Body13, line, width);
    let gap = m.px(4.0);
    let total = t.height() + gap + l.height();
    let bottom = pos[1] + size[1] - m.px(16.0);
    let y = (top + ((bottom - top - total) / 2.0).max(m.px(8.0))).floor();
    let cx = pos[0] + size[0] / 2.0;
    t.draw_centered(ui, cx, y, theme::TEXT);
    l.draw_centered(ui, cx, y + t.height() + gap, theme::MUTED);
}
