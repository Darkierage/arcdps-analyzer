//! Nexus entry points: load/unload, render callbacks, Quick Access icon and keybind.

use crate::client::{Client, PORTS};
use crate::ui::App;
use crate::view::theme::{self, Font, GLYPH_RANGES};
use nexus::{
    AddonFlags, UpdateProvider,
    data_link::mumble::{UiState, get_mumble_link},
    data_link::read_nexus_link,
    font::{add_font_from_memory, font_receive, resize_font},
    gui::{RenderType, register_render, render},
    imgui::{Ui, sys},
    keybind::{keybind_handler, register_keybind_with_string},
    paths::get_addon_dir,
    quick_access::add_quick_access,
    texture::load_texture_from_memory,
};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};

nexus::export! {
    name: "WvW Analyzer",
    signature: -0x5741_4E31, // not on the Raidcore library: a fixed negative id
    load,
    unload,
    flags: AddonFlags::None,
    provider: UpdateProvider::None, // the WvW Analyzer app installs and updates the addon
}

const KEYBIND: &str = "KB_WVW_ANALYZER_TOGGLE";
const QUICK_ACCESS: &str = "QA_WVW_ANALYZER";
// Nexus keeps textures by name for the whole game session: rename it when the image changes,
// or a hot-reloaded addon keeps showing the old one. Nexus dims it unless hovered.
const ICON: &str = "TEX_WVW_ANALYZER_QA2";
const ICON_PNG: &[u8] = include_bytes!("../assets/icon.png");

static APP: Mutex<Option<App>> = Mutex::new(None);
/// Set after a panic: the addon stops drawing instead of risking the game.
static FAILED: AtomicBool = AtomicBool::new(false);

fn with_app(what: &str, f: impl FnOnce(&mut App)) {
    if FAILED.load(Ordering::Relaxed) {
        return;
    }
    let result = catch_unwind(AssertUnwindSafe(|| {
        let mut guard = APP.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(app) = guard.as_mut() {
            f(app);
        }
    }));
    if result.is_err() {
        FAILED.store(true, Ordering::Relaxed);
        log::error!("{what} failed; WvW Analyzer overlay disabled until reload");
    }
}

/// The UI scale the fonts were last sized for (f32 bits).
static FONT_SCALE: AtomicU32 = AtomicU32::new(0);

/// Nexus's UI scale (the game's interface size), 1 until Nexus reports one.
fn ui_scale() -> f32 {
    read_nexus_link().map(|l| l.scaling).filter(|s| s.is_finite() && *s > 0.2).unwrap_or(1.0)
}

/// Hands Inter to Nexus at each size of the type scale. Nexus adds them to its atlas and calls
/// back with each `ImFont`; until then the view keeps the current font.
fn register_fonts(scale: f32) {
    // SAFETY: ImGui's own constructor; the config is leaked on purpose, as Nexus may read it
    // when it rebuilds the atlas later. The font bytes are static, so the atlas must not own
    // (and free) them; the glyph ranges are static too.
    let config = unsafe {
        let raw = sys::ImFontConfig_ImFontConfig();
        (*raw).FontDataOwnedByAtlas = false;
        (*raw).GlyphRanges = GLYPH_RANGES.as_ptr();
        &*raw
    };
    let receive = font_receive!(|id, font| {
        if let Some(f) = Font::from_id(id) {
            theme::set_font(f, font.map(|p| p as *mut sys::ImFont));
        }
    });
    for f in Font::ALL {
        add_font_from_memory(f.id(), f.data(), f.size() * scale, Some(config), receive)
            .revert_on_unload();
    }
    FONT_SCALE.store(scale.to_bits(), Ordering::Relaxed);
}

/// Resizes the fonts when the player changes the game's interface size.
fn follow_scale(scale: f32) {
    let last = f32::from_bits(FONT_SCALE.load(Ordering::Relaxed));
    if (scale - last).abs() > 0.01 {
        FONT_SCALE.store(scale.to_bits(), Ordering::Relaxed);
        for f in Font::ALL {
            resize_font(f.id(), f.size() * scale);
        }
    }
}

fn in_combat() -> bool {
    get_mumble_link().is_some_and(|m| m.read_ui_state().contains(UiState::IS_IN_COMBAT))
}

fn load() {
    FAILED.store(false, Ordering::Relaxed);
    let settings_path = get_addon_dir("WvWAnalyzer").ok().map(|d| d.join("settings.json"));
    *APP.lock().unwrap_or_else(|e| e.into_inner()) =
        Some(App::new(Client::start(PORTS), settings_path));

    register_render(
        RenderType::Render,
        render!(|ui: &Ui| {
            let scale = ui_scale();
            follow_scale(scale);
            with_app("render", |app| app.render(ui, in_combat(), scale))
        }),
    )
    .revert_on_unload();
    register_render(
        RenderType::OptionsRender,
        render!(|ui: &Ui| with_app("options", |app| app.render_options(ui))),
    )
    .revert_on_unload();

    register_keybind_with_string(
        KEYBIND,
        keybind_handler!(|_id, is_release| {
            if !is_release {
                with_app("keybind", App::toggle);
            }
        }),
        "ALT+SHIFT+W",
    )
    .revert_on_unload();

    register_fonts(ui_scale());
    load_texture_from_memory(ICON, ICON_PNG, None);
    add_quick_access(QUICK_ACCESS, ICON, ICON, KEYBIND, "WvW Analyzer").revert_on_unload();
    log::info!("loaded");
}

fn unload() {
    // Render callbacks, keybind, fonts and Quick Access are removed by revert_on_unload; the
    // font pointers are forgotten so nothing draws with a released font.
    for f in Font::ALL {
        theme::set_font(f, None);
    }
    let app = APP.lock().unwrap_or_else(|e| e.into_inner()).take();
    if let Some(mut app) = app {
        app.save();
        app.client.stop();
    }
    log::info!("unloaded");
}
