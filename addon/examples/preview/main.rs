//! Draws every overlay state with the addon's own `view` code into PNGs, without the game:
//! `cargo run --example preview` writes them to `addon/target/preview/`.
//!
//! The payloads are synthetic (the shared test fixture, changed per state). The images show
//! layout, wrapping, sizes and colors; Nexus's renderer and UI scale differ, so they are not
//! pixel-identical to the game.

mod png;
mod raster;

use WvWAnalyzer::client::{Snapshot, Status};
use WvWAnalyzer::model::Overlay;
use WvWAnalyzer::view;
use imgui::{Context, FontSource, TextureId, Ui};
use std::path::{Path, PathBuf};

const FIXTURE: &str = include_str!("../../tests/fixtures/overlay.json");
/// Behind the window: a dark gray, roughly what the window sits on in game.
const BACKDROP: [f32; 3] = [0.19, 0.20, 0.19];

fn main() {
    let out = Path::new(env!("CARGO_MANIFEST_DIR")).join("target").join("preview");
    std::fs::create_dir_all(&out).expect("create target/preview");
    let mut written = Vec::new();
    for (name, snap) in states() {
        written.push(render(&out, name, |ui| {
            view::main_window(ui, &snap, 1.0);
        }));
    }
    for p in written {
        println!("{}", p.display());
    }
}

fn fixture() -> Overlay {
    Overlay::parse(FIXTURE).expect("fixture parses")
}

fn connected(data: Overlay) -> Snapshot {
    Snapshot { status: Status::Connected, data: Some(data), action_error: None }
}

fn states() -> Vec<(&'static str, Snapshot)> {
    let mut no_fights = fixture();
    no_fights.fight = None;
    vec![
        ("fight", connected(fixture())),
        ("empty", connected(no_fights)),
        ("not-running", Snapshot { status: Status::Searching, data: None, action_error: None }),
        (
            "problem",
            Snapshot {
                status: Status::Problem("WvW Analyzer answered with an error (500).".into()),
                data: None,
                action_error: None,
            },
        ),
    ]
}

/// Runs a few headless frames (windows size themselves over the first ones), rasterizes the
/// last one and writes `<name>.png`, cropped to what was drawn.
fn render(out: &Path, name: &str, draw: impl Fn(&Ui)) -> PathBuf {
    let mut ctx = Context::create();
    ctx.set_ini_filename(None);
    ctx.io_mut().display_size = [1200.0, 1200.0];
    ctx.io_mut().delta_time = 1.0 / 60.0;
    ctx.io_mut().mouse_pos = [-f32::MAX, -f32::MAX];
    let atlas = {
        let mut fonts = ctx.fonts();
        fonts.add_font(&[FontSource::DefaultFontData { config: None }]);
        let tex = fonts.build_alpha8_texture();
        let atlas = raster::Atlas {
            width: tex.width as usize,
            height: tex.height as usize,
            alpha: tex.data.to_vec(),
        };
        fonts.tex_id = TextureId::new(1);
        atlas
    };
    for _ in 0..3 {
        let ui = ctx.frame();
        draw(&ui);
        ui.render();
    }
    let ui = ctx.frame();
    draw(&ui);
    let data = ui.render();
    // The box around everything drawn: the window(s).
    let (mut lo, mut hi) = ([f32::MAX; 2], [0.0f32; 2]);
    for list in data.draw_lists() {
        for v in list.vtx_buffer() {
            for k in 0..2 {
                lo[k] = lo[k].min(v.pos[k]);
                hi[k] = hi[k].max(v.pos[k]);
            }
        }
    }
    let size = data.display_size;
    let mut img = raster::Image::new(size[0] as usize, size[1] as usize, BACKDROP);
    raster::draw(&mut img, data, &atlas);
    let (x, y) = (lo[0].max(0.0).floor() as usize, lo[1].max(0.0).floor() as usize);
    let w = (hi[0].min(size[0]).ceil() as usize).saturating_sub(x).max(1);
    let h = (hi[1].min(size[1]).ceil() as usize).saturating_sub(y).max(1);
    let path = out.join(format!("{name}.png"));
    png::write_rgb(&path, w, h, &img.crop_rgb8(x, y, w, h)).expect("write png");
    path
}
