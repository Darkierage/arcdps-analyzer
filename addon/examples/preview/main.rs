//! Draws every overlay state with the addon's own `view` code into PNGs, without the game:
//! `cargo run --example preview` writes them to `addon/target/preview/`.
//!
//! The payloads are synthetic (the shared test fixture, or the mockups' sample wording). The
//! images show layout, wrapping, sizes and colors; Nexus's renderer and UI scale differ, so
//! they are not pixel-identical to the game.

mod png;
mod raster;
mod states;

use WvWAnalyzer::view::theme::{self, Font, GLYPH_RANGES};
use imgui::{Context, FontConfig, FontGlyphRanges, FontSource, TextureId, Ui, sys};
use std::path::{Path, PathBuf};

/// Behind the window: a dark gray, roughly what the window sits on in game.
const BACKDROP: [f32; 3] = [0.19, 0.20, 0.19];

fn main() {
    let out = Path::new(env!("CARGO_MANIFEST_DIR")).join("target").join("preview");
    std::fs::create_dir_all(&out).expect("create target/preview");
    for state in states::all() {
        let path = render(&out, &state.name, state.size, |ui| (state.draw)(ui));
        println!("{}", path.display());
    }
}

/// Runs a few headless frames (windows size themselves over the first ones), rasterizes the
/// last one and writes `<name>.png`, cropped to what was drawn. `size` resizes the main window.
fn render(out: &Path, name: &str, size: Option<[f32; 2]>, draw: impl Fn(&Ui)) -> PathBuf {
    let mut ctx = Context::create();
    ctx.set_ini_filename(None);
    ctx.io_mut().display_size = [1400.0, 1400.0];
    ctx.io_mut().delta_time = 1.0 / 60.0;
    ctx.io_mut().mouse_pos = [-f32::MAX, -f32::MAX];
    let atlas = load_fonts(&mut ctx);
    for i in 0..5 {
        let ui = ctx.frame();
        if let (Some(s), true) = (size, i > 0) {
            // SAFETY: plain ImGui call inside a frame, with a static C string.
            unsafe {
                sys::igSetWindowSize_Str(
                    c"WvW Analyzer###wvw_analyzer".as_ptr(),
                    sys::ImVec2 { x: s[0], y: s[1] },
                    sys::ImGuiCond_Always as i32,
                );
            }
        }
        draw(&ui);
        if i < 4 {
            ui.render();
            continue;
        }
        let data = ui.render();
        let (lo, hi) = raster::drawn_box(data);
        let disp = data.display_size;
        let mut img = raster::Image::new(disp[0] as usize, disp[1] as usize, BACKDROP);
        raster::draw(&mut img, data, &atlas);
        let (x, y) = (lo[0].max(0.0).floor() as usize, lo[1].max(0.0).floor() as usize);
        let w = (hi[0].min(disp[0]).ceil() as usize).saturating_sub(x).max(1);
        let h = (hi[1].min(disp[1]).ceil() as usize).saturating_sub(y).max(1);
        let path = out.join(format!("{name}.png"));
        png::write_rgb(&path, w, h, &img.crop_rgb8(x, y, w, h)).expect("write png");
        for f in Font::ALL {
            theme::set_font(f, None);
        }
        return path;
    }
    unreachable!()
}

/// ImGui's default font (what shows before Nexus hands Inter over), then Inter at every size of
/// the type scale, handed to the view as the addon does with Nexus's fonts.
fn load_fonts(ctx: &mut Context) -> raster::Atlas {
    let mut fonts = ctx.fonts();
    fonts.add_font(&[FontSource::DefaultFontData { config: None }]);
    for f in Font::ALL {
        fonts.add_font(&[FontSource::TtfData {
            data: f.data(),
            size_pixels: f.size(),
            config: Some(FontConfig {
                glyph_ranges: FontGlyphRanges::from_slice(&GLYPH_RANGES),
                ..FontConfig::default()
            }),
        }]);
    }
    let tex = fonts.build_alpha8_texture();
    let atlas = raster::Atlas {
        width: tex.width as usize,
        height: tex.height as usize,
        alpha: tex.data.to_vec(),
    };
    fonts.tex_id = TextureId::new(1);
    drop(fonts);
    // SAFETY: reads the atlas' font list of the current context; the pointers stay valid until
    // the context is dropped, and `render` forgets them before that.
    unsafe {
        let atlas_ptr = (*sys::igGetIO()).Fonts;
        let list = &(*atlas_ptr).Fonts;
        for (i, f) in Font::ALL.into_iter().enumerate() {
            theme::set_font(f, Some(*list.Data.add(i + 1)));
        }
    }
    atlas
}
