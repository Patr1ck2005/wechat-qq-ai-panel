"""Build original, font-free application artwork with the existing Pillow dependency.

No network, native app, account data or model is used. Geometry is shared by the
editable SVG and matching supersampled PNG/Windows ICO renderers.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "wq_panel" / "assets"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
BACK = "M 71 102 H 151 Q 176 102 176 127 V 167 Q 176 191 151 191 H 105 L 69 212 L 75 191 H 71 Q 47 191 47 167 V 127 Q 47 102 71 102 Z"
FRONT = "M 89 59 H 177 Q 204 59 204 86 V 139 Q 204 166 177 166 H 171 L 184 188 L 144 166 H 89 Q 63 166 63 139 V 86 Q 63 59 89 59 Z"
STAR = [(191, 44), (197, 61), (214, 67), (197, 73), (191, 90), (185, 73), (168, 67), (185, 61)]
DOTS = (96, 122, 148)


def svg() -> str:
    star = " ".join(f"{x},{y}" for x, y in STAR)
    dots = "".join(f'<circle cx="{x}" cy="111" r="5.5" fill="#5270d8"/>' for x in DOTS)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256" role="img" aria-labelledby="title desc">
<title id="title">WeChat QQ AI Panel</title><desc id="desc">Two conversation cards with an aqua sparkle on a blue and indigo rounded tile.</desc>
<defs><linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#508bff"/><stop offset="1" stop-color="#5141cf"/></linearGradient><linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ffffff" stop-opacity=".20"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient></defs>
<rect x="16" y="16" width="224" height="224" rx="58" fill="url(#tile)"/>
<rect x="17" y="17" width="222" height="222" rx="57" fill="none" stroke="url(#sheen)" stroke-width="2"/>
<path d="{BACK}" fill="#a7c5ff"/>
<path d="{FRONT}" fill="#ffffff"/>
{dots}<polygon points="{star}" fill="#61e8d5" stroke="#5267e7" stroke-width="3" stroke-linejoin="round"/>
</svg>
'''


def raster(size: int = 256) -> Image.Image:
    # Draw above target resolution so all Windows icon sizes have clean edges.
    scale = 4
    canvas = 256 * scale
    mask = Image.new("L", (canvas, canvas))
    shape = ImageDraw.Draw(mask)
    shape.rounded_rectangle((16*scale, 16*scale, 240*scale, 240*scale), radius=58*scale, fill=255)
    tile = Image.new("RGBA", (canvas, canvas))
    pixels = tile.load()
    start, end = (80, 139, 255), (81, 65, 207)
    for y in range(canvas):
        for x in range(canvas):
            fraction = max(0, min(1, ((x + y) / scale - 32) / 448))
            pixels[x, y] = tuple(round(a + (b-a)*fraction) for a, b in zip(start, end)) + (255,)
    tile.putalpha(mask)
    draw = ImageDraw.Draw(tile)
    def point(pair):
        return tuple(round(v * scale) for v in pair)
    def rounded(box, radius, fill):
        draw.rounded_rectangle(point(box[:2]) + point(box[2:]), radius=radius*scale, fill=fill)
    rounded((47, 102, 176, 191), 24, "#a7c5ff")
    draw.polygon([point(p) for p in ((75, 183), (69, 212), (114, 186))], fill="#a7c5ff")
    rounded((63, 59, 204, 166), 27, "white")
    draw.polygon([point(p) for p in ((140, 156), (184, 188), (169, 156))], fill="white")
    for x in DOTS:
        draw.ellipse(point((x-5.5, 105.5)) + point((x+5.5, 116.5)), fill="#5270d8")
    polygon = [point(p) for p in STAR]
    draw.polygon(polygon, fill="#61e8d5")
    draw.line(polygon + [polygon[0]], fill="#5267e7", width=3*scale, joint="curve")
    return tile.resize((size, size), Image.Resampling.LANCZOS)


def main():
    DESTINATION.mkdir(exist_ok=True)
    (DESTINATION / "app.svg").write_text(svg(), encoding="utf-8", newline="\n")
    image = raster()
    image.save(DESTINATION / "app.png", optimize=True)
    image.save(DESTINATION / "app.ico", sizes=[(size, size) for size in ICO_SIZES])
    with Image.open(DESTINATION / "app.ico") as icon:
        if icon.ico.sizes() != {(size, size) for size in ICO_SIZES}:
            raise RuntimeError("ICO_SIZE_MISMATCH")
    print("Built original SVG, PNG and 9-size Windows ICO; no private data used.")


if __name__ == "__main__":
    main()
