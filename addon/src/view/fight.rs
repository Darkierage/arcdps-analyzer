//! The Fight tab: the result block (badge, heading, meta, stat tiles), then a scrolling list of
//! issue cards, "went well" cards and the LLM debrief row.

use super::rules::{capitalize_first, starts_open};
use super::theme::{self, Font, Metrics};
use super::widgets::{self, Block, ButtonStyle, Icon};
use super::{Action, Frame, ViewState};
use crate::model::{Fight, Note};
use imgui::{ChildWindow, Ui};

/// Older and newer arrows around "Fight n of N", then **Latest** when the fight on screen isn't
/// the current session's newest one. Right-aligned to `right`.
#[allow(clippy::too_many_arguments)]
pub fn navigation(
    ui: &Ui,
    m: &Metrics,
    f: &Fight,
    latest: Option<i64>,
    right: f32,
    y: f32,
    row_h: f32,
    actions: &mut Vec<Action>,
) {
    let side = m.px(24.0);
    let gap = m.px(8.0);
    let top = y + ((row_h - side) / 2.0).floor();
    let mut x = right;
    // Browsing anything but the current session's newest fight (maybe in an older session).
    if latest.is_some_and(|id| id != f.id) {
        let size = widgets::button_size(ui, m, "Latest", side);
        x -= size[0];
        if widgets::button(ui, m, "##latest", [x, top], "Latest", side, ButtonStyle::Outline) {
            actions.push(Action::Select(None));
        }
        x -= gap;
    }
    x -= side;
    if let Some(next) = f.next_id
        && widgets::icon_button(ui, m, "##newer", [x, top], side, Icon::Right, true)
    {
        actions.push(Action::Select(Some(next)));
    }
    let label = match f.index {
        Some(i) => format!("Fight {i} of {}", f.count),
        None => "Fight".to_string(),
    };
    let lw = widgets::text_size(ui, Font::Body12, &label)[0];
    let slot = lw.max(m.px(62.0));
    x -= gap + slot;
    widgets::text_mid(ui, Font::Body12, x + (slot - lw) / 2.0, y, row_h, theme::SECONDARY, &label);
    x -= gap + side;
    if let Some(prev) = f.prev_id
        && widgets::icon_button(ui, m, "##older", [x, top], side, Icon::Left, true)
    {
        actions.push(Action::Select(Some(prev)));
    }
}

/// The tab below the tab row: the result block stays put, the list under it scrolls.
pub fn tab(ui: &Ui, m: &Metrics, state: &mut ViewState, f: &Fight, top: f32, frame: &mut Frame) {
    let pos = ui.window_pos();
    let w = ui.window_size()[0];
    let x = pos[0] + m.px(12.0);
    let y = top + m.px(4.0);
    let h = result_block(ui, m, f, x, y, w - m.px(24.0));
    ui.set_cursor_screen_pos([pos[0], y + h + m.px(12.0)]);
    ChildWindow::new("##fight_list")
        .size([0.0, 0.0])
        .draw_background(false)
        .build(ui, || list(ui, m, state, f, frame));
}

/// Badge, heading and meta, then the stat tiles. An app older than 0.7.0 sends none of them:
/// then its title and result line show instead. Returns the height.
fn result_block(ui: &Ui, m: &Metrics, f: &Fight, x: f32, y: f32, w: f32) -> f32 {
    if !f.has_header() {
        let mut h = Block::new(ui, Font::Heading15, &f.title, w).draw(ui, [x, y], theme::TEXT);
        let tone = theme::result_tone(f.result.as_deref());
        h += Block::new(ui, Font::Body13, &f.result_line, w).draw(ui, [x, y + h], tone.text);
        return h;
    }
    let tone = theme::result_tone(f.result.as_deref());
    let badge = widgets::chip_size(ui, m, &f.badge, true);
    let heading_h = widgets::line_height(ui, Font::Heading15);
    let row_h = badge[1].max(heading_h);
    widgets::chip(ui, m, [x, y + ((row_h - badge[1]) / 2.0).floor()], &f.badge, tone, true);
    let hx = x + badge[0] + m.px(8.0);
    let heading_w = widgets::text_size(ui, Font::Heading15, &f.heading)[0];
    let meta_w = widgets::text_size(ui, Font::Body12, &f.meta)[0];
    let meta_inline = hx + heading_w + m.px(8.0) + meta_w <= x + w;
    {
        let _font = theme::font(ui, Font::Heading15);
        let dl = ui.get_window_draw_list();
        let ty = y + ((row_h - widgets::font_size()) / 2.0).floor();
        dl.with_clip_rect_intersect([hx, y], [x + w, y + row_h], || {
            dl.add_text([hx, ty], theme::TEXT, &f.heading);
        });
    }
    let mut h = row_h;
    if meta_inline {
        widgets::text_mid(ui, Font::Body12, x + w - meta_w, y, row_h, theme::MUTED, &f.meta);
    } else {
        // Too narrow for both: the meta goes under the heading.
        let lh = widgets::line_height(ui, Font::Body12);
        widgets::text_mid(ui, Font::Body12, hx, y + h, lh, theme::MUTED, &f.meta);
        h += lh;
    }
    h += m.px(10.0);
    h + widgets::stat_tiles(ui, m, [x, y + h], w, &f.facts)
}

fn list(ui: &Ui, m: &Metrics, state: &mut ViewState, f: &Fight, _frame: &mut Frame) {
    let start = ui.cursor_screen_pos();
    let x = start[0] + m.px(12.0);
    let w = ui.content_region_avail()[0] - m.px(24.0);
    let mut y = start[1];
    let gap = m.px(6.0);
    if let Some(framing) = &f.framing {
        y += Block::new(ui, Font::Body13, framing, w).draw(ui, [x, y], theme::SECONDARY) + gap;
    } else if !f.issues.is_empty() {
        let title = if f.issues_title.is_empty() { "Key issues" } else { &f.issues_title };
        y += widgets::section_label(ui, m, [x, y], title, Some(f.issues.len())) + gap;
    }
    if f.issues.is_empty() {
        y += Block::new(ui, Font::Body13, "No problems found.", w).draw(ui, [x, y], theme::MUTED)
            + gap;
    }
    for (i, n) in f.issues.iter().enumerate() {
        y += issue_card(ui, m, state, f, i, n, x, y, w) + gap;
    }
    if f.more_count > 0 {
        let more = format!("{} more in the app", f.more_count);
        y += Block::new(ui, Font::Body12, &more, w).draw(ui, [x, y], theme::MUTED) + gap;
    }
    if !f.positives.is_empty() {
        y += m.px(8.0);
        y += widgets::section_label(ui, m, [x, y], "Went well", None) + gap;
        for n in &f.positives {
            y += positive_card(ui, m, n, x, y, w) + gap;
        }
    }
    if !f.debrief.is_empty() {
        y += m.px(2.0);
        y += debrief_row(ui, m, state, f, x, y, w) + gap;
    }
    // Room under the last item, and the scroll height.
    ui.set_cursor_screen_pos([x, y]);
    ui.dummy([1.0, m.px(6.0)]);
}

/// One issue: severity chip, title and a chevron; open, also the fact, a line and "NEXT TIME"
/// with the fix. A click on the header opens or closes it. Returns the height.
#[allow(clippy::too_many_arguments)]
fn issue_card(
    ui: &Ui,
    m: &Metrics,
    state: &mut ViewState,
    f: &Fight,
    i: usize,
    n: &Note,
    x: f32,
    y: f32,
    w: f32,
) -> f32 {
    let key = (f.id, n.title.clone());
    let default_open = starts_open(&f.issues, i);
    let mut open = state.toggled.get(&key).copied().unwrap_or(default_open);
    let pad_x = m.px(12.0);
    let pad_y = if open { m.px(10.0) } else { m.px(8.0) };
    let word = theme::severity_word(&n.severity);
    let chip = widgets::chip_size(ui, m, word, false);
    let chevron = m.px(12.0);
    let title_x = x + pad_x + chip[0] + m.px(8.0);
    let title_w = (x + w - pad_x - chevron - m.px(8.0) - title_x).max(m.px(40.0));
    let title = Block::new(ui, Font::Title13, &n.title, title_w);
    let head_h = chip[1].max(title.height());
    let head_area = [w, pad_y + head_h + if open { m.px(4.0) } else { pad_y }];
    let (clicked, hovered) = widgets::hit(ui, &format!("##issue{i}"), [x, y], head_area);
    if clicked {
        open = !open;
        state.toggled.insert(key.clone(), open);
    }
    let by_click = open && !default_open;
    let highlight = hovered || by_click;

    // Measure the open part.
    let inner = w - pad_x * 2.0;
    let fact = (open && !n.short.is_empty())
        .then(|| Block::new(ui, Font::Body13, &capitalize_first(&n.short), inner));
    let label = "NEXT TIME";
    let label_w = widgets::text_size(ui, Font::Label11, label)[0];
    let fix = (open && !n.fix.is_empty())
        .then(|| Block::new(ui, Font::Body13, &n.fix, inner - label_w - m.px(8.0)));
    let gap = m.px(6.0);
    let mut body_h = 0.0;
    if let Some(b) = &fact {
        body_h += gap + b.height();
    }
    if let Some(b) = &fix {
        body_h += gap + 1.0 + gap + b.height();
    }
    let total = pad_y * 2.0 + head_h + body_h;

    let bg = if highlight { theme::CARD_HOVER } else { theme::CARD };
    widgets::rect(ui, [x, y], [x + w, y + total], m.bg(bg), m.px(6.0));
    let first_line = title.line_h.min(head_h);
    widgets::chip(
        ui,
        m,
        [x + pad_x, y + pad_y + ((first_line - chip[1]) / 2.0).floor()],
        word,
        theme::severity_tone(&n.severity),
        false,
    );
    title.draw(ui, [title_x, y + pad_y + ((head_h - title.height()) / 2.0).floor()], theme::TEXT);
    let chevron_color = if highlight { theme::TEXT } else { theme::MUTED };
    widgets::icon(
        ui,
        m,
        [x + w - pad_x - chevron / 2.0, y + pad_y + first_line / 2.0],
        if open { Icon::Up } else { Icon::Down },
        chevron_color,
    );
    let mut cy = y + pad_y + head_h;
    if let Some(b) = &fact {
        cy += gap;
        cy += b.draw(ui, [x + pad_x, cy], theme::SECONDARY);
    }
    if let Some(b) = &fix {
        cy += gap;
        let line = if highlight { theme::LINE_HOVER } else { theme::LINE };
        widgets::hline(ui, x + pad_x, x + w - pad_x, cy, line);
        cy += 1.0 + gap;
        let lh = b.line_h;
        widgets::text_mid(ui, Font::Label11, x + pad_x, cy, lh, theme::MUTED, label);
        b.draw(ui, [x + pad_x + label_w + m.px(8.0), cy], theme::TEXT);
    }
    total
}

/// A "went well" card: green dot, title, the fact. Returns the height.
fn positive_card(ui: &Ui, m: &Metrics, n: &Note, x: f32, y: f32, w: f32) -> f32 {
    let (pad_x, pad_y) = (m.px(12.0), m.px(8.0));
    let dot_w = m.px(8.0) + m.px(8.0);
    let title = Block::new(ui, Font::Title13, &n.title, w - pad_x * 2.0 - dot_w);
    let fact = (!n.short.is_empty())
        .then(|| Block::new(ui, Font::Body13, &capitalize_first(&n.short), w - pad_x * 2.0));
    let gap = m.px(4.0);
    let total = pad_y * 2.0 + title.height() + fact.as_ref().map_or(0.0, |b| gap + b.height());
    widgets::rect(ui, [x, y], [x + w, y + total], m.bg(theme::CARD), m.px(6.0));
    widgets::dot(ui, m, [x + pad_x + m.px(4.0), y + pad_y + title.line_h / 2.0], theme::GREEN_DOT);
    title.draw(ui, [x + pad_x + dot_w, y + pad_y], theme::TEXT);
    if let Some(b) = &fact {
        b.draw(ui, [x + pad_x, y + pad_y + title.height() + gap], theme::SECONDARY);
    }
    total
}

/// The LLM debrief: a closed row at the bottom; opened, its lines and the "couldn't be checked"
/// note. Returns the height.
fn debrief_row(
    ui: &Ui,
    m: &Metrics,
    state: &mut ViewState,
    f: &Fight,
    x: f32,
    y: f32,
    w: f32,
) -> f32 {
    let (pad_x, pad_y) = (m.px(12.0), m.px(8.0));
    let label = "Debrief, worded by the local LLM";
    let lh = widgets::line_height(ui, Font::Body12);
    let mut open = state.debrief_open.contains(&f.id);
    let (clicked, hovered) = widgets::hit(ui, "##debrief", [x, y], [w, pad_y * 2.0 + lh]);
    if clicked {
        open = !open;
        if open {
            state.debrief_open.insert(f.id);
        } else {
            state.debrief_open.remove(&f.id);
        }
    }
    let inner = w - pad_x * 2.0;
    let lines: Vec<Block> = if open {
        f.debrief.iter().map(|l| Block::new(ui, Font::Body13, l, inner)).collect()
    } else {
        Vec::new()
    };
    let note = (open && f.debrief_unverified > 0).then(|| {
        Block::new(ui, Font::Body12, "Some numbers in this debrief couldn't be checked.", inner)
    });
    let gap = m.px(4.0);
    let mut total = pad_y * 2.0 + lh;
    if open {
        total += lines.iter().map(|b| b.height() + gap).sum::<f32>() + m.px(2.0);
        total += note.as_ref().map_or(0.0, |b| b.height() + gap);
    }
    if hovered {
        widgets::rect(ui, [x, y], [x + w, y + pad_y * 2.0 + lh], m.bg(theme::CARD), m.px(6.0));
    }
    widgets::outline(ui, [x, y], [x + w, y + total], theme::LINE, m.px(6.0));
    widgets::text_mid(ui, Font::Body12, x + pad_x, y + pad_y, lh, theme::SECONDARY, label);
    let icon = if open { Icon::Up } else { Icon::Down };
    widgets::icon(ui, m, [x + w - pad_x - m.px(6.0), y + pad_y + lh / 2.0], icon, theme::MUTED);
    let mut cy = y + pad_y + lh + m.px(2.0);
    for b in &lines {
        cy += b.draw(ui, [x + pad_x, cy], theme::TEXT) + gap;
    }
    if let Some(b) = &note {
        b.draw(ui, [x + pad_x, cy], theme::MAJOR.text);
    }
    total
}
