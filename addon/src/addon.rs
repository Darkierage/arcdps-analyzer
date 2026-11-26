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
    localization::set_translation,
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
/// The keybind's name in Nexus's keybind list (it shows the identifier without one). English in
/// every language Nexus ships, like the rest of the overlay.
const KEYBIND_NAME: &str = "Toggle WvW Analyzer window";
const NEXUS_LANGUAGES: [&str; 10] = ["br", "cn", "cz", "de", "en", "es", "fr", "it", "pl", "ru"];
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

/// The size each font was last asked for (f32 bits; index = `Font::index`).
static ASKED: [AtomicU32; 6] = [const { AtomicU32::new(0) }; 6];
/// How much larger than asked Nexus builds fonts (f32 bits; 0 = not measured yet).
static FONT_FACTOR: AtomicU32 = AtomicU32::new(0);

fn load_f32(a: &AtomicU32) -> f32 {
    f32::from_bits(a.load(Ordering::Relaxed))
}

fn store_f32(a: &AtomicU32, v: f32) {
    a.store(v.to_bits(), Ordering::Relaxed);
}

/// Nexus's UI scale (the game's interface size), 1 until Nexus reports one.
fn ui_scale() -> f32 {
    read_nexus_link().map(|l| l.scaling).filter(|s| s.is_finite() && *s > 0.2).unwrap_or(1.0)
}

/// Hands Inter to Nexus at each size of the type scale. Nexus adds them to its atlas and calls
/// back with each `ImFont`; until then the view keeps the current font.
fn register_fonts(scale: f32) {
    // Everything Nexus keeps a pointer to is a heap copy that is never freed (about 80 KB per
    // load): Nexus may rebuild its atlas from it after this DLL is unloaded or reloaded. The atlas
    // must not own (and free) the font bytes.
    let regular = theme::leak_copy(theme::INTER_REGULAR);
    let semibold = theme::leak_copy(theme::INTER_SEMIBOLD);
    let ranges = theme::leak_copy(&GLYPH_RANGES);
    // SAFETY: ImGui's constructor sets the defaults; the struct is copied into a leaked Box and
    // ImGui's own allocation is destroyed right away.
    let config: &'static sys::ImFontConfig = unsafe {
        let raw = sys::ImFontConfig_ImFontConfig();
        let mut copy = std::ptr::read(raw);
        sys::ImFontConfig_destroy(raw);
        copy.FontDataOwnedByAtlas = false;
        copy.GlyphRanges = ranges.as_ptr();
        Box::leak(Box::new(copy))
    };
    let receive = font_receive!(|id, font| {
        if let Some(f) = Font::from_id(id) {
            theme::set_font(f, font.map(|p| p as *mut sys::ImFont));
        }
    });
    for f in Font::ALL {
        let data = if f.semibold() { semibold } else { regular };
        store_f32(&ASKED[f.index()], f.size() * scale);
        add_font_from_memory(f.id(), data, f.size() * scale, Some(config), receive)
            .revert_on_unload();
    }
    store_f32(&FONT_FACTOR, 0.0);
}

/// Keeps the fonts at the type scale times `scale` (the UI scale times the size option), rounded
/// to whole pixels, which draw a little cleaner. Nexus may build a font larger than asked (seen
/// in game: 1.5 times, Windows scaling at 150% with Nexus's DPI scaling on), while the layout
/// uses `scale` alone; the first font handed over gives that factor, and every font is then
/// asked for that much less. Follows the interface size and the size option. Called each frame
/// on the render thread with the addon's lock held: safe, since Nexus's font callback only
/// stores pointers.
fn follow_scale(scale: f32) {
    let mut factor = load_f32(&FONT_FACTOR);
    if factor == 0.0 {
        // Measured once, from a font as first added (never from a resized one).
        let Some((f, got)) = Font::ALL.into_iter().find_map(|f| Some((f, theme::loaded_size(f)?)))
        else {
            return;
        };
        factor = theme::font_factor(load_f32(&ASKED[f.index()]), got);
        store_f32(&FONT_FACTOR, factor);
        if (factor - 1.0).abs() > 0.01 {
            log::info!("Nexus builds fonts {factor:.2}x the asked size; asking for less");
        }
    }
    for f in Font::ALL {
        let size = (f.size() * scale).round() / factor;
        if (size - load_f32(&ASKED[f.index()])).abs() > 0.01 {
            store_f32(&ASKED[f.index()], size);
            resize_font(f.id(), size);
        }
    }
}

fn in_combat() -> bool {
    get_mumble_link().is_some_and(|m| m.read_ui_state().contains(UiState::IS_IN_COMBAT))
}

fn load() {
    // nexus-rs forwards every level to Nexus.log; ureq's debug and trace lines (a hex dump of
    // each overlay request) would grow it by megabytes an hour.
    log::set_max_level(log::LevelFilter::Info);
    FAILED.store(false, Ordering::Relaxed);
    let settings_path = get_addon_dir("WvWAnalyzer").ok().map(|d| d.join("settings.json"));
    *APP.lock().unwrap_or_else(|e| e.into_inner()) =
        Some(App::new(Client::start(PORTS), settings_path));

    register_render(
        RenderType::Render,
        render!(|ui: &Ui| {
            let ui_scale = ui_scale();
            with_app("render", |app| {
                // The size option scales text and layout together, so proportions stay.
                let scale = ui_scale * app.size_factor();
                follow_scale(scale);
                app.render(ui, in_combat(), scale)
            })
        }),
    )
    .revert_on_unload();
    register_render(
        RenderType::OptionsRender,
        render!(|ui: &Ui| with_app("options", |app| app.render_options(ui))),
    )
    .revert_on_unload();

    for lang in NEXUS_LANGUAGES {
        set_translation(KEYBIND, lang, KEYBIND_NAME);
    }
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
