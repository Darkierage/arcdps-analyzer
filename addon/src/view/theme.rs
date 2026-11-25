//! Colors, type and metrics of the overlay (plan 14, "Look").

use imgui::{Ui, sys};
use std::sync::atomic::{AtomicUsize, Ordering};

/// Inter (SIL Open Font License, `assets/fonts/OFL.txt`), subset to Latin and Latin Extended.
pub const INTER_REGULAR: &[u8] = include_bytes!("../../assets/fonts/Inter-Regular.ttf");
pub const INTER_SEMIBOLD: &[u8] = include_bytes!("../../assets/fonts/Inter-SemiBold.ttf");

/// Glyphs loaded from Inter: Basic Latin, Latin-1, Latin Extended-A/B, general punctuation
/// (dashes, quotes, the ellipsis) and the euro sign. Zero-terminated, as ImGui wants it.
pub static GLYPH_RANGES: [u16; 11] =
    [0x0020, 0x007E, 0x00A0, 0x024F, 0x2010, 0x2027, 0x2030, 0x203A, 0x20AC, 0x20AC, 0];

/// A copy of `data` on the process heap that is never freed. What Nexus keeps a pointer to
/// (font bytes, glyph ranges, the font config) must outlive this DLL: Nexus may hold a font
/// after the addon is unloaded or reloaded, and the DLL's static data goes with it.
pub fn leak_copy<T: Copy>(data: &[T]) -> &'static [T] {
    Box::leak(data.to_vec().into_boxed_slice())
}

const fn hex(rgb: u32) -> [f32; 4] {
    [
        ((rgb >> 16) & 0xff) as f32 / 255.0,
        ((rgb >> 8) & 0xff) as f32 / 255.0,
        (rgb & 0xff) as f32 / 255.0,
        1.0,
    ]
}

const fn alpha(c: [f32; 4], a: f32) -> [f32; 4] {
    [c[0], c[1], c[2], a]
}

pub const WINDOW: [f32; 4] = hex(0x15171c);
pub const HEADER: [f32; 4] = hex(0x1b1e25);
pub const CARD: [f32; 4] = hex(0x1e222a);
pub const CARD_HOVER: [f32; 4] = hex(0x232832);
pub const LINE: [f32; 4] = hex(0x2a2f3a);
/// The divider inside a hovered or clicked-open card.
pub const LINE_HOVER: [f32; 4] = hex(0x343b48);
pub const TAB_ACTIVE: [f32; 4] = hex(0x303744);
pub const BUTTON_BORDER: [f32; 4] = hex(0x3a4150);
pub const TEXT: [f32; 4] = hex(0xe6e8ec);
pub const TEXT_STRONG: [f32; 4] = hex(0xffffff);
pub const SECONDARY: [f32; 4] = hex(0xc9ced8);
pub const MUTED: [f32; 4] = hex(0x9aa3b2);
pub const DOT_OFF: [f32; 4] = hex(0x6b7382);

/// A severity's or result's text color and chip fill.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Tone {
    pub text: [f32; 4],
    pub fill: [f32; 4],
}

pub const CRITICAL: Tone = Tone { text: hex(0xff8080), fill: alpha(hex(0xff6b6b), 0.16) };
pub const MAJOR: Tone = Tone { text: hex(0xffb066), fill: alpha(hex(0xffa348), 0.16) };
pub const MINOR: Tone = Tone { text: hex(0xe8d470), fill: alpha(hex(0xe8d15a), 0.14) };
pub const CONTEXT: Tone = Tone { text: hex(0x9aa3b2), fill: alpha(hex(0x9aa3b2), 0.14) };
pub const POSITIVE: Tone = Tone { text: hex(0x6fdc8c), fill: alpha(hex(0x5fd47a), 0.16) };
/// The solid green of the "went well" and "recording" dots.
pub const GREEN_DOT: [f32; 4] = hex(0x5fd47a);

pub fn severity_tone(severity: &str) -> Tone {
    match severity {
        "critical" => CRITICAL,
        "major" => MAJOR,
        "minor" => MINOR,
        "positive" => POSITIVE,
        _ => CONTEXT,
    }
}

/// The word on a severity chip; severity is never shown by color alone.
pub fn severity_word(severity: &str) -> &'static str {
    match severity {
        "critical" => "CRITICAL",
        "major" => "MAJOR",
        "minor" => "MINOR",
        "positive" => "WENT WELL",
        _ => "CONTEXT",
    }
}

pub fn result_tone(result: Option<&str>) -> Tone {
    match result {
        Some("win") => POSITIVE,
        Some("loss") => CRITICAL,
        Some("even") => MINOR,
        _ => CONTEXT,
    }
}

/// A stat tile's value color.
pub fn fact_color(tone: &str) -> [f32; 4] {
    match tone {
        "good" => POSITIVE.text,
        "bad" => CRITICAL.text,
        _ => TEXT,
    }
}

/// The overlay's type scale: Inter Regular 12 and 13, SemiBold 11, 13, 15 and 18.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Font {
    Body12,
    Body13,
    /// Chips, badges and section labels (upper case).
    Label11,
    /// Card titles and the small panel's headline.
    Title13,
    /// The fight's heading and the empty-state titles.
    Heading15,
    /// Stat values.
    Value18,
}

impl Font {
    pub const ALL: [Font; 6] =
        [Font::Body12, Font::Body13, Font::Label11, Font::Title13, Font::Heading15, Font::Value18];

    pub fn size(self) -> f32 {
        match self {
            Font::Label11 => 11.0,
            Font::Body12 => 12.0,
            Font::Body13 | Font::Title13 => 13.0,
            Font::Heading15 => 15.0,
            Font::Value18 => 18.0,
        }
    }

    pub fn semibold(self) -> bool {
        !matches!(self, Font::Body12 | Font::Body13)
    }

    pub fn data(self) -> &'static [u8] {
        if self.semibold() { INTER_SEMIBOLD } else { INTER_REGULAR }
    }

    /// The name Nexus keeps the font under.
    pub fn id(self) -> &'static str {
        match self {
            Font::Body12 => "WVW_ANALYZER_INTER_R12",
            Font::Body13 => "WVW_ANALYZER_INTER_R13",
            Font::Label11 => "WVW_ANALYZER_INTER_SB11",
            Font::Title13 => "WVW_ANALYZER_INTER_SB13",
            Font::Heading15 => "WVW_ANALYZER_INTER_SB15",
            Font::Value18 => "WVW_ANALYZER_INTER_SB18",
        }
    }

    pub fn from_id(id: &str) -> Option<Font> {
        Font::ALL.into_iter().find(|f| f.id() == id)
    }

    fn index(self) -> usize {
        Font::ALL.iter().position(|f| *f == self).unwrap_or(0)
    }
}

/// The loaded fonts, as raw `ImFont` pointers (0 = not handed over yet). Atomics, because Nexus
/// may hand a font over from inside a call that already holds the addon's lock.
static FONTS: [AtomicUsize; 6] = [const { AtomicUsize::new(0) }; 6];

/// Stores a font Nexus (or the preview) handed over; None forgets it.
pub fn set_font(font: Font, ptr: Option<*mut sys::ImFont>) {
    FONTS[font.index()].store(ptr.map_or(0, |p| p as usize), Ordering::Release);
}

/// Pushes `font` until the token is dropped. Without it (not handed over yet) the current font
/// stays: the window still works, only less polished.
pub fn font(_ui: &Ui, font: Font) -> FontToken {
    let ptr = FONTS[font.index()].load(Ordering::Acquire);
    if ptr == 0 {
        return FontToken(false);
    }
    // SAFETY: the pointer came from the ImGui context we draw in (Nexus's, or the preview's
    // atlas), and the font is replaced or cleared through `set_font` before it goes away.
    unsafe { sys::igPushFont(ptr as *mut sys::ImFont) };
    FontToken(true)
}

#[must_use]
pub struct FontToken(bool);

impl Drop for FontToken {
    fn drop(&mut self) {
        if self.0 {
            // SAFETY: pairs with the push in `font`.
            unsafe { sys::igPopFont() };
        }
    }
}

/// Sizes at the current UI scale.
#[derive(Debug, Clone, Copy)]
pub struct Metrics {
    pub scale: f32,
    /// Background alpha (the opacity setting) for the window, header, cards and tiles.
    pub bg_alpha: f32,
}

impl Metrics {
    pub fn new(scale: f32, bg_alpha: f32) -> Self {
        let scale = if scale.is_finite() && scale > 0.2 { scale } else { 1.0 };
        Self { scale, bg_alpha: bg_alpha.clamp(0.0, 1.0) }
    }

    /// A length in mockup pixels at the current scale.
    pub fn px(&self, v: f32) -> f32 {
        (v * self.scale).round()
    }

    /// A background color at the opacity setting.
    pub fn bg(&self, c: [f32; 4]) -> [f32; 4] {
        [c[0], c[1], c[2], c[3] * self.bg_alpha]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn heap_copies_hold_the_same_bytes_outside_the_dll_statics() {
        let copy = leak_copy(INTER_REGULAR);
        assert_eq!(copy, INTER_REGULAR);
        assert_ne!(copy.as_ptr(), INTER_REGULAR.as_ptr());
        let ranges = leak_copy(&GLYPH_RANGES);
        assert_eq!(ranges.last(), Some(&0)); // still zero-terminated for ImGui
        assert_ne!(ranges.as_ptr(), GLYPH_RANGES.as_ptr());
    }
}
