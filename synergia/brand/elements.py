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


# ---------------------------------------------------------------- animated pieces (D / E)
SS = 4   # supersampling factor for smooth arcs and strokes


def _rgba(col, alpha: float = 1.0) -> tuple[int, int, int, int]:
    return tuple(col[:3]) + (int(255 * max(0.0, min(1.0, alpha))),)


def _patch(img: Image.Image, x0: int, y0: int, w: int, h: int, draw_fn) -> Image.Image:
    """Run draw_fn(ImageDraw, scale) on a supersampled transparent patch and composite it.

    An RGBA img is drawn on in place (and returned); an RGB img is left untouched and a new
    RGB image is returned."""
    layer = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer), SS)
    layer = layer.resize((w, h), Image.LANCZOS)
    if img.mode == "RGBA":
        img.alpha_composite(layer, (x0, y0))
        return img
    out = img.convert("RGBA")
    out.alpha_composite(layer, (x0, y0))
    return out.convert("RGB")


def draw_timer(img: Image.Image, cx: int, cy: int, r: int, frac: float, secs_left: int,
               alpha: float = 1.0) -> Image.Image:
    """Countdown ring: a track plus an accent arc covering `frac` (1 -> 0) and the seconds left."""
    from synergia.brand.typography import ACCENT, MUTED, TEXT, font

    width = max(6, r // 6)
    pad = width + 4
    size = 2 * (r + pad)

    def draw(d: ImageDraw.ImageDraw, s: int) -> None:
        box = [pad * s, pad * s, (pad + 2 * r) * s, (pad + 2 * r) * s]
        d.ellipse(box, outline=_rgba(MUTED, 0.28 * alpha), width=width * s)
        if frac > 0:
            col = ACCENT if frac > 0.34 else MARK_PURPLE
            d.arc(box, -90, -90 + 360 * frac, fill=_rgba(col, alpha), width=width * s)
        f = font("black", int(r * 0.95) * s)
        d.text((size * s / 2, size * s / 2), str(secs_left), font=f, fill=_rgba(TEXT, alpha),
               anchor="mm")

    return _patch(img, cx - size // 2, cy - size // 2, size, size, draw)


def draw_ring(img: Image.Image, cx: int, cy: int, r: int, progress: float,
              color=None, width: int = 9) -> Image.Image:
    """'Found it' circle that draws itself in clockwise (progress 0..1)."""
    if progress <= 0:
        return img
    from synergia.brand.typography import ACCENT
    col = color or ACCENT
    pad = width + 4
    size = 2 * (r + pad)

    def draw(d: ImageDraw.ImageDraw, s: int) -> None:
        box = [pad * s, pad * s, (pad + 2 * r) * s, (pad + 2 * r) * s]
        d.arc(box, -120, -120 + 360 * min(1.0, progress), fill=_rgba(col), width=width * s)

    return _patch(img, cx - size // 2, cy - size // 2, size, size, draw)


def draw_check(img: Image.Image, x: int, y: int, size: int, progress: float,
               alpha: float = 1.0) -> Image.Image:
    """Checkbox at (x, y) top-left; progress 0 = empty box, 1 = filled with a full tick."""
    from synergia.brand.typography import ACCENT, BG_DARK, MUTED

    p = max(0.0, min(1.0, progress))
    pad = 4

    def draw(d: ImageDraw.ImageDraw, s: int) -> None:
        box = [pad * s, pad * s, (pad + size) * s, (pad + size) * s]
        rad = size * 0.24 * s
        fill = _rgba(ACCENT, alpha * min(1.0, p * 2.5)) if p > 0 else None
        d.rounded_rectangle(box, rad, fill=fill,
                            outline=_rgba(ACCENT if p > 0 else MUTED, alpha), width=max(3, size // 14) * s)
        if p > 0.15:   # the tick draws along its two strokes
            q = (p - 0.15) / 0.85
            pts = [(0.26, 0.53), (0.44, 0.71), (0.77, 0.32)]
            pts = [((pad + size * a) * s, (pad + size * b) * s) for a, b in pts]
            l1 = ((pts[1][0] - pts[0][0]) ** 2 + (pts[1][1] - pts[0][1]) ** 2) ** 0.5
            l2 = ((pts[2][0] - pts[1][0]) ** 2 + (pts[2][1] - pts[1][1]) ** 2) ** 0.5
            reach = q * (l1 + l2)
            line = [pts[0]]
            if reach <= l1:
                k = reach / l1
                line.append((pts[0][0] + (pts[1][0] - pts[0][0]) * k, pts[0][1] + (pts[1][1] - pts[0][1]) * k))
            else:
                k = (reach - l1) / l2
                line += [pts[1], (pts[1][0] + (pts[2][0] - pts[1][0]) * k, pts[1][1] + (pts[2][1] - pts[1][1]) * k)]
            d.line(line, fill=_rgba(BG_DARK, alpha), width=max(4, size // 8) * s, joint="curve")

    return _patch(img, x - pad, y - pad, size + 2 * pad, size + 2 * pad, draw)
