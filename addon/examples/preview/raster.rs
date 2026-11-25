//! A small CPU rasterizer for ImGui draw data: vertex color times the font atlas' alpha, clip
//! rectangles and alpha blending. Enough to check layout, wrapping, sizes and colors; not
//! pixel-identical to the game's renderer.

use imgui::{DrawCmd, DrawCmdParams, DrawData, DrawVert};

pub struct Atlas {
    pub width: usize,
    pub height: usize,
    pub alpha: Vec<u8>,
}

impl Atlas {
    /// Bilinear sample of the atlas' alpha at a texture coordinate, 0..1.
    fn sample(&self, u: f32, v: f32) -> f32 {
        let x = u * self.width as f32 - 0.5;
        let y = v * self.height as f32 - 0.5;
        let (x0, y0) = (x.floor(), y.floor());
        let (fx, fy) = (x - x0, y - y0);
        let at = |xi: f32, yi: f32| -> f32 {
            let xi = (xi as isize).clamp(0, self.width as isize - 1) as usize;
            let yi = (yi as isize).clamp(0, self.height as isize - 1) as usize;
            self.alpha[yi * self.width + xi] as f32 / 255.0
        };
        let top = at(x0, y0) * (1.0 - fx) + at(x0 + 1.0, y0) * fx;
        let bottom = at(x0, y0 + 1.0) * (1.0 - fx) + at(x0 + 1.0, y0 + 1.0) * fx;
        top * (1.0 - fy) + bottom * fy
    }
}

/// An RGB image with float channels, 0..1.
pub struct Image {
    pub width: usize,
    pub height: usize,
    pub rgb: Vec<[f32; 3]>,
}

impl Image {
    pub fn new(width: usize, height: usize, background: [f32; 3]) -> Self {
        Self { width, height, rgb: vec![background; width * height] }
    }

    /// 8-bit RGB rows of the `w` by `h` area at `x`, `y`.
    pub fn crop_rgb8(&self, x: usize, y: usize, w: usize, h: usize) -> Vec<u8> {
        let mut out = Vec::with_capacity(w * h * 3);
        for row in y..y + h {
            for px in &self.rgb[row * self.width + x..row * self.width + x + w] {
                for c in px {
                    out.push((c.clamp(0.0, 1.0) * 255.0 + 0.5) as u8);
                }
            }
        }
        out
    }
}

/// Draws all of ImGui's draw lists into `img`. The font atlas is texture 1; other textures
/// (none are used today) draw as plain vertex color.
pub fn draw(img: &mut Image, data: &DrawData, atlas: &Atlas) {
    let origin = data.display_pos;
    for list in data.draw_lists() {
        let vtx = list.vtx_buffer();
        let idx = list.idx_buffer();
        for cmd in list.commands() {
            let DrawCmd::Elements { count, cmd_params } = cmd else { continue };
            let DrawCmdParams { clip_rect, texture_id, vtx_offset, idx_offset } = cmd_params;
            let clip = [
                clip_rect[0] - origin[0],
                clip_rect[1] - origin[1],
                clip_rect[2] - origin[0],
                clip_rect[3] - origin[1],
            ];
            let textured = texture_id.id() == 1;
            for tri in idx[idx_offset..idx_offset + count].as_chunks::<3>().0 {
                let v = |i: usize| &vtx[vtx_offset + tri[i] as usize];
                triangle(img, [v(0), v(1), v(2)], origin, clip, textured.then_some(atlas));
            }
        }
    }
}

fn triangle(
    img: &mut Image,
    v: [&DrawVert; 3],
    origin: [f32; 2],
    clip: [f32; 4],
    atlas: Option<&Atlas>,
) {
    let p: Vec<[f32; 2]> = v.iter().map(|x| [x.pos[0] - origin[0], x.pos[1] - origin[1]]).collect();
    let area = edge(p[0], p[1], p[2]);
    if area.abs() < 1e-8 {
        return;
    }
    // Pixel bounds: the triangle's box inside the clip rectangle and the image.
    let min_x = p.iter().map(|q| q[0]).fold(f32::MAX, f32::min).max(clip[0]).max(0.0);
    let min_y = p.iter().map(|q| q[1]).fold(f32::MAX, f32::min).max(clip[1]).max(0.0);
    let max_x = p.iter().map(|q| q[0]).fold(f32::MIN, f32::max).min(clip[2]).min(img.width as f32);
    let max_y =
        p.iter().map(|q| q[1]).fold(f32::MIN, f32::max).min(clip[3]).min(img.height as f32);
    if min_x >= max_x || min_y >= max_y {
        return;
    }
    let col: Vec<[f32; 4]> =
        v.iter().map(|x| x.col.map(|c| c as f32 / 255.0)).collect();
    // Top-left fill rule, so pixels on an edge shared by two triangles are drawn once.
    let sign = area.signum();
    let bias = |a: [f32; 2], b: [f32; 2]| -> f32 {
        let (dx, dy) = ((b[0] - a[0]) * sign, (b[1] - a[1]) * sign);
        let top_left = (dy == 0.0 && dx > 0.0) || dy < 0.0;
        if top_left { 0.0 } else { -1e-6 }
    };
    let biases = [bias(p[1], p[2]), bias(p[2], p[0]), bias(p[0], p[1])];
    for y in (min_y.floor() as usize)..(max_y.ceil() as usize) {
        for x in (min_x.floor() as usize)..(max_x.ceil() as usize) {
            let c = [x as f32 + 0.5, y as f32 + 0.5];
            if c[0] < clip[0] || c[0] >= clip[2] || c[1] < clip[1] || c[1] >= clip[3] {
                continue;
            }
            let w = [edge(p[1], p[2], c) / area, edge(p[2], p[0], c) / area, edge(p[0], p[1], c) / area];
            if w.iter().zip(biases).any(|(wi, b)| *wi + b < 0.0) {
                continue;
            }
            let mut rgba = [0.0f32; 4];
            for (k, item) in rgba.iter_mut().enumerate() {
                *item = w[0] * col[0][k] + w[1] * col[1][k] + w[2] * col[2][k];
            }
            if let Some(atlas) = atlas {
                let u = w[0] * v[0].uv[0] + w[1] * v[1].uv[0] + w[2] * v[2].uv[0];
                let vv = w[0] * v[0].uv[1] + w[1] * v[1].uv[1] + w[2] * v[2].uv[1];
                rgba[3] *= atlas.sample(u, vv);
            }
            let a = rgba[3].clamp(0.0, 1.0);
            let dst = &mut img.rgb[y * img.width + x];
            for k in 0..3 {
                dst[k] = rgba[k] * a + dst[k] * (1.0 - a);
            }
        }
    }
}

fn edge(a: [f32; 2], b: [f32; 2], c: [f32; 2]) -> f32 {
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
}
