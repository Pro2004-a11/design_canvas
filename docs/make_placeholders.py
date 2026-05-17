"""Generate placeholder screenshot images for the README.

Run once to scaffold docs/screenshots/*.png. Replace each file with a real
capture of the app when ready — keep the filenames identical so the README
keeps working.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

BG = (26, 26, 26)
PANEL = (36, 36, 36)
ACCENT = (232, 120, 48)
MUTED = (136, 136, 136)
TEXT = (235, 235, 235)

SHOTS = [
    ("01-canvas.png", "Canvas — 3D Layer",
     "Primitives + imported OBJ/GLB on the staging canvas"),
    ("02-layers.png", "Layer System",
     "Background / Objects / Drawing / Lighting controls"),
    ("03-generate.png", "Generate",
     "Composite sent to ComfyUI — live WebSocket progress"),
    ("04-gallery.png", "Gallery + A|B Compare",
     "Result lightbox and before/after comparison slider"),
]

W, H = 1280, 800


def _font(size, bold=False):
    names = (["arialbd.ttf", "Arial Bold.ttf"] if bold
             else ["arial.ttf", "Arial.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make(name, title, caption):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # window chrome
    d.rectangle([0, 0, W, 48], fill=PANEL)
    for i, c in enumerate([(224, 82, 82), (232, 224, 82), (76, 175, 80)]):
        d.ellipse([20 + i * 26, 17, 34 + i * 26, 31], fill=c)
    d.text((120, 16), "Design Canvas", font=_font(15, True), fill=TEXT)

    # left tool rail
    d.rectangle([0, 48, 64, H], fill=PANEL)
    # right inspector
    d.rectangle([W - 280, 48, W, H], fill=PANEL)

    # accent frame on the staging area
    d.rectangle([96, 92, W - 312, H - 96], outline=ACCENT, width=2)

    # centred label
    tf, cf = _font(40, True), _font(20)
    tw = d.textlength(title, font=tf)
    cw = d.textlength(caption, font=cf)
    cx = (96 + W - 312) // 2
    cy = H // 2
    d.text((cx - tw / 2, cy - 46), title, font=tf, fill=ACCENT)
    d.text((cx - cw / 2, cy + 14), caption, font=cf, fill=MUTED)

    ph = "PLACEHOLDER — replace with a real screenshot"
    pf = _font(13)
    d.text((cx - d.textlength(ph, font=pf) / 2, cy + 54), ph,
           font=pf, fill=(90, 90, 90))

    img.save(OUT / name)
    print("wrote", name)


if __name__ == "__main__":
    for args in SHOTS:
        make(*args)
