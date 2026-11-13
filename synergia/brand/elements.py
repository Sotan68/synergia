"""Shared brand elements (logo mark, wordmark lockup)."""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

from synergia.brand.canvas import safe_for
from synergia.brand.typography import ACCENT2, draw_label, font
from synergia.config import hex_to_rgb, CFG

# Colours sampled from "logo ideas/05 · Overlap, mark only".
MARK_BLUE = hex_to_rgb("#5B9CFF")
MARK_PURPLE = hex_to_rgb("#A78BFA")

WORDMARK_SIZE = 30
WORDMARK_TRACKING = 0.45


@lru_cache(maxsize=8)
def logo_mark(height: int) -> Image.Image:
    """The Overlap mark (two rings + gradient lens) as a transparent RGBA sprite.

    Drawn procedurally at 4x and downsampled, so it stays crisp at any size.
    Proportions match the logo file: ring radius R, centres 1.0R apart, stroke ~0.105R.
    """
    ss = 4
    R = height * ss / 2.105           # ring centre-line radius
    sw = max(2, round(0.105 * R))     # stroke width
    pad = sw / 2
    w, h = int(3 * R + 2 * pad) + 2, int(2 * R + 2 * pad) + 2
    cy = h / 2
    c1, c2 = pad + R + 1, pad + 2 * R + 1

    def disc(cx: float, r: float) -> Image.Image:
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        return m

    def ring(cx: float, col) -> Image.Image:
        layer = Image.new("RGBA", (w, h), col + (0,))
        outer, inner = disc(cx, R + sw / 2), disc(cx, R - sw / 2)
        mask = Image.composite(Image.new("L", (w, h), 0), outer, inner)
        layer.putalpha(mask)
        return layer

    # Lens = intersection of the two discs, filled with a blue -> purple gradient.
    lens_mask = Image.composite(disc(c1, R), Image.new("L", (w, h), 0), disc(c2, R))
    x0, x1 = int(c2 - R), int(c1 + R)
    grad = Image.new("RGBA", (w, h), MARK_BLUE + (0,))
    gd = ImageDraw.Draw(grad)
    for x in range(x0, x1 + 1):
        t = (x - x0) / max(1, x1 - x0)
        gd.line([(x, 0), (x, h)], fill=tuple(int(a + (b - a) * t)
                                             for a, b in zip(MARK_BLUE, MARK_PURPLE)) + (255,))
    grad.putalpha(lens_mask)

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(grad)
    out.alpha_composite(ring(c1, MARK_BLUE))
    out.alpha_composite(ring(c2, MARK_PURPLE))
    return out.resize((round(w / ss), round(h / ss)), Image.LANCZOS)


def footer_baseline(img: Image.Image) -> int:
    """Baseline of the footer row (wordmark, swipe cue) at the bottom of the safe zone."""
    return safe_for(img.height).bottom - 6


def draw_wordmark(img: Image.Image, align: str = "left") -> None:
    """Logo mark + letter-spaced SYNERGIA as a footer at the bottom of the safe zone.

    align="left" lines it up with the left edge of the text column; "center" for centred slides.
    """
    box = safe_for(img.height)
    baseline = footer_baseline(img)
    mark = logo_mark(34)
    f = font("semibold", WORDMARK_SIZE)
    name = CFG.brand.name.upper()
    text_w = sum(f.getlength(c) for c in name) + WORDMARK_SIZE * WORDMARK_TRACKING * (len(name) - 1)
    gap = 18
    total = mark.width + gap + text_w
    # The mark sprite has ~1px of transparent padding; nudge so the ring touches the text edge.
    x = box.x - 1 if align == "left" else round(box.cx - total / 2)
    cap_mid = baseline - round(WORDMARK_SIZE * 0.36)   # optical middle of the capitals
    img.paste(mark, (x, cap_mid - mark.height // 2), mark)
    draw_label(img, name, x + mark.width + gap, baseline, size=WORDMARK_SIZE, color=ACCENT2,
               weight="semibold", tracking=WORDMARK_TRACKING)
