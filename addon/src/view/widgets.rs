//! Drawing blocks: text that wraps, chips, buttons, icons, stat tiles, bars. Everything is
//! measured before it is drawn, so backgrounds go under their content without draw channels.
//! Positions are screen coordinates; clickable areas are ImGui invisible buttons.

use super::theme::{self, Font, Metrics};
use crate::model::Fact;
use imgui::{Ui, sys};

/// The current font's size in pixels.
pub fn font_size() -> f32 {
    // SAFETY: plain getter on the current context; only called while drawing a frame.
    unsafe { sys::igGetFontSize() }
}

/// Line height for wrapped text (the mockups' 1.4 line height).
pub fn line_height(ui: &Ui, font: Font) -> f32 {
    let _f = theme::font(ui, font);
    (font_size() * 1.4).round()
}

/// One line of text; returns its size.
pub fn text_size(ui: &Ui, font: Font, text: &str) -> [f32; 2] {
    let _f = theme::font(ui, font);
    ui.calc_text_size(text)
}

/// Splits `text` into lines no wider than `width` (at word breaks; a single word too long is
/// cut). Respects line breaks in the text.
pub fn wrap(ui: &Ui, font: Font, text: &str, width: f32) -> Vec<String> {
    let _f = theme::font(ui, font);
    let mut out = Vec::new();
    for para in text.split('\n') {
        let mut line = String::new();
        for word in para.split(' ').filter(|w| !w.is_empty()) {
            let candidate =
                if line.is_empty() { word.to_string() } else { format!("{line} {word}") };
            if ui.calc_text_size(&candidate)[0] <= width {
                line = candidate;
                continue;
            }
            if !line.is_empty() {
                out.push(std::mem::take(&mut line));
            }
            // A word wider than the line: cut it into pieces that fit.
            let mut rest = word;
            while ui.calc_text_size(rest)[0] > width && rest.chars().count() > 1 {
                let mut cut = rest.len();
                while cut > 0 && ui.calc_text_size(&rest[..cut])[0] > width {
                    cut = rest[..cut].char_indices().last().map_or(0, |(i, _)| i);
                }
                if cut == 0 {
                    cut = rest.chars().next().map_or(rest.len(), char::len_utf8);
                }
                out.push(rest[..cut].to_string());
                rest = &rest[cut..];
            }
            line = rest.to_string();
        }
        out.push(line);
    }
    out
}

/// Wrapped text, measured before drawing.
pub struct Block {
    pub lines: Vec<String>,
    pub font: Font,
    pub line_h: f32,
}

impl Block {
    pub fn new(ui: &Ui, font: Font, text: &str, width: f32) -> Self {
        Self { lines: wrap(ui, font, text, width), font, line_h: line_height(ui, font) }
    }

    pub fn height(&self) -> f32 {
        self.lines.len() as f32 * self.line_h
    }

    pub fn width(&self, ui: &Ui) -> f32 {
        let _f = theme::font(ui, self.font);
        self.lines.iter().map(|l| ui.calc_text_size(l)[0]).fold(0.0, f32::max)
    }

    /// Draws the lines from `pos` (top left); returns the height.
    pub fn draw(&self, ui: &Ui, pos: [f32; 2], color: [f32; 4]) -> f32 {
        let _f = theme::font(ui, self.font);
        let offset = ((self.line_h - font_size()) / 2.0).floor();
        let dl = ui.get_window_draw_list();
        for (i, line) in self.lines.iter().enumerate() {
            dl.add_text([pos[0], pos[1] + offset + i as f32 * self.line_h], color, line);
        }
        self.height()
    }

    /// Draws each line centered on `center_x`.
    pub fn draw_centered(&self, ui: &Ui, center_x: f32, top: f32, color: [f32; 4]) -> f32 {
        let _f = theme::font(ui, self.font);
        let offset = ((self.line_h - font_size()) / 2.0).floor();
        let dl = ui.get_window_draw_list();
        for (i, line) in self.lines.iter().enumerate() {
            let w = ui.calc_text_size(line)[0];
            dl.add_text(
                [(center_x - w / 2.0).round(), top + offset + i as f32 * self.line_h],
                color,
                line,
            );
        }
        self.height()
    }
}

/// One line of text with its top left at `pos`.
pub fn text(ui: &Ui, font: Font, pos: [f32; 2], color: [f32; 4], s: &str) {
    let _f = theme::font(ui, font);
    ui.get_window_draw_list().add_text([pos[0].round(), pos[1].round()], color, s);
}

/// One line of text vertically centered in a row from `top` of height `h`.
pub fn text_mid(ui: &Ui, font: Font, x: f32, top: f32, h: f32, color: [f32; 4], s: &str) -> f32 {
    let size = text_size(ui, font, s);
    text(ui, font, [x, top + ((h - size[1]) / 2.0).floor()], color, s);
    size[0]
}

pub fn rect(ui: &Ui, min: [f32; 2], max: [f32; 2], color: [f32; 4], rounding: f32) {
    ui.get_window_draw_list().add_rect(min, max, color).filled(true).rounding(rounding).build();
}

pub fn outline(ui: &Ui, min: [f32; 2], max: [f32; 2], color: [f32; 4], rounding: f32) {
    // Half a pixel in, so the 1 px line lands on whole pixels.
    ui.get_window_draw_list()
        .add_rect([min[0] + 0.5, min[1] + 0.5], [max[0] - 0.5, max[1] - 0.5], color)
        .rounding(rounding)
        .thickness(1.0)
        .build();
}

pub fn hline(ui: &Ui, x0: f32, x1: f32, y: f32, color: [f32; 4]) {
    rect(ui, [x0, y], [x1, y + 1.0], color, 0.0);
}

pub fn dot(ui: &Ui, m: &Metrics, center: [f32; 2], color: [f32; 4]) {
    ui.get_window_draw_list().add_circle(center, m.px(4.0), color).filled(true).build();
}

/// Size of a chip: the word in SemiBold 11 with 7 by 1 padding (a badge: 8 by 2).
pub fn chip_size(ui: &Ui, m: &Metrics, word: &str, badge: bool) -> [f32; 2] {
    let t = text_size(ui, Font::Label11, word);
    let (px, py) = if badge { (8.0, 3.0) } else { (7.0, 2.0) };
    [t[0] + m.px(px) * 2.0, t[1] + m.px(py) * 2.0]
}

/// A severity chip or result badge with its top left at `pos`; returns its size.
pub fn chip(
    ui: &Ui,
    m: &Metrics,
    pos: [f32; 2],
    word: &str,
    tone: theme::Tone,
    badge: bool,
) -> [f32; 2] {
    let size = chip_size(ui, m, word, badge);
    rect(ui, pos, [pos[0] + size[0], pos[1] + size[1]], tone.fill, m.px(4.0));
    let t = text_size(ui, Font::Label11, word);
    text(
        ui,
        Font::Label11,
        [pos[0] + (size[0] - t[0]) / 2.0, pos[1] + (size[1] - t[1]) / 2.0],
        tone.text,
        word,
    );
    size
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Icon {
    Close,
    Left,
    Right,
    Down,
    Up,
}

/// A 12 by 12 stroke icon (the mockups' paths) centered on `center`.
pub fn icon(ui: &Ui, m: &Metrics, center: [f32; 2], kind: Icon, color: [f32; 4]) {
    let pts: &[[f32; 2]] = match kind {
        Icon::Close => &[[2.0, 2.0], [10.0, 10.0], [10.0, 2.0], [2.0, 10.0]],
        Icon::Left => &[[7.5, 2.5], [4.0, 6.0], [7.5, 9.5]],
        Icon::Right => &[[4.5, 2.5], [8.0, 6.0], [4.5, 9.5]],
        Icon::Down => &[[2.5, 4.5], [6.0, 8.0], [9.5, 4.5]],
        Icon::Up => &[[2.5, 7.5], [6.0, 4.0], [9.5, 7.5]],
    };
    let s = m.scale;
    let at = |p: [f32; 2]| [center[0] + (p[0] - 6.0) * s, center[1] + (p[1] - 6.0) * s];
    let dl = ui.get_window_draw_list();
    let thick = 1.5 * s;
    if kind == Icon::Close {
        dl.add_line(at(pts[0]), at(pts[1]), color).thickness(thick).build();
        dl.add_line(at(pts[2]), at(pts[3]), color).thickness(thick).build();
    } else {
        dl.add_line(at(pts[0]), at(pts[1]), color).thickness(thick).build();
        dl.add_line(at(pts[1]), at(pts[2]), color).thickness(thick).build();
    }
}

/// A clickable area; returns (clicked, hovered).
pub fn hit(ui: &Ui, id: &str, pos: [f32; 2], size: [f32; 2]) -> (bool, bool) {
    ui.set_cursor_screen_pos(pos);
    let clicked = ui.invisible_button(id, [size[0].max(1.0), size[1].max(1.0)]);
    (clicked, ui.is_item_hovered())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ButtonStyle {
    /// Border, transparent ("Latest").
    Outline,
    /// Border on a raised fill ("Stop", "Start").
    Raised,
    /// The main action ("Open debrief").
    Primary,
}

pub fn button_size(ui: &Ui, m: &Metrics, label: &str, h: f32) -> [f32; 2] {
    let pad = if label.len() > 5 { 12.0 } else { 10.0 };
    [text_size(ui, Font::Body12, label)[0] + m.px(pad) * 2.0, h]
}

/// A text button with its top left at `pos`; returns whether it was clicked.
pub fn button(
    ui: &Ui,
    m: &Metrics,
    id: &str,
    pos: [f32; 2],
    label: &str,
    h: f32,
    style: ButtonStyle,
) -> bool {
    let size = button_size(ui, m, label, h);
    let (clicked, hovered) = hit(ui, id, pos, size);
    let max = [pos[0] + size[0], pos[1] + size[1]];
    let r = m.px(4.0);
    let (fill, border, color) = match style {
        ButtonStyle::Outline => (None, Some(theme::BUTTON_BORDER), theme::SECONDARY),
        ButtonStyle::Raised => (Some(theme::CARD_HOVER), Some(theme::BUTTON_BORDER), theme::TEXT),
        ButtonStyle::Primary => (Some(theme::TAB_ACTIVE), None, theme::TEXT_STRONG),
    };
    let fill = match (fill, hovered) {
        (Some(_), true) | (None, true) => Some(theme::BUTTON_BORDER),
        (f, false) => f,
    };
    if let Some(f) = fill {
        rect(ui, pos, max, m.bg(f), r);
    }
    if let Some(b) = border {
        outline(ui, pos, max, b, r);
    }
    let font = if style == ButtonStyle::Primary { Font::Title13 } else { Font::Body12 };
    let t = text_size(ui, font, label);
    text(
        ui,
        font,
        [pos[0] + (size[0] - t[0]) / 2.0, pos[1] + (size[1] - t[1]) / 2.0],
        color,
        label,
    );
    clicked
}

/// A square icon button; `fill` draws the card color behind it (the fight arrows).
pub fn icon_button(
    ui: &Ui,
    m: &Metrics,
    id: &str,
    pos: [f32; 2],
    side: f32,
    kind: Icon,
    fill: bool,
) -> bool {
    let (clicked, hovered) = hit(ui, id, pos, [side, side]);
    let max = [pos[0] + side, pos[1] + side];
    if hovered {
        rect(ui, pos, max, m.bg(theme::TAB_ACTIVE), m.px(4.0));
    } else if fill {
        rect(ui, pos, max, m.bg(theme::CARD), m.px(4.0));
    }
    let color = if fill || hovered { theme::TEXT } else { theme::MUTED };
    icon(ui, m, [pos[0] + side / 2.0, pos[1] + side / 2.0], kind, color);
    clicked
}

/// A section label in upper case ("WHAT TO IMPROVE 4"); returns its height.
pub fn section_label(
    ui: &Ui,
    m: &Metrics,
    pos: [f32; 2],
    label: &str,
    count: Option<usize>,
) -> f32 {
    let upper = label.to_uppercase();
    let size = text_size(ui, Font::Label11, &upper);
    text(ui, Font::Label11, pos, theme::MUTED, &upper);
    if let Some(n) = count {
        text(
            ui,
            Font::Label11,
            [pos[0] + size[0] + m.px(6.0), pos[1]],
            theme::MUTED,
            &n.to_string(),
        );
    }
    line_height(ui, Font::Label11)
}

/// Stat tiles in one row from `pos`, `width` wide; returns the row's height.
///
/// A tile's note goes on its label line ("Squad · +2 allies"). A value too wide for its tile
/// drops to the heading size, and only then is clipped.
pub fn stat_tiles(ui: &Ui, m: &Metrics, pos: [f32; 2], width: f32, facts: &[Fact]) -> f32 {
    if facts.is_empty() {
        return 0.0;
    }
    let gap = m.px(6.0);
    let n = facts.len() as f32;
    let tile_w = ((width - gap * (n - 1.0)) / n).floor();
    let (pad_x, pad_y) = (m.px(10.0), m.px(6.0));
    let inner = (tile_w - pad_x * 2.0).max(1.0);
    let value_h = line_height(ui, Font::Value18);
    let labels: Vec<Block> = facts
        .iter()
        .map(|f| {
            let label = if f.note.is_empty() {
                f.label.clone()
            } else {
                format!("{} · {}", f.label, f.note)
            };
            Block::new(ui, Font::Body12, &label, inner)
        })
        .collect();
    let label_h = labels.iter().map(|b| b.lines.len()).max().unwrap_or(1) as f32
        * line_height(ui, Font::Body12);
    let tile_h = pad_y * 2.0 + value_h + label_h;
    for (i, (f, label)) in facts.iter().zip(&labels).enumerate() {
        let x = pos[0] + i as f32 * (tile_w + gap);
        let max = [x + tile_w, pos[1] + tile_h];
        rect(ui, [x, pos[1]], max, m.bg(theme::CARD), m.px(6.0));
        let font = if text_size(ui, Font::Value18, &f.value)[0] <= inner {
            Font::Value18
        } else {
            Font::Heading15
        };
        let color = theme::fact_color(&f.tone);
        let vy = pos[1] + pad_y + ((value_h - text_size(ui, font, &f.value)[1]) / 2.0).floor();
        {
            // One draw list at a time: imgui-rs panics on a second one.
            let _f = theme::font(ui, font);
            let dl = ui.get_window_draw_list();
            dl.with_clip_rect_intersect([x, pos[1]], [max[0] - pad_x / 2.0, max[1]], || {
                dl.add_text([(x + pad_x).round(), vy.round()], color, &f.value);
            });
        }
        label.draw(ui, [x + pad_x, pos[1] + pad_y + value_h], theme::MUTED);
    }
    tile_h
}

/// A thin bar for a share, 0..1.
pub fn bar(ui: &Ui, m: &Metrics, pos: [f32; 2], width: f32, share: f32, color: [f32; 4]) -> f32 {
    let h = m.px(4.0);
    rect(ui, pos, [pos[0] + width, pos[1] + h], theme::LINE, h / 2.0);
    let w = (width * share.clamp(0.0, 1.0)).round();
    if w > 0.0 {
        rect(ui, pos, [pos[0] + w.max(h), pos[1] + h], color, h / 2.0);
    }
    h
}
