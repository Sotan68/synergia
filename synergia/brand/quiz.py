"""The look of Engines D and E: light "test sheet" slides in white, blue and purple.

`[quiz] style` in config.toml picks the surface:
- "sheet":  the textured paper of Engines A / B, with the slide's content on a white card
- "grid":   light graph paper, no card
- "cobalt": a saturated blue background with the content on a white card

Text is always navy on a light surface, one font family per slide ([fonts] quiz_*), and
**highlighted** words only change colour. The header ("02  Odd one out" over a hairline) and the
footer page count ("02 / 04") follow Engine A.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from synergia.brand import paper
from synergia.brand.canvas import BODY, CENTRE, Box, safe_for
from synergia.brand.elements import footer_name, logo
from synergia.brand.typography import font
from synergia.config import CFG, hex_to_rgb

K = CFG.quiz
STYLE = getattr(K, "style", "sheet")
BG = hex_to_rgb(K.surface)            # the card / sheet colour (also the tick inside checkboxes)
TEXT = hex_to_rgb(K.text)
MUTED = hex_to_rgb(K.muted)
ACCENT = hex_to_rgb(K.accent)
ACCENT2 = hex_to_rgb(K.accent2)
LINE = TEXT + (36,)
SURFACE_DARK = sum(BG) < 3 * 110          # a dark card (e.g. the Midnight theme)                   # hairlines

# Font roles (keys of [fonts] in config.toml): one family, four weights.
HEAVY, BOLD, SEMI, MED = "quiz_heavy", "quiz_bold", "quiz_semibold", "quiz_medium"

# The white card ("sheet" / "cobalt"): symmetric on screen and entirely inside the safe zone, so
# the app's buttons on the right (like, comment, share) never sit on it. INNER is the content
# column inside the card.
CARD = Box(CENTRE.x, BODY.y - 30, CENTRE.w, BODY.h + 50)
INNER = Box(CARD.x + 40, BODY.y, CARD.w - 80, BODY.h)
HEADER_Y = BODY.y + 52                # baseline of the header row
CONTENT_TOP = HEADER_Y + 60           # first free y under the header rule
AREA = Box(INNER.x, CONTENT_TOP, INNER.w, INNER.bottom - CONTENT_TOP)   # content under the header


# ---------------------------------------------------------------- backgrounds
def _card(img: Image.Image) -> Image.Image:
    """White rounded card with a soft shadow and a thin navy edge."""
    w, h = img.size
    c = CARD
    shadow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shadow).rounded_rectangle([c.x, c.y + 18, c.right, c.bottom + 18], radius=46,
                                             fill=70 if STYLE == "cobalt" else 38)
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    out = img.convert("RGBA")
    out.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (w, h), v) for v in (10, 12, 50)],
                                             shadow)))
    d = ImageDraw.Draw(out, "RGBA")
    edge = TEXT + ((60,) if SURFACE_DARK else (255,))     # crisp navy edge; soft on dark cards
    d.rounded_rectangle([c.x, c.y, c.right, c.bottom], radius=46, fill=BG + (255,),
                        outline=edge, width=2)
    return out.convert("RGB")


def _cobalt(seed: int, w: int, h: int, variant: int) -> Image.Image:
    rng = np.random.default_rng(seed * 104729 + variant)
    top, bot = np.array(hex_to_rgb(K.cobalt), np.float32), np.array(hex_to_rgb(K.cobalt2), np.float32)
    k = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    img = np.broadcast_to(top + (bot - top) * k, (h, w, 3)).copy()
    img += rng.normal(0, 255 * 0.014, (h, w)).astype(np.float32)[..., None]
    return _card(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB"))


@lru_cache(maxsize=16)
def _background(seed: int, w: int, h: int, variant: int) -> Image.Image:
    if STYLE == "grid":                     # graph paper, no card
        return paper.background(seed, w, h, variant, kind="grid")
    if STYLE == "cobalt":                   # coloured background + card
        return _cobalt(seed, w, h, variant)
    if STYLE == "plain":                    # the theme's background, no card
        return paper.background(seed, w, h, variant)
    return _card(paper.background(seed, w, h, variant))   # "sheet": card on the theme's background


def background(seed: int, width: int | None = None, height: int | None = None,
               variant: int = 0) -> Image.Image:
    return _background(seed, width or CFG.brand.width, height or CFG.brand.height, variant).copy()


# ---------------------------------------------------------------- chrome
def header(img: Image.Image, label: str, num: int | None = None, right: str | None = None) -> None:
    """'02  Odd one out' (or just a label) and an optional right-hand note, over a hairline."""
    d = ImageDraw.Draw(img, "RGBA")
    x0, x1, y = INNER.x, INNER.right, HEADER_Y
    f = font(SEMI, 34)
    x = x0
    if num is not None:
        d.text((x, y), f"{num:02d}", font=f, fill=ACCENT2, anchor="ls")
        x += f.getlength("00") + 22
    d.text((x, y), label, font=f, fill=TEXT, anchor="ls")
    if right:
        d.text((x1, y), right, font=font(MED, 32), fill=MUTED, anchor="rs")
    d.line([(x0, y + 28), (x1, y + 28)], fill=LINE, width=2)


def footer(img: Image.Image, page: int | None = None, total: int | None = None) -> None:
    """Logo mark + "Synergia" on the left, "02 / 06" on the right, under the card."""
    base = safe_for(img.height).bottom - 4
    if STYLE == "cobalt":                   # under the card, on the blue
        col, soft = (255, 255, 255), (214, 220, 255)
    elif paper.DARK:                        # on a dark sheet
        col, soft = paper.INK, paper.SOFT
    else:
        col, soft = TEXT, MUTED
    d = ImageDraw.Draw(img)
    f = font(SEMI, 30)
    mark = logo(30)
    x = INNER.x
    img.paste(mark, (x, base - 11 - mark.height // 2), mark)
    d.text((x + mark.width + 14, base), footer_name(), font=f, fill=col, anchor="ls")
    if page is not None:
        d.text((INNER.right, base), f"{page:02d} / {total:02d}", font=font(MED, 28), fill=soft,
               anchor="rs")


def score_line(img: Image.Image, total: int, y: int, label: str = "Your score") -> int:
    """'Your score' over a blank to fill in and '/ 4', across the text column. Returns its height."""
    d = ImageDraw.Draw(img, "RGBA")
    d.text((INNER.x, y), label, font=font(SEMI, 34), fill=MUTED, anchor="ls")
    f = font(HEAVY, 96)
    tail = f"/ {total}"
    base = y + 120
    d.text((INNER.right, base), tail, font=f, fill=ACCENT2, anchor="rs")
    d.line([(INNER.x, base), (INNER.right - f.getlength(tail) - 28, base)], fill=TEXT + (200,), width=4)
    return 130


def title_sheet(img: Image.Image, head: str, big: str, small: str, total: int | None = None,
                right: str | None = None, page: int | None = None, pages: int | None = None,
                big_max: int = 112, big_min: int = 60):
    """Cover / ending: header, big left-aligned line, muted small line and, with `total`, a
    'Your score ___ / 4' line at the bottom. Draws the static parts onto img; returns the big and
    small layouts for typing."""
    from synergia.brand.typography import layout_text

    header(img, head, right=right)
    footer(img, page, pages)
    big_l = layout_text(big, Box(INNER.x, 0, INNER.w, 520), weight=HEAVY, max_size=big_max,
                        min_size=big_min, valign="top", line_spacing=1.06, color=TEXT,
                        accent_color=ACCENT)
    small_l = layout_text(small, Box(INNER.x, 0, INNER.w, 160), weight=MED, max_size=46,
                          min_size=34, valign="top", line_spacing=1.25, color=MUTED,
                          accent_color=ACCENT)
    bottom = INNER.bottom - (200 if total else 0)
    block = big_l.height + 44 + small_l.height
    top = CONTENT_TOP + max(0, (bottom - CONTENT_TOP - block) // 2 - 20)
    big_l = big_l.moved(dy=top)
    small_l = small_l.moved(dy=big_l.top + big_l.height + 44)
    if total:
        score_line(img, total, INNER.bottom - 150)
    return big_l, small_l


def label(img: Image.Image, text: str, y: int, cx: int | None = None, size: int = 34,
          color=None, weight: str = SEMI, alpha: float = 1.0) -> None:
    """A small sentence-case label centred on cx (default: the screen centre), baseline at y."""
    cx = img.width // 2 if cx is None else cx
    color = MUTED if color is None else color
    d = ImageDraw.Draw(img, "RGBA" if img.mode == "RGBA" else None)
    fill = tuple(color) + (int(255 * alpha),) if img.mode == "RGBA" else tuple(color)
    d.text((cx, y), text, font=font(weight, size), fill=fill, anchor="ms")
