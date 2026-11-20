"""Draw the overlay's Quick Access icon (addon/assets/icon.png).

It follows the game's menu-bar style: a flat khaki silhouette with a dark edge and a two-tone
shade, no background. Here a shield (WvW) with a bar chart (stats) cut into it.

Nexus draws icons that aren't hovered at roughly 43% brightness and hovered ones at full, like
the other addons' icons. So the texture is a light, warm near-white that shows as khaki.

    uv run --no-project --with pillow python scripts/draw_addon_icon.py
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 256  # drawn supersampled, saved at 64x64
SIZE = 64
OUT = Path(__file__).resolve().parents[1] / "addon" / "assets"
Color = tuple[int, int, int]


def shield() -> list[tuple[float, float]]:
    """Flat top, straight sides, then a rounded taper to the point."""
    left, right, top, side, tip, cx = 0.16 * S, 0.84 * S, 0.10 * S, 0.52 * S, 0.92 * S, S / 2
    curve = [(edge + (cx - edge) * a, side + (tip - side) * math.sin(a * math.pi / 2))
             for edge in (right, left) for a in (i / 20 for i in range(1, 20))]
    right_side, left_side = curve[:19], curve[19:][::-1]
    return [(left, top), (right, top), (right, side), *right_side, (cx, tip), *left_side,
            (left, side)]


def chart() -> Image.Image:
    """Three rising bars, cut out of the shield."""
    cut = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(cut)
    w, gap, bottom = 0.11 * S, 0.055 * S, 0.70 * S
    x = S / 2 - 1.5 * w - gap
    for h in (0.20, 0.32, 0.46):
        d.rounded_rectangle((x, bottom - h * S, x + w, bottom), radius=0.02 * S, fill=255)
        x += w + gap
    return cut


def icon(base: Color, shade: Color, edge: Color) -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    body = Image.new("L", (S, S), 0)
    ImageDraw.Draw(body).polygon(shield(), fill=255)
    right_half = Image.new("L", (S, S), 0)
    ImageDraw.Draw(right_half).rectangle((S // 2, 0, S, S), fill=255)
    cut = chart()
    im.paste((*edge, 255), (0, 0), body.filter(ImageFilter.MaxFilter(9)))
    im.paste((*base, 255), (0, 0), body)
    im.paste((*shade, 255), (0, 0), ImageChops.multiply(body, right_half))
    im.paste((*edge, 255), (0, 0), cut.filter(ImageFilter.MaxFilter(5)))
    im.putalpha(ImageChops.subtract(im.getchannel("A"), cut))
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    # Dimmed by Nexus, these show as about (107, 104, 92) and (90, 88, 78): the khaki measured
    # on the other icons in the bar.
    icon((248, 242, 214), (210, 205, 181), (24, 22, 20)).save(OUT / "icon.png", optimize=True)
    print(f"wrote {OUT / 'icon.png'}")


if __name__ == "__main__":
    main()
