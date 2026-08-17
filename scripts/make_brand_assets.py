"""Strip the white background off the Oneread logo and generate the asset set."""
import sys

import numpy as np
from PIL import Image
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/Users/ivoip/Downloads/Oneread logo.png")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend/public"      # what the app ships
WEB = OUT / "brand"
BRAND = ROOT / "brand"               # full-size masters, not bundled
for d in (WEB, BRAND):
    d.mkdir(parents=True, exist_ok=True)

# Matting ramp: pixels darker than T are fully opaque, white is fully clear, and
# everything between keeps the alpha it needs to reproduce the original over white.
# A wide ramp is what kills the pale fringe around the edges on dark backgrounds.
T = 20.0

img = Image.open(SRC).convert("RGB")
px = np.asarray(img).astype(np.float32)
mn = px.min(axis=2)

alpha = np.clip((255.0 - mn) / (255.0 - T), 0.0, 1.0)

# Unpremultiply: edge pixels are fg blended over white, recover the true color.
a3 = alpha[..., None]
rgb = np.where(a3 > 0.004, (px - (1.0 - a3) * 255.0) / np.maximum(a3, 0.004), px)
rgb = np.clip(rgb, 0, 255)

# Every enclosed white area in this logo is a letter counter (O, e, e, a, a) —
# all ringed by navy — so white goes clear everywhere, no exceptions carved out.

out = np.dstack([rgb, alpha * 255.0]).astype(np.uint8)
logo = Image.fromarray(out, "RGBA")


def content_bbox(im, thresh=96, min_frac=0.0015):
    """Bbox of real ink, ignoring stray near-white speckle from the source JPEG-ish edges."""
    m = np.asarray(im.getchannel("A")) > thresh
    rows = m.sum(axis=1) > max(1, int(m.shape[1] * min_frac))
    cols = m.sum(axis=0) > max(1, int(m.shape[0] * min_frac))
    ys, xs = np.flatnonzero(rows), np.flatnonzero(cols)
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


logo = logo.crop(content_bbox(logo))
logo.save(BRAND / "oneread-logo.png")
print("lockup", logo.size)

# --- split the mark (1R) off the wordmark -------------------------------------
a = np.asarray(logo.getchannel("A")) > 96
rows = a.sum(axis=1) > max(1, int(logo.width * 0.0015))
gaps = []
run = None
for i, filled in enumerate(rows):
    if not filled and run is None:
        run = i
    elif filled and run is not None:
        gaps.append((run, i))
        run = None
gap = max(gaps, key=lambda g: g[1] - g[0])
print("wordmark gap rows", gap)
mark = logo.crop((0, 0, logo.width, gap[0]))
mark = mark.crop(content_bbox(mark))
word = logo.crop((0, gap[1], logo.width, logo.height))
word = word.crop(content_bbox(word))


def square(im, pad=0.0, bg=None):
    """Center im on a square canvas; pad is fraction of the final side left empty."""
    side = int(max(im.size) / (1.0 - pad))
    canvas = Image.new("RGBA", (side, side), bg or (0, 0, 0, 0))
    canvas.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return canvas


mark_sq = square(mark, 0.04)
mark_sq.save(BRAND / "oneread-mark.png")
word.save(BRAND / "oneread-wordmark.png")
print("mark", mark.size, "wordmark", word.size)


def rs(im, size):
    return im.resize((size, size) if isinstance(size, int) else size, Image.LANCZOS)


rs(mark_sq, 1024).save(BRAND / "oneread-mark-1024.png")
for s in (512, 256, 128, 64, 32):
    rs(mark_sq, s).save(WEB / f"oneread-mark-{s}.png")
for wpx in (1024, 512, 256, 128):
    dst = BRAND if wpx == 1024 else WEB
    logo.resize((wpx, round(logo.height * wpx / logo.width)), Image.LANCZOS).save(
        dst / f"oneread-logo-{wpx}.png"
    )

# --- favicons -----------------------------------------------------------------
for s in (16, 32, 48, 96):
    rs(mark_sq, s).save(OUT / f"favicon-{s}x{s}.png")
rs(mark_sq, 256).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

# Apple wants an opaque icon: transparent renders black on iOS.
apple = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
m = rs(square(mark, 0.20), 180)
apple.alpha_composite(m)
apple.convert("RGB").save(OUT / "apple-touch-icon.png")

rs(mark_sq, 192).save(OUT / "android-chrome-192x192.png")
rs(mark_sq, 512).save(OUT / "android-chrome-512x512.png")

# Maskable: 40% safe-zone padding, opaque white so the platform mask can crop.
mask = Image.new("RGBA", (512, 512), (255, 255, 255, 255))
mask.alpha_composite(rs(square(mark, 0.40), 512))
mask.save(OUT / "maskable-icon-512x512.png")

# --- social card --------------------------------------------------------------
og = Image.new("RGBA", (1200, 630), (255, 255, 255, 255))
lw = 420
lk = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
og.alpha_composite(lk, ((1200 - lk.width) // 2, (630 - lk.height) // 2))
og.convert("RGB").save(OUT / "og-image.png")


# --- dark-mode variant --------------------------------------------------------
# The navy reads as a hole on a dark page, so flip its lightness and leave the
# teal alone (teal already carries enough contrast either way).
def on_dark(im):
    a = np.asarray(im).astype(np.float32)
    c, alpha_ch = a[..., :3] / 255.0, a[..., 3:]
    mx, mn_ = c.max(axis=2), c.min(axis=2)
    lum = (mx + mn_) / 2
    delta = mx - mn_
    sat = np.where(delta < 1e-6, 0, delta / np.maximum(1 - np.abs(2 * lum - 1), 1e-6))
    teal = (c[..., 0] < 0.45) & (c[..., 1] > 0.5) & (c[..., 2] > 0.5)
    new_lum = np.clip(0.97 - 0.62 * lum, 0, 1)
    # rebuild each channel at the new lightness, keeping hue and saturation
    scaled = np.where(
        lum[..., None] > 1e-6,
        (c - lum[..., None]) / np.maximum(lum[..., None], 1e-6),
        0,
    )
    out_c = np.clip(new_lum[..., None] * (1 + scaled * np.minimum(sat, 0.16)[..., None]), 0, 1)
    out_c = np.where(teal[..., None], c, out_c)
    return Image.fromarray(
        np.concatenate([out_c * 255.0, alpha_ch], axis=2).astype(np.uint8), "RGBA"
    )


logo_d, mark_d, word_d = on_dark(logo), on_dark(mark_sq), on_dark(word)
logo_d.save(BRAND / "oneread-logo-dark.png")
mark_d.save(BRAND / "oneread-mark-dark.png")
word_d.save(BRAND / "oneread-wordmark-dark.png")
for s in (512, 256, 128, 64, 32):
    rs(mark_d, s).save(WEB / f"oneread-mark-dark-{s}.png")
for wpx in (1024, 512, 256, 128):
    dst = BRAND if wpx == 1024 else WEB
    logo_d.resize((wpx, round(logo_d.height * wpx / logo_d.width)), Image.LANCZOS).save(
        dst / f"oneread-logo-dark-{wpx}.png"
    )

print("done")
