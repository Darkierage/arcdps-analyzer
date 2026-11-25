//! The small panel after a fight: the result and the top problems, between fights, without the
//! full window. Its show and hide rules are in [`GlanceRules`].

use super::theme::{self, Font, Metrics};
use super::widgets::{self, Block, ButtonStyle, Icon};
use super::{Pushed, window_style};
use crate::model::Fight;
use imgui::{Condition, StyleVar, Ui, Window};

/// When the small panel shows (plan 14, "Small panel after a fight").
#[derive(Debug, Default, Clone, PartialEq)]
pub struct GlanceRules {
    /// A new fight waits to be shown (out of combat, once the payload has it).
    armed: bool,
    visible: bool,
}

impl GlanceRules {
    /// A new fight was analyzed. With the full window open, that window just moves to it.
    /// A newer fight replaces what the panel shows, once the payload has caught up.
    pub fn new_fight(&mut self, window_open: bool) {
        self.visible = false;
        self.armed = !window_open;
    }

    /// Once per frame; returns whether the panel shows. `payload_ready`: the payload's fight is
    /// the newest one (so the panel never flashes the fight before).
    pub fn update(&mut self, in_combat: bool, window_open: bool, payload_ready: bool) -> bool {
        if window_open {
            self.armed = false;
            self.visible = false;
        } else if in_combat {
            // Hidden for this fight: it doesn't come back after combat. One still waiting
            // (`armed`) shows once combat ends.
            self.visible = false;
        } else if self.armed && payload_ready {
            self.armed = false;
            self.visible = true;
        }
        self.visible
    }

    /// Dismiss or Open debrief.
    pub fn hide(&mut self) {
        self.armed = false;
        self.visible = false;
    }

    pub fn visible(&self) -> bool {
        self.visible
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GlanceAction {
    Dismiss,
    OpenDebrief,
}

pub const WIDTH: f32 = 360.0;
/// Issue titles shown in the panel.
const SHOWN: usize = 3;

/// The panel: no title bar, sized to its content, movable, never takes keyboard focus.
pub fn panel(ui: &Ui, f: &Fight, scale: f32, opacity: f32) -> Option<GlanceAction> {
    let m = Metrics::new(scale, opacity);
    let mut action = None;
    let display = ui.io().display_size;
    let _style = window_style(ui, &m);
    let _body = Pushed::new(ui, &[StyleVar::ItemSpacing([0.0, 0.0])], &[]);
    Window::new("WvW Analyzer, after a fight###wvw_analyzer_glance")
        .title_bar(false)
        .collapsible(false)
        .resizable(false)
        .scroll_bar(false)
        .scrollable(false)
        .always_auto_resize(true)
        .focus_on_appearing(false)
        .no_nav()
        .position(
            [(display[0] / 2.0 - WIDTH * m.scale / 2.0).round(), (display[1] * 0.18).round()],
            Condition::FirstUseEver,
        )
        .bg_alpha(opacity)
        .build(ui, || action = draw(ui, &m, f));
    action
}

fn draw(ui: &Ui, m: &Metrics, f: &Fight) -> Option<GlanceAction> {
    let mut action = None;
    let pos = ui.window_pos();
    let w = WIDTH * m.scale;
    let pad = m.px(12.0);
    let (x, inner) = (pos[0] + pad, w - pad * 2.0);
    let mut y = pos[1] + pad;

    // Badge, headline, numbers, dismiss.
    let side = m.px(22.0);
    let row_h = side;
    let mut hx = x;
    if f.has_header() {
        let tone = theme::result_tone(f.result.as_deref());
        let badge = widgets::chip_size(ui, m, &f.badge, true);
        widgets::chip(ui, m, [x, y + ((row_h - badge[1]) / 2.0).floor()], &f.badge, tone, true);
        hx += badge[0] + m.px(8.0);
    }
    let close_x = x + inner - side;
    if widgets::icon_button(ui, m, "##dismiss", [close_x, y], side, Icon::Close, false) {
        action = Some(GlanceAction::Dismiss);
    }
    let headline = if f.has_header() {
        f.headline.clone()
    } else {
        f.result_line.lines().next().unwrap_or_default().to_string()
    };
    let numbers_w = widgets::text_size(ui, Font::Body12, &f.numbers)[0];
    let numbers_x = close_x - m.px(8.0) - numbers_w;
    if !f.numbers.is_empty() {
        widgets::text_mid(ui, Font::Body12, numbers_x, y, row_h, theme::MUTED, &f.numbers);
    }
    {
        let _font = theme::font(ui, Font::Title13);
        let dl = ui.get_window_draw_list();
        let ty = y + ((row_h - widgets::font_size()) / 2.0).floor();
        let right = if f.numbers.is_empty() { close_x } else { numbers_x } - m.px(8.0);
        dl.with_clip_rect_intersect([hx, y], [right, y + row_h], || {
            dl.add_text([hx, ty], theme::TEXT, &headline);
        });
    }
    y += row_h + m.px(10.0);

    // The first issues with their severity word.
    let word_w = m.px(62.0);
    let gap = m.px(6.0);
    if f.issues.is_empty() {
        y += Block::new(ui, Font::Body13, "No problems found.", inner).draw(
            ui,
            [x, y],
            theme::MUTED,
        ) + gap;
    }
    for n in f.issues.iter().take(SHOWN) {
        let tone = theme::severity_tone(&n.severity);
        let title = Block::new(ui, Font::Body13, &n.title, inner - word_w - m.px(8.0));
        widgets::text_mid(
            ui,
            Font::Label11,
            x,
            y,
            title.line_h,
            tone.text,
            theme::severity_word(&n.severity),
        );
        y += title.draw(ui, [x + word_w + m.px(8.0), y], theme::TEXT) + gap;
    }
    y += m.px(4.0);

    // "N more", Open debrief.
    widgets::hline(ui, x, x + inner, y, theme::LINE);
    y += 1.0 + m.px(8.0);
    let more = f.issues.len().saturating_sub(SHOWN) + f.more_count as usize;
    let note = if more > 0 {
        format!("{more} more · hides when combat starts")
    } else {
        "Hides when combat starts".to_string()
    };
    let btn_h = m.px(24.0);
    let btn = widgets::button_size(ui, m, "Open debrief", btn_h);
    widgets::text_mid(ui, Font::Body12, x, y, btn_h, theme::MUTED, &note);
    if widgets::button(
        ui,
        m,
        "##open",
        [x + inner - btn[0], y],
        "Open debrief",
        btn_h,
        ButtonStyle::Primary,
    ) {
        action = Some(GlanceAction::OpenDebrief);
    }
    y += btn_h + pad;

    // The window sizes itself to this.
    ui.set_cursor_screen_pos(pos);
    ui.dummy([w, y - pos[1]]);
    action
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shows_out_of_combat_once_the_payload_has_the_fight() {
        let mut g = GlanceRules::default();
        assert!(!g.update(false, false, true)); // nothing new yet
        g.new_fight(false);
        assert!(!g.update(true, false, true)); // in combat: waits
        assert!(!g.update(false, false, false)); // payload still on the fight before
        assert!(g.update(false, false, true));
        assert!(g.update(false, false, true)); // stays
    }

    #[test]
    fn combat_hides_it_for_good_until_a_newer_fight() {
        let mut g = GlanceRules::default();
        g.new_fight(false);
        assert!(g.update(false, false, true));
        assert!(!g.update(true, false, true));
        assert!(!g.update(false, false, true)); // doesn't come back after combat
        g.new_fight(false);
        assert!(!g.update(false, false, false)); // newer fight: waits for its payload
        assert!(g.update(false, false, true));
    }

    #[test]
    fn the_full_window_wins() {
        let mut g = GlanceRules::default();
        g.new_fight(true); // window open: it just moves to the new fight
        assert!(!g.update(false, false, true));
        g.new_fight(false);
        assert!(g.update(false, false, true));
        assert!(!g.update(false, true, true)); // the window opened: the panel goes
        assert!(!g.update(false, false, true));
    }

    #[test]
    fn dismiss_and_open_hide_it() {
        let mut g = GlanceRules::default();
        g.new_fight(false);
        assert!(g.update(false, false, true));
        g.hide();
        assert!(!g.update(false, false, true) && !g.visible());
    }
}
