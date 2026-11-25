//! The Session tab: record and totals, a strip of the session's fights (a click opens one on
//! the Fight tab), then recurring problems and strengths in a scrolling list.

use super::theme::{self, Font, Metrics};
use super::widgets::{self, Block};
use super::{Action, Frame, Tab};
use crate::model::{Fact, Session};
use imgui::{ChildWindow, Ui};

/// "Raid, 21 Nov · 48:12 of fighting", right-aligned in the tab row (dropped without room).
pub fn meta(ui: &Ui, s: &Session, left: f32, right: f32, y: f32, row_h: f32) {
    let text = if s.name.is_empty() {
        format!("{} of fighting", s.duration)
    } else {
        format!("{} · {} of fighting", s.name, s.duration)
    };
    let w = widgets::text_size(ui, Font::Body12, &text)[0];
    if right - w >= left {
        widgets::text_mid(ui, Font::Body12, right - w, y, row_h, theme::MUTED, &text);
    }
}

fn plural(n: u32, word: &str) -> String {
    format!("{n} {word}{}", if n == 1 { "" } else { "s" })
}

/// The tiles: record with the fight count, kills, deaths, KDR.
pub fn facts(s: &Session) -> Vec<Fact> {
    let fact = |label: String, value: String, tone: &str| Fact {
        label,
        value,
        note: String::new(),
        tone: tone.into(),
    };
    vec![
        fact(plural(s.fights, "fight"), s.record.clone(), ""),
        fact("Kills".into(), s.kills.to_string(), "good"),
        fact("Deaths".into(), s.deaths.to_string(), "bad"),
        fact("KDR".into(), format!("{:.2}", s.kdr), ""),
    ]
}

pub fn tab(ui: &Ui, m: &Metrics, s: &Session, top: f32, frame: &mut Frame, tab: &mut Tab) {
    let pos = ui.window_pos();
    let w = ui.window_size()[0] - m.px(24.0);
    let x = pos[0] + m.px(12.0);
    let mut y = top + m.px(4.0);
    y += widgets::stat_tiles(ui, m, [x, y], w, &facts(s)) + m.px(10.0);
    if !s.strip.is_empty() {
        y += strip(ui, m, s, x, y, w, frame, tab);
    }
    ui.set_cursor_screen_pos([pos[0], y + m.px(12.0)]);
    ChildWindow::new("##session_list")
        .size([0.0, 0.0])
        .draw_background(false)
        .build(ui, || list(ui, m, s));
}

/// One small square per fight, oldest first, wrapping onto more lines. Returns the height.
#[allow(clippy::too_many_arguments)]
fn strip(
    ui: &Ui,
    m: &Metrics,
    s: &Session,
    x: f32,
    y: f32,
    w: f32,
    frame: &mut Frame,
    tab: &mut Tab,
) -> f32 {
    let (cell_w, cell_h, gap) = (m.px(26.0), m.px(22.0), m.px(4.0));
    let label_w = m.px(44.0);
    widgets::text_mid(ui, Font::Body12, x, y, cell_h, theme::MUTED, "Fights");
    let left = x + label_w;
    let per_row = (((x + w - left) + gap) / (cell_w + gap)).floor().max(1.0) as usize;
    for (i, f) in s.strip.iter().enumerate() {
        let (row, col) = (i / per_row, i % per_row);
        let p = [left + col as f32 * (cell_w + gap), y + row as f32 * (cell_h + gap)];
        let (clicked, hovered) = widgets::hit(ui, &format!("##strip{}", f.id), p, [cell_w, cell_h]);
        if clicked {
            *tab = Tab::Fight;
            frame.actions.push(Action::Select(Some(f.id)));
        }
        let tone = theme::result_tone(f.result.as_deref());
        let fill = [tone.fill[0], tone.fill[1], tone.fill[2], 0.2];
        let max = [p[0] + cell_w, p[1] + cell_h];
        widgets::rect(ui, p, max, fill, m.px(4.0));
        if hovered {
            widgets::outline(ui, p, max, tone.text, m.px(4.0));
        }
        let lw = widgets::text_size(ui, Font::Label11, &f.letter)[0];
        widgets::text_mid(
            ui,
            Font::Label11,
            p[0] + (cell_w - lw) / 2.0,
            p[1],
            cell_h,
            tone.text,
            &f.letter,
        );
    }
    let rows = s.strip.len().div_ceil(per_row);
    // The hint goes after the last square when it fits on that line.
    let last_col = (s.strip.len() - 1) % per_row;
    let hint = "click to open a fight";
    let hx = left + (last_col + 1) as f32 * (cell_w + gap) + m.px(2.0);
    if hx + widgets::text_size(ui, Font::Body12, hint)[0] <= x + w {
        let hy = y + (rows - 1) as f32 * (cell_h + gap);
        widgets::text_mid(ui, Font::Body12, hx, hy, cell_h, theme::MUTED, hint);
    }
    rows as f32 * (cell_h + gap) - gap
}

fn list(ui: &Ui, m: &Metrics, s: &Session) {
    let start = ui.cursor_screen_pos();
    let x = start[0] + m.px(12.0);
    let w = ui.content_region_avail()[0] - m.px(24.0);
    let mut y = start[1];
    let gap = m.px(6.0);
    let (pad_x, pad_y) = (m.px(12.0), m.px(8.0));
    let fights = s.fights.max(1);
    if !s.problems.is_empty() {
        y += widgets::section_label(ui, m, [x, y], "Recurring problems", None) + gap;
    }
    for p in &s.problems {
        let word = theme::severity_word(&p.severity);
        let tone = theme::severity_tone(&p.severity);
        let chip = widgets::chip_size(ui, m, word, false);
        let count = format!("{} of {} · {} lost", p.count, s.fights, p.losses);
        let count_w = widgets::text_size(ui, Font::Body12, &count)[0];
        let tx = x + pad_x + chip[0] + m.px(8.0);
        let title_w = (x + w - pad_x - count_w - m.px(8.0) - tx).max(m.px(40.0));
        let title = Block::new(ui, Font::Title13, &p.title, title_w);
        let head_h = chip[1].max(title.height());
        let bar_gap = m.px(6.0);
        let bar_h = m.px(4.0);
        let total = pad_y * 2.0 + head_h + bar_gap + bar_h;
        widgets::rect(ui, [x, y], [x + w, y + total], m.bg(theme::CARD), m.px(6.0));
        let first = title.line_h.min(head_h);
        widgets::chip(
            ui,
            m,
            [x + pad_x, y + pad_y + ((first - chip[1]) / 2.0).floor()],
            word,
            tone,
            false,
        );
        title.draw(ui, [tx, y + pad_y + ((head_h - title.height()) / 2.0).floor()], theme::TEXT);
        widgets::text_mid(
            ui,
            Font::Body12,
            x + w - pad_x - count_w,
            y + pad_y,
            first,
            theme::MUTED,
            &count,
        );
        let share = p.count as f32 / fights as f32;
        widgets::bar(
            ui,
            m,
            [x + pad_x, y + pad_y + head_h + bar_gap],
            w - pad_x * 2.0,
            share,
            tone.text,
        );
        y += total + gap;
    }
    if !s.strengths.is_empty() {
        y += m.px(8.0);
        y += widgets::section_label(ui, m, [x, y], "Strengths", None) + gap;
    }
    for p in &s.strengths {
        let count = format!("{} of {} fights", p.count, s.fights);
        let count_w = widgets::text_size(ui, Font::Body12, &count)[0];
        let dot_w = m.px(16.0);
        let title_w = (w - pad_x * 2.0 - dot_w - count_w - m.px(8.0)).max(m.px(40.0));
        let title = Block::new(ui, Font::Title13, &p.title, title_w);
        let total = pad_y * 2.0 + title.height();
        widgets::rect(ui, [x, y], [x + w, y + total], m.bg(theme::CARD), m.px(6.0));
        widgets::dot(
            ui,
            m,
            [x + pad_x + m.px(4.0), y + pad_y + title.line_h / 2.0],
            theme::GREEN_DOT,
        );
        title.draw(ui, [x + pad_x + dot_w, y + pad_y], theme::TEXT);
        widgets::text_mid(
            ui,
            Font::Body12,
            x + w - pad_x - count_w,
            y + pad_y,
            title.line_h,
            theme::MUTED,
            &count,
        );
        y += total + gap;
    }
    if s.problems.is_empty() && s.strengths.is_empty() {
        let line = "No recurring problems or strengths yet.";
        y += Block::new(ui, Font::Body13, line, w).draw(ui, [x, y], theme::MUTED);
    }
    ui.set_cursor_screen_pos([x, y]);
    ui.dummy([1.0, m.px(6.0)]);
}
