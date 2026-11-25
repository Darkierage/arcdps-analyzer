//! Everything the overlay draws, independent of Nexus: the same code runs in the game and in
//! the preview program (`cargo run --example preview`). It only reads the payload and reports
//! what the player clicked as [`Action`]s; `ui.rs` carries them out.

pub mod fight;
pub mod glance;
pub mod rules;
pub mod session;
pub mod states;
pub mod theme;
pub mod widgets;

use crate::client::{Snapshot, Status};
use crate::model::Overlay;
use imgui::{Condition, StyleColor, StyleVar, Ui, Window};
use std::collections::{HashMap, HashSet};
use theme::{Font, Metrics};
use widgets::{ButtonStyle, Icon};

/// What the player asked for this frame.
#[derive(Debug, Clone, PartialEq)]
pub enum Action {
    /// Show this fight, or the latest one.
    Select(Option<i64>),
    Record(bool),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Tab {
    #[default]
    Fight,
    Session,
}

/// What the player opened and picked, kept while the game runs (not saved).
#[derive(Debug, Default)]
pub struct ViewState {
    pub tab: Tab,
    /// Issue cards the player opened or closed, by fight id and title (else the default).
    toggled: HashMap<(i64, String), bool>,
    /// Fights whose LLM debrief row is open.
    debrief_open: HashSet<i64>,
}

impl ViewState {
    /// Opens or closes an issue card as a click would (the preview uses it).
    pub fn set_open(&mut self, fight: i64, title: &str, open: bool) {
        self.toggled.insert((fight, title.to_string()), open);
    }
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

/// Default and minimum size of the main window, at UI scale 1.
pub const DEFAULT_SIZE: [f32; 2] = [460.0, 600.0];
pub const MIN_SIZE: [f32; 2] = [360.0, 200.0];

/// The main window. `scale` is Nexus's UI scale; `opacity` the background setting.
pub fn main_window(
    ui: &Ui,
    state: &mut ViewState,
    snap: &Snapshot,
    scale: f32,
    opacity: f32,
) -> Frame {
    let m = Metrics::new(scale, opacity);
    let mut frame = Frame {
        latest: snap.data.as_ref().and_then(|d| d.latest.as_ref()).map(|l| l.id),
        open: true,
        ..Frame::default()
    };
    let _style = window_style(ui, &m);
    Window::new("WvW Analyzer###wvw_analyzer")
        .title_bar(false)
        .collapsible(false)
        .scroll_bar(false)
        .scrollable(false)
        .size([DEFAULT_SIZE[0] * m.scale, DEFAULT_SIZE[1] * m.scale], Condition::FirstUseEver)
        .size_constraints([MIN_SIZE[0] * m.scale, MIN_SIZE[1] * m.scale], [f32::MAX, f32::MAX])
        .bg_alpha(opacity)
        .build(ui, || {
            let _body = body_style(ui);
            draw(ui, &m, state, snap, &mut frame);
        });
    frame
}

/// Pushed style values, popped together when dropped.
#[must_use]
pub(crate) struct Pushed {
    vars: i32,
    colors: i32,
}

impl Pushed {
    pub(crate) fn new(ui: &Ui, vars: &[StyleVar], colors: &[(StyleColor, [f32; 4])]) -> Self {
        for v in vars {
            // The guard pops them all at once, so the per-call tokens are not kept.
            std::mem::forget(ui.push_style_var(*v));
        }
        for (c, rgba) in colors {
            std::mem::forget(ui.push_style_color(*c, *rgba));
        }
        Self { vars: vars.len() as i32, colors: colors.len() as i32 }
    }
}

impl Drop for Pushed {
    fn drop(&mut self) {
        // SAFETY: pops exactly what `new` pushed on the current context.
        unsafe {
            imgui::sys::igPopStyleColor(self.colors);
            imgui::sys::igPopStyleVar(self.vars);
        }
    }
}

/// Style for the window itself: no padding (the header band reaches the edges), rounded
/// corners and the theme's colors. Popped once the window has begun.
pub(crate) fn window_style(ui: &Ui, m: &Metrics) -> Pushed {
    Pushed::new(
        ui,
        &[
            StyleVar::WindowPadding([0.0, 0.0]),
            StyleVar::WindowRounding(m.px(6.0)),
            StyleVar::WindowBorderSize(1.0),
            StyleVar::WindowMinSize([MIN_SIZE[0] * m.scale, MIN_SIZE[1] * m.scale]),
            StyleVar::ScrollbarSize(m.px(8.0)),
            StyleVar::ScrollbarRounding(m.px(4.0)),
        ],
        &[
            (StyleColor::WindowBg, theme::WINDOW),
            (StyleColor::Border, theme::LINE),
            (StyleColor::ScrollbarBg, [0.0, 0.0, 0.0, 0.0]),
            (StyleColor::ScrollbarGrab, theme::LINE),
            (StyleColor::ScrollbarGrabHovered, theme::BUTTON_BORDER),
            (StyleColor::ScrollbarGrabActive, theme::BUTTON_BORDER),
            (StyleColor::ResizeGrip, [0.0, 0.0, 0.0, 0.0]),
            (StyleColor::ResizeGripHovered, theme::BUTTON_BORDER),
            (StyleColor::ResizeGripActive, theme::BUTTON_BORDER),
        ],
    )
}

/// Inside the window every position is set explicitly: no item spacing.
fn body_style(ui: &Ui) -> Pushed {
    Pushed::new(ui, &[StyleVar::ItemSpacing([0.0, 0.0]), StyleVar::WindowPadding([0.0, 0.0])], &[])
}

fn draw(ui: &Ui, m: &Metrics, state: &mut ViewState, snap: &Snapshot, frame: &mut Frame) {
    let data = match (&snap.status, &snap.data) {
        (Status::Connected, Some(d)) => Some(d),
        _ => None,
    };
    let top = header(ui, m, data, matches!(snap.status, Status::Searching), frame);
    match &snap.status {
        Status::Searching => {
            states::centered(
                ui,
                m,
                top,
                "WvW Analyzer isn't running",
                "Start the WvW Analyzer app on this PC. This window connects on its own within \
                 a few seconds.",
            );
            return;
        }
        Status::Problem(msg) => {
            states::centered(ui, m, top, "The debrief can't be shown", msg);
            return;
        }
        Status::Connected => {}
    }
    let Some(data) = data else { return };
    let mut y = tab_row(ui, m, state, data, top, frame);
    if let Some(err) = &snap.action_error {
        let pos = ui.window_pos();
        let w = ui.window_size()[0] - m.px(24.0);
        let b = widgets::Block::new(ui, Font::Body12, err, w);
        y += b.draw(ui, [pos[0] + m.px(12.0), y], theme::CRITICAL.text) + m.px(6.0);
    }
    match state.tab {
        Tab::Fight => match &data.fight {
            Some(f) => fight::tab(ui, m, state, f, y, frame),
            None => states::centered(
                ui,
                m,
                y,
                "No analyzed fights in this session yet",
                "The debrief appears here when the first fight has been analyzed.",
            ),
        },
        Tab::Session => match &data.session {
            Some(s) => session::tab(ui, m, s, y, frame, &mut state.tab),
            None => states::centered(
                ui,
                m,
                y,
                "No sessions yet",
                "Start recording in the app, or import logs there.",
            ),
        },
    }
}

/// The header band: name, queue, recording state with Start/Stop, Close. Returns its bottom.
fn header(ui: &Ui, m: &Metrics, data: Option<&Overlay>, searching: bool, frame: &mut Frame) -> f32 {
    let pos = ui.window_pos();
    let w = ui.window_size()[0];
    let h = m.px(38.0);
    let bottom = pos[1] + h;
    {
        let dl = ui.get_window_draw_list();
        dl.add_rect(pos, [pos[0] + w, bottom], m.bg(theme::HEADER))
            .filled(true)
            .rounding(m.px(6.0))
            .round_bot_left(false)
            .round_bot_right(false)
            .build();
    }
    widgets::hline(ui, pos[0], pos[0] + w, bottom - 1.0, theme::LINE);
    let name_w = widgets::text_mid(
        ui,
        Font::Body12,
        pos[0] + m.px(12.0),
        pos[1],
        h,
        theme::MUTED,
        "WvW Analyzer",
    );

    let side = m.px(22.0);
    let mid = |item_h: f32| pos[1] + ((h - item_h) / 2.0).floor();
    let mut x = pos[0] + w - m.px(10.0) - side;
    if widgets::icon_button(ui, m, "##close", [x, mid(side)], side, Icon::Close, false) {
        frame.open = false;
    }
    let (status, dot, color) = match data {
        Some(d) => {
            let label = if d.recording.active { "Stop" } else { "Start" };
            let size = widgets::button_size(ui, m, label, side);
            x -= m.px(10.0) + size[0];
            if widgets::button(ui, m, "##record", [x, mid(side)], label, side, ButtonStyle::Raised)
            {
                frame.actions.push(Action::Record(!d.recording.active));
            }
            if d.recording.active {
                ("Recording", theme::GREEN_DOT, theme::POSITIVE.text)
            } else {
                ("Not recording", theme::DOT_OFF, theme::MUTED)
            }
        }
        None if searching => ("Not connected", theme::DOT_OFF, theme::MUTED),
        None => ("", theme::DOT_OFF, theme::MUTED),
    };
    if !status.is_empty() {
        let tw = widgets::text_size(ui, Font::Body12, status)[0];
        x -= m.px(10.0) + tw;
        widgets::text_mid(ui, Font::Body12, x, pos[1], h, color, status);
        x -= m.px(6.0) + m.px(8.0);
        widgets::dot(ui, m, [x + m.px(4.0), pos[1] + h / 2.0], dot);
    }
    if let Some(d) = data
        && (d.queue.busy || d.queue.pending > 0)
    {
        let queued = if d.queue.pending > 0 {
            format!("Analyzing ({} queued)", d.queue.pending)
        } else {
            "Analyzing…".to_string()
        };
        let tw = widgets::text_size(ui, Font::Body12, &queued)[0];
        // Dropped when the window is too narrow for it.
        if x - m.px(10.0) - tw > pos[0] + m.px(12.0) + name_w + m.px(10.0) {
            widgets::text_mid(
                ui,
                Font::Body12,
                x - m.px(10.0) - tw,
                pos[1],
                h,
                theme::MUTED,
                &queued,
            );
        }
    }
    bottom
}

/// The tab switch and, on the right, the fight navigation or the session's meta line.
/// Returns where the content below starts.
fn tab_row(
    ui: &Ui,
    m: &Metrics,
    state: &mut ViewState,
    data: &Overlay,
    top: f32,
    frame: &mut Frame,
) -> f32 {
    let pos = ui.window_pos();
    let w = ui.window_size()[0];
    let y = top + m.px(8.0);
    let row_h = m.px(28.0);
    let x0 = pos[0] + m.px(12.0);
    // The switch: a card-colored pill with the active tab raised.
    let pad = m.px(2.0);
    let tab_h = row_h - pad * 2.0;
    let labels = [("Fight", Tab::Fight), ("Session", Tab::Session)];
    let widths: Vec<f32> = labels
        .iter()
        .map(|(l, _)| widgets::text_size(ui, Font::Body12, l)[0] + m.px(14.0) * 2.0)
        .collect();
    let pill_w = widths.iter().sum::<f32>() + pad * 3.0;
    widgets::rect(ui, [x0, y], [x0 + pill_w, y + row_h], m.bg(theme::CARD), m.px(6.0));
    let mut x = x0 + pad;
    for ((label, tab), tw) in labels.iter().zip(&widths) {
        let active = state.tab == *tab;
        let (clicked, hovered) =
            widgets::hit(ui, &format!("##tab{label}"), [x, y + pad], [*tw, tab_h]);
        if clicked {
            state.tab = *tab;
        }
        if active || hovered {
            let fill = if active { theme::TAB_ACTIVE } else { theme::CARD_HOVER };
            widgets::rect(ui, [x, y + pad], [x + tw, y + pad + tab_h], m.bg(fill), m.px(4.0));
        }
        let color = if active { theme::TEXT_STRONG } else { theme::MUTED };
        let lw = widgets::text_size(ui, Font::Body12, label)[0];
        widgets::text_mid(ui, Font::Body12, x + (tw - lw) / 2.0, y + pad, tab_h, color, label);
        x += tw + pad;
    }
    let right = pos[0] + w - m.px(12.0);
    match state.tab {
        Tab::Fight => {
            if let Some(f) = &data.fight {
                fight::navigation(ui, m, f, frame.latest, right, y, row_h, &mut frame.actions);
            }
        }
        Tab::Session => {
            if let Some(s) = &data.session {
                session::meta(ui, s, x0 + pill_w + m.px(12.0), right, y, row_h);
            }
        }
    }
    y + row_h + m.px(8.0)
}
