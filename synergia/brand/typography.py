"""Text layout: word wrapping, auto-fit sizing, **accent** markup, per-word sprites for animation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from synergia.brand.canvas import Box
from synergia.config import CFG, hex_to_rgb

TEXT = hex_to_rgb(CFG.brand.text)
ACCENT = hex_to_rgb(CFG.brand.accent)
ACCENT2 = hex_to_rgb(CFG.brand.accent2)
MUTED = hex_to_rgb(CFG.brand.muted)


@lru_cache(maxsize=256)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(getattr(CFG.fonts, weight), size)


Run = tuple[str, bool]  # (text, is_accent)


def smart_quotes(text: str) -> str:
    text = re.sub(r"(\w)'(\w)", "\\1\u2019\\2", text)
    text = re.sub(r"(^|\s)'", "\\1\u2018", text)
    text = text.replace("'", "\u2019")
    text = re.sub(r'(^|\s)"', "\\1\u201c", text)
    return text.replace('"', "\u201d")


def parse_markup(text: str) -> list[list[Run]]:
    """'You **overthink** it.' -> words as runs: [[('You',F)], [('overthink',T)], [('it.',F)]].

    Text glued to an accent span (e.g. '**you**.') stays in the same word as a separate run.
    """
    words: list[list[Run]] = []
    glue = False  # previous part ended without whitespace -> next part's first word glues on
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", smart_quotes(text.strip()))):
        if not part:
            continue
        accent = i % 2 == 1
        pieces = part.split()
        if glue and words and part[0].strip() and pieces:
            words[-1].append((pieces.pop(0), accent))
        words += [[(w, accent)] for w in pieces]
        glue = bool(part[-1].strip())
    return words


def strip_markup(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


@dataclass
class PlacedWord:
    runs: list[Run]
    x: int          # left
    y: int          # baseline
    line: int

    @property
    def text(self) -> str:
        return "".join(t for t, _ in self.runs)


@dataclass
class TextLayout:
    words: list[PlacedWord]
    size: int
    weight: str
    box: Box
    height: int     # total block height
    top: int        # y of block top
    color: tuple[int, int, int] = TEXT
    accent_color: tuple[int, int, int] = ACCENT
    _sprites: dict = field(default_factory=dict, repr=False)
    _edges: dict = field(default_factory=dict, repr=False)

    @property
    def font(self) -> ImageFont.FreeTypeFont:
        return font(self.weight, self.size)

    def sprite(self, i: int) -> tuple[Image.Image, int, int]:
        """RGBA sprite of word i and its top-left paste position."""
        if i not in self._sprites:
            w = self.words[i]
            f = self.font
            asc, desc = f.getmetrics()
            width = int(f.getlength(w.text)) + 8
            im = Image.new("RGBA", (width, asc + desc + 8), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            x = 4.0
            for text, acc in w.runs:
                col = self.accent_color if acc else self.color
                d.text((x, 4 + asc), text, font=f, fill=col + (255,), anchor="ls")
                x += f.getlength(text)
            self._sprites[i] = (im, w.x - 4, w.y - asc - 4)
        return self._sprites[i]

    def char_edges(self, i: int) -> list[int]:
        """x boundaries (sprite coords) of each character of word i: len(text) + 1 values."""
        if i not in self._edges:
            spr, _, _ = self.sprite(i)
            f = self.font
            edges, x0 = [0], 4.0
            for text, _ in self.words[i].runs:
                for k in range(1, len(text) + 1):
                    edges.append(max(edges[-1], int(round(x0 + f.getlength(text[:k])))))
                x0 += f.getlength(text)
            edges[-1] = spr.width
            self._edges[i] = edges
        return self._edges[i]

    def draw_typed(self, img: Image.Image, char_alphas: list[list[float]],
                   rise: float = 14.0) -> Image.Image:
        """Composite words letter by letter. char_alphas[i][c] is the eased 0..1 reveal of
        character c of word i; each letter fades in and settles up from `rise` px below.

        Letters are vertical slices of the word sprite, so a fully revealed word is
        pixel-identical to draw()."""
        base = img.convert("RGBA")
        for i, ca in enumerate(char_alphas):
            if not ca or ca[0] <= 0:
                continue
            spr, x, y = self.sprite(i)
            if ca[-1] >= 1:
                base.alpha_composite(spr, (x, y))
                continue
            edges = self.char_edges(i)
            done = 0                                   # leading fully-revealed letters
            while done < len(ca) and ca[done] >= 1:
                done += 1
            if done:
                base.alpha_composite(spr.crop((0, 0, edges[done], spr.height)), (x, y))
            for c in range(done, len(ca)):
                a = ca[c]
                if a <= 0:
                    break
                x0, x1 = edges[c], edges[c + 1]
                if x1 <= x0:
                    continue
                piece = spr.crop((x0, 0, x1, spr.height))
                piece.putalpha(piece.getchannel("A").point(lambda v, a=a: int(v * a)))
                base.alpha_composite(piece, (x + x0, y + int(round((1 - a) * rise))))
        return base.convert("RGB")

    def draw(self, img: Image.Image, alphas: list[float] | None = None,
             offsets: list[float] | None = None) -> Image.Image:
        """Composite words onto img (RGB or RGBA). alphas/offsets are per-word (0..1 / px)."""
        base = img.convert("RGBA")
        for i in range(len(self.words)):
            a = 1.0 if alphas is None else alphas[i]
            if a <= 0:
                continue
            spr, x, y = self.sprite(i)
            if a < 1:
                spr = spr.copy()
                spr.putalpha(spr.getchannel("A").point(lambda v, a=a: int(v * a)))
            dy = 0 if offsets is None else int(offsets[i])
            base.alpha_composite(spr, (x, y + dy))
        return base.convert("RGB")


def layout_text(text: str, box: Box, weight: str = "bold", max_size: int = 96,
                min_size: int = 34, align: str = "left", valign: str = "center",
                line_spacing: float | None = None, color=TEXT, accent_color=ACCENT,
                all_accent: bool = False) -> TextLayout:
    """Find the largest size in [min_size, max_size] at which the text fits the box."""
    tokens = parse_markup(text)
    if all_accent:
        tokens = [[(t, True) for t, _ in runs] for runs in tokens]
    ls = line_spacing or CFG.fonts.line_spacing
    size = max_size
    while True:
        f = font(weight, size)
        space = f.getlength(" ")
        lines: list[list[tuple[list[Run], float]]] = [[]]
        cur = 0.0
        for runs in tokens:
            wl = f.getlength("".join(t for t, _ in runs))
            add = wl if not lines[-1] else space + wl
            if lines[-1] and cur + add > box.w:
                lines.append([])
                cur, add = 0.0, wl
            lines[-1].append((runs, wl))
            cur += add
        line_h = int(size * ls)
        asc, _ = f.getmetrics()
        total_h = line_h * (len(lines) - 1) + int(size * 1.05)
        too_wide = any(wl > box.w for ln in lines for _, wl in ln)
        if (total_h <= box.h and not too_wide) or size <= min_size:
            break
        size -= 2

    if valign == "top":
        top = box.y
    elif valign == "bottom":
        top = box.bottom - total_h
    else:
        top = box.y + (box.h - total_h) // 2

    placed: list[PlacedWord] = []
    cap = int(size * 0.75)  # approx cap height; baseline offset from line top
    for li, ln in enumerate(lines):
        lw = sum(wl for _, wl in ln) + space * (len(ln) - 1)
        if align == "center":
            x = box.x + (box.w - lw) / 2
        elif align == "right":
            x = box.right - lw
        else:
            x = box.x
        baseline = top + li * line_h + cap
        for runs, wl in ln:
            placed.append(PlacedWord(runs, int(x), int(baseline), li))
            x += wl + space
    return TextLayout(placed, size, weight, box, total_h, top, color, accent_color)


def draw_label(img: Image.Image, text: str, x: int, y: int, size: int = 34,
               color=ACCENT, weight: str = "semibold", tracking: float = 0.18,
               anchor_center: bool = False) -> int:
    """Draw letter-spaced uppercase label; returns its width."""
    f = font(weight, size)
    text = text.upper()
    spacing = size * tracking
    total = sum(f.getlength(c) for c in text) + spacing * (len(text) - 1)
    cx = x - total / 2 if anchor_center else x
    d = ImageDraw.Draw(img)
    for c in text:
        d.text((cx, y), c, font=f, fill=color, anchor="ls")
        cx += f.getlength(c) + spacing
    return int(total)


def draw_gradient_text(img: Image.Image, xy: tuple[float, float], text: str,
                       f: ImageFont.FreeTypeFont, c1=ACCENT, c2=ACCENT2,
                       anchor: str = "ls") -> None:
    """Draw text filled with a left-to-right gradient c1 -> c2 (in place)."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=f, fill=255, anchor=anchor)
    bbox = mask.getbbox()
    if not bbox:
        return
    x0, y0, x1, y1 = bbox
    w = max(1, x1 - x0)
    grad = Image.new("RGB", (w, y1 - y0))
    gd = ImageDraw.Draw(grad)
    for x in range(w):
        t = x / (w - 1) if w > 1 else 0
        gd.line([(x, 0), (x, y1 - y0)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    img.paste(grad, (x0, y0), mask.crop(bbox))
