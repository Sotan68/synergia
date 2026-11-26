"""The slide look for Engines A and B, driven by the theme (synergia/brand/themes.py).

[paper]  colours and texture; [layout] background kind (paper / grid / gradient / flat),
alignment (left / center), how **highlighted** words look (italic / color / marker / underline)
and the section-header style (rule / pill / plain); [fonts] headline, text, paragraph, numeral.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from synergia.brand.canvas import safe_for
from synergia.brand.elements import footer_name, logo
from synergia.brand.typography import font
from synergia.config import CFG, hex_to_rgb

P = CFG.paper
L = CFG.layout
PAPER = hex_to_rgb(P.background)
PAPER2 = hex_to_rgb(getattr(P, "background2", P.background))
INK = hex_to_rgb(P.ink)
SOFT = hex_to_rgb(P.soft)
ACCENT = hex_to_rgb(P.accent)
ACCENT2 = hex_to_rgb(P.accent2)
ALIGN = getattr(L, "align", "left")            # "left" or "center"
CENTRED = ALIGN == "center"
DARK = sum(PAPER) < 3 * 110                    # light text on a dark sheet

# Font roles (keys of [fonts], set by the theme).
SERIF, SERIF_I = "serif", "serif_italic"       # headlines (not always a serif) / italic highlight
TEXT_W, STRONG_W = "display_medium", "display_semibold"
PARA_W = "paragraph"      # Engine A's paragraph slides: one font for the header and the text
NUM_W = "numeral"         # Engine B's big point numbers
SERIF_IN_SANS = 1.18      # serif italic accent inside Inter text: scale to match the x-height


def highlight(where: str) -> dict:
    """layout_text keyword arguments for **highlighted** words, in the theme's style.

    where: "headline" (serif headlines), "text" (sans text next to them) or "paragraph" (Engine A's
    one-font slides: never a second font, so italic falls back to colour)."""
    kw = {"color": INK, "accent_color": ACCENT}
    style = getattr(L, "highlight", "italic")
    if style == "italic" and where != "paragraph":
        kw["accent_weight"] = SERIF_I
        if where == "text":
            kw["accent_scale"] = SERIF_IN_SANS
    elif style == "marker":
        kw["marker"] = hex_to_rgb(getattr(L, "marker", P.accent))
        kw["accent_color"] = hex_to_rgb(getattr(L, "marker_ink", P.ink))
    elif style == "underline":
        kw["underline"], kw["accent_color"] = ACCENT, INK
    return kw


# ---------------------------------------------------------------- background
def _smooth_noise(rng: np.random.Generator, w: int, h: int, cells: int) -> np.ndarray:
    """Soft cloudy noise in [-1, 1]: a coarse random grid upscaled with bicubic smoothing."""
    gw, gh = cells, max(2, round(cells * h / w))
    small = rng.uniform(0, 255, (gh, gw)).astype(np.uint8)
    big = Image.fromarray(small, "L").resize((w, h), Image.BICUBIC)
    return np.asarray(big, dtype=np.float32) / 127.5 - 1.0


def _grain(rng: np.random.Generator, w: int, h: int, strength: float) -> np.ndarray:
    """Monochrome tooth, slightly blue-tinted; half of it 2-3 px clumps so it survives video."""
    fine = rng.normal(0, 1, (h, w)).astype(np.float32)
    small = rng.normal(0, 1, (h // 2, w // 2)).astype(np.float32)
    coarse = np.asarray(Image.fromarray(small, "F").resize((w, h), Image.BILINEAR)) * 1.6
    g = (0.6 * fine + 0.55 * coarse) * 255 * strength
    return g[..., None] * np.array([0.95, 0.95, 1.0], np.float32)


def grid_lines(img: Image.Image, color, cell: int = 44) -> Image.Image:
    """Graph paper: fine lines every `cell` px, a bolder one every 5; a line runs down the centre."""
    w, h = img.size
    out = img.convert("RGBA")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0 = (w // 2) % cell
    for x in range(x0 - cell * ((x0 // cell) + 1), w, cell):
        major = (x - w // 2) % (cell * 5) == 0
        d.line([(x, 0), (x, h)], fill=tuple(color) + (46 if major else 22,), width=2 if major else 1)
    for y in range(0, h, cell):
        major = (y // cell) % 5 == 0
        d.line([(0, y), (w, y)], fill=tuple(color) + (46 if major else 22,), width=2 if major else 1)
    out.alpha_composite(layer)
    return out.convert("RGB")


def _plain(seed: int, w: int, h: int, variant: int, gradient: bool) -> Image.Image:
    """Flat colour, or a top-to-bottom blend into background2, with an optional light grain."""
    rng = np.random.default_rng(seed * 7919 + variant)
    k = (np.linspace(0, 1, h, dtype=np.float32)[:, None, None] ** 1.2) if gradient else 0.0
    a, b = np.array(PAPER, np.float32), np.array(PAPER2, np.float32)
    img = np.broadcast_to(a + (b - a) * k, (h, w, 3)).astype(np.float32).copy()
    if P.grain > 0:
        img += _grain(rng, w, h, P.grain)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


# Notebook paper: ruled lines every NB_RULE px from NB_TOP, a red margin line at NB_MARGIN.
NB_RULE, NB_TOP, NB_MARGIN = 80, 300, 150


def notebook_lines(img: Image.Image) -> Image.Image:
    w, h = img.size
    out = img.convert("RGBA")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(NB_TOP, h - 120, NB_RULE):
        d.line([(0, y), (w, y)], fill=(120, 165, 225, 70), width=2)
    d.line([(NB_MARGIN, 0), (NB_MARGIN, h)], fill=(232, 96, 96, 120), width=3)
    for cy in (h * 0.22, h * 0.5, h * 0.78):          # punched holes
        d.ellipse([38, cy - 22, 82, cy + 22], fill=(0, 0, 0, 0), outline=(0, 0, 0, 40), width=2)
        d.ellipse([40, cy - 20, 80, cy + 20], fill=(222, 224, 232, 255))
    out.alpha_composite(layer)
    return out.convert("RGB")


@lru_cache(maxsize=16)
def _background(seed: int, w: int, h: int, variant: int, kind: str = "paper") -> Image.Image:
    if kind in ("flat", "gradient"):
        return _plain(seed, w, h, variant, kind == "gradient")
    if kind == "notebook":
        return notebook_lines(_background(seed, w, h, variant, "paper"))
    if kind == "scanlines":                     # a CRT screen: faint horizontal lines
        out = _plain(seed, w, h, variant, False).convert("RGBA")
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for y in range(0, h, 4):
            d.line([(0, y), (w, y)], fill=(0, 0, 0, 70), width=1)
        out.alpha_composite(layer)
        return out.convert("RGB")
    if kind == "halftone":                      # comic-print dots fading in from two corners
        out = _plain(seed, w, h, variant, False).convert("RGBA")
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        step = 34
        corner = (w, 0) if variant % 2 == 0 else (0, 0)
        for y in range(0, h, step):
            for x in range(0, w, step):
                for cx, cy in (corner, (w - corner[0], h)):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / 700
                    r = max(0.0, 9 * (1 - dist))
                    if r > 0.6:
                        ox = step / 2 if (y // step) % 2 else 0
                        d.ellipse([x + ox - r, y - r, x + ox + r, y + r], fill=ACCENT2 + (90,))
        out.alpha_composite(layer)
        return out.convert("RGB")
    if kind == "grid":
        return grid_lines(_background(seed, w, h, variant, "paper"), ACCENT)
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
        img += _grain(rng, w, h, P.grain)

    # Fibres / specks: a few tiny darker flecks, like recycled stock.
    n_specks = int(w * h / 9000)
    xs, ys = rng.integers(0, w, n_specks), rng.integers(0, h, n_specks)
    depth = rng.uniform(6, 22, n_specks).astype(np.float32)
    img[ys, xs] -= depth[:, None]

    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def background(seed: int, width: int | None = None, height: int | None = None,
               variant: int = 0, kind: str | None = None) -> Image.Image:
    """The slide background in the theme's kind (paper / grid / gradient / flat). `seed` fixes the
    look of a post, `variant` varies each slide."""
    return _background(seed, width or CFG.brand.width, height or CFG.brand.height, variant,
                       kind or getattr(L, "bg", "paper")).copy()


# ---------------------------------------------------------------- chrome
FOOT_SIZE = 30


def footer_baseline(img: Image.Image) -> int:
    return safe_for(img.height).bottom - 14


def footer(img: Image.Image, page: int | None = None, total: int | None = None,
           align: str = "left", ink=None, soft=None, show_page: bool = True) -> None:
    """Logo mark + the brand name (left or centred) and an optional "02 / 06" page count on the
    right. ink / soft: colours for a footer that sits on a coloured block."""
    ink, soft = ink or INK, soft or SOFT
    box = safe_for(img.height)
    base = footer_baseline(img)
    d = ImageDraw.Draw(img)
    f = font(STRONG_W, FOOT_SIZE)
    mark = logo(30)
    name = footer_name()
    mw = mark.width + 14 if mark else 0        # no logo: just the name
    total_w = mw + f.getlength(name)
    x = box.x if align == "left" else round(img.width / 2 - total_w / 2)
    if mark:
        img.paste(mark, (x, base - 11 - mark.height // 2), mark)
    d.text((x + mw, base), name, font=f, fill=ink, anchor="ls")
    if page is not None and align == "left" and show_page:
        d.text((box.right, base), f"{page:02d} / {total:02d}", font=font(TEXT_W, 28), fill=soft,
               anchor="rs")


def section_header(img: Image.Image, num: int, label: str, y: int | None = None,
                   face: str | None = None, size: int = 32) -> int:
    """'02  The mirror' in the theme's style: over a hairline ("rule"), inside an outlined pill
    ("pill") or on its own ("plain"); left-aligned or centred. Returns the y below it.

    face: one font for both the number and the label (default: the theme's text font)."""
    box = safe_for(img.height)
    y = box.y + 80 if y is None else y
    d = ImageDraw.Draw(img, "RGBA")
    nf, lf = (font(face, size), font(face, size)) if face else (font(STRONG_W, size),
                                                                font(TEXT_W, size))
    style = getattr(L, "header", "rule")
    gap = 22
    w = nf.getlength(f"{num:02d}") + gap + lf.getlength(label)
    pad = 30 if style == "pill" else 0
    x = round(img.width / 2 - w / 2) if CENTRED else box.x + pad
    if style == "pill":
        d.rounded_rectangle([x - pad, y - size - 12, x + w + pad, y + 20], radius=size,
                            outline=INK + (150,), width=3)
    d.text((x, y), f"{num:02d}", font=nf, fill=ACCENT2, anchor="ls")
    d.text((x + nf.getlength(f"{num:02d}") + gap, y), label, font=lf, fill=INK, anchor="ls")
    rule = y + 30
    if style == "rule":
        d.line([(box.x, rule), (box.right, rule)], fill=INK + (34,), width=2)
    return rule


def has_glyph(f, ch: str) -> bool:
    """True if the font really has `ch` (not the empty box it draws for missing characters)."""
    missing = f.getmask("\U0010FFFD")
    got = f.getmask(ch)
    return got.size != missing.size or bytes(got) != bytes(missing)


def arrow(draw: ImageDraw.ImageDraw, x: float, y: float, size: int, fill) -> float:
    """A drawn → for fonts without the character; (x, y) = left end on the baseline-ish middle.
    Returns its width."""
    w = size * 0.9
    t = max(2, round(size * 0.09))
    draw.line([(x, y), (x + w, y)], fill=fill, width=t)
    draw.line([(x + w - size * 0.32, y - size * 0.3), (x + w, y)], fill=fill, width=t)
    draw.line([(x + w - size * 0.32, y + size * 0.3), (x + w, y)], fill=fill, width=t)
    return w


def swipe_pill(img: Image.Image) -> None:
    """Navy 'Swipe →' pill on the right of the footer row (carousel covers)."""
    box = safe_for(img.height)
    base = footer_baseline(img)
    f = font(STRONG_W, 30)
    d = ImageDraw.Draw(img)
    if has_glyph(f, "→"):
        txt = "Swipe  →"
        w = f.getlength(txt)
        d.rounded_rectangle([box.right - w - 48, base - 42, box.right, base + 16], radius=29, fill=INK)
        d.text((box.right - w - 24, base - 2), txt, font=f, fill=PAPER, anchor="ls")
        return
    txt = "Swipe"
    w = f.getlength(txt) + 16 + 30 * 0.9
    d.rounded_rectangle([box.right - w - 48, base - 42, box.right, base + 16], radius=29, fill=INK)
    d.text((box.right - w - 24, base - 2), txt, font=f, fill=PAPER, anchor="ls")
    arrow(d, box.right - 24 - 30 * 0.9, base - 12, 30, PAPER)
