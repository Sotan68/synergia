"""The "paper" look for Engines A and B: textured off-white sheet, navy ink, blue / purple accents.

Headlines are Instrument Serif, running text is Inter Display, and highlighted (**word**) runs switch
to a blue serif italic. Colours and texture strength live in [paper] in config.toml.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from synergia.brand.canvas import safe_for
from synergia.brand.elements import logo_mark
from synergia.brand.typography import font
from synergia.config import CFG, hex_to_rgb

P = CFG.paper
PAPER = hex_to_rgb(P.background)
INK = hex_to_rgb(P.ink)
SOFT = hex_to_rgb(P.soft)
ACCENT = hex_to_rgb(P.accent)
ACCENT2 = hex_to_rgb(P.accent2)

# Font roles (keys of [fonts] in config.toml).
SERIF, SERIF_I = "serif", "serif_italic"
TEXT_W, STRONG_W = "display_medium", "display_semibold"
PARA_W = "paragraph"      # Engine A's paragraph slides: one font for the header and the text
SERIF_IN_SANS = 1.18      # serif italic accent inside Inter text: scale to match the x-height


# ---------------------------------------------------------------- background
def _smooth_noise(rng: np.random.Generator, w: int, h: int, cells: int) -> np.ndarray:
    """Soft cloudy noise in [-1, 1]: a coarse random grid upscaled with bicubic smoothing."""
    gw, gh = cells, max(2, round(cells * h / w))
    small = rng.uniform(0, 255, (gh, gw)).astype(np.uint8)
    big = Image.fromarray(small, "L").resize((w, h), Image.BICUBIC)
    return np.asarray(big, dtype=np.float32) / 127.5 - 1.0


@lru_cache(maxsize=16)
def _background(seed: int, w: int, h: int, variant: int) -> Image.Image:
    rng = np.random.default_rng(seed * 7919 + variant)
    img = np.empty((h, w, 3), np.float32)
    img[:] = PAPER

    # Faint wash: blue drifting in from one top corner, lavender from the opposite bottom corner.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xx / w, yy / h
    side = 1.0 if (seed + variant) % 2 else 0.0          # which corner the blue comes from
    d1 = np.sqrt((nx - side) ** 2 + (ny * 0.7) ** 2)
    d2 = np.sqrt((nx - (1 - side)) ** 2 + ((1 - ny) * 0.7) ** 2)
    wash1 = np.clip(1 - d1 / 0.9, 0, 1) ** 2
    wash2 = np.clip(1 - d2 / 0.9, 0, 1) ** 2
    for wash, col in ((wash1, ACCENT), (wash2, ACCENT2)):
        img += (np.array(col, np.float32) - PAPER)[None, None, :] * (wash * P.tint)[..., None]

    # Mottle: the slightly uneven tone of real paper, at two scales.
    if P.mottle > 0:
        m = 0.65 * _smooth_noise(rng, w, h, 9) + 0.35 * _smooth_noise(rng, w, h, 40)
        img += (m * 255 * P.mottle)[..., None]

    # Grain: monochrome tooth, slightly blue-tinted. Half of it is 2-3 px clumps, so it survives
    # video compression and still reads as paper on a phone.
    if P.grain > 0:
        fine = rng.normal(0, 1, (h, w)).astype(np.float32)
        small = rng.normal(0, 1, (h // 2, w // 2)).astype(np.float32)
        coarse = np.asarray(Image.fromarray(small, "F").resize((w, h), Image.BILINEAR)) * 1.6
        g = (0.6 * fine + 0.55 * coarse) * 255 * P.grain
        img += g[..., None] * np.array([0.95, 0.95, 1.0], np.float32)

    # Fibres / specks: a few tiny darker flecks, like recycled stock.
    n_specks = int(w * h / 9000)
    xs, ys = rng.integers(0, w, n_specks), rng.integers(0, h, n_specks)
    depth = rng.uniform(6, 22, n_specks).astype(np.float32)
    img[ys, xs] -= depth[:, None]

    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def background(seed: int, width: int | None = None, height: int | None = None,
               variant: int = 0) -> Image.Image:
    """A paper sheet for one slide. `seed` fixes the look of a post, `variant` varies each slide."""
    return _background(seed, width or CFG.brand.width, height or CFG.brand.height, variant).copy()


# ---------------------------------------------------------------- chrome
FOOT_SIZE = 30


def footer_baseline(img: Image.Image) -> int:
    return safe_for(img.height).bottom - 14


def footer(img: Image.Image, page: int | None = None, total: int | None = None,
           align: str = "left") -> None:
    """Logo mark + "Synergia" (left or centred) and an optional "02 / 06" page count on the right."""
    box = safe_for(img.height)
    base = footer_baseline(img)
    d = ImageDraw.Draw(img)
    f = font(STRONG_W, FOOT_SIZE)
    mark = logo_mark(30)
    name = CFG.brand.name.capitalize()
    total_w = mark.width + 14 + f.getlength(name)
    x = box.x if align == "left" else round(img.width / 2 - total_w / 2)
    img.paste(mark, (x, base - 11 - mark.height // 2), mark)
    d.text((x + mark.width + 14, base), name, font=f, fill=INK, anchor="ls")
    if page is not None and align == "left":
        d.text((box.right, base), f"{page:02d} / {total:02d}", font=font(TEXT_W, 28), fill=SOFT,
               anchor="rs")


def section_header(img: Image.Image, num: int, label: str, y: int | None = None,
                   face: str | None = None, size: int = 32) -> int:
    """'02  The mirror' over a hairline rule across the column. Returns the rule's y.

    face: one font for both the number and the label (default: Inter Display)."""
    box = safe_for(img.height)
    y = box.y + 80 if y is None else y
    d = ImageDraw.Draw(img, "RGBA")
    nf, lf = (font(face, size), font(face, size)) if face else (font(STRONG_W, size),
                                                                font(TEXT_W, size))
    d.text((box.x, y), f"{num:02d}", font=nf, fill=ACCENT2, anchor="ls")
    d.text((box.x + nf.getlength("00") + 22, y), label, font=lf, fill=INK, anchor="ls")
    rule = y + 30
    d.line([(box.x, rule), (box.right, rule)], fill=INK + (34,), width=2)
    return rule


def swipe_pill(img: Image.Image) -> None:
    """Navy 'Swipe →' pill on the right of the footer row (carousel covers)."""
    box = safe_for(img.height)
    base = footer_baseline(img)
    f = font(STRONG_W, 30)
    txt = "Swipe  →"
    w = f.getlength(txt)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([box.right - w - 48, base - 42, box.right, base + 16], radius=29, fill=INK)
    d.text((box.right - w - 24, base - 2), txt, font=f, fill=PAPER, anchor="ls")
