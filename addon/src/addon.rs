//! Nexus entry points: load/unload, render callbacks, Quick Access icon and keybind.

use crate::client::{Client, PORTS};
use crate::ui::App;
use nexus::{
    AddonFlags, UpdateProvider,
    data_link::mumble::{UiState, get_mumble_link},
    gui::{RenderType, register_render, render},
    imgui::Ui,
    keybind::{keybind_handler, register_keybind_with_string},
    paths::get_addon_dir,
    quick_access::add_quick_access,
    texture::load_texture_from_memory,
};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

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
        render!(|ui: &Ui| with_app("render", |app| app.render(ui, in_combat()))),
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

    load_texture_from_memory(ICON, ICON_PNG, None);
    add_quick_access(QUICK_ACCESS, ICON, ICON, KEYBIND, "WvW Analyzer").revert_on_unload();
    log::info!("loaded");
}

fn unload() {
    // Render callbacks, keybind and Quick Access are removed by revert_on_unload.
    let app = APP.lock().unwrap_or_else(|e| e.into_inner()).take();
    if let Some(mut app) = app {
        app.save();
        app.client.stop();
    }
    log::info!("unloaded");
}
