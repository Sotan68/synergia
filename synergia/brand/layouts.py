"""Slide blueprints for Engines A and B: each theme composes its slides differently.

- editorial  (Synergia)  the original layout, kept in engines/psychology.py and listicle.py
- notebook   (Notebook)  ruled paper with a red margin; text sits on the lines, a sticky note,
                         numbers in hand-drawn circles
- poster     (Cobalt)    a big colour block holding giant headlines / numbers, text below it
- cinematic  (Midnight)  a thin frame, a huge faint watermark number, text anchored low
- cards      (Sunset)    content on a floating card with a sticker label or a number badge
- swiss      (Minimal)   asymmetric grid: giant numeral top-left, red bar, page count top-right,
                         text anchored bottom-left

Each blueprint draws the static parts onto the slide background and returns the text layouts that
get typed out. Colours, fonts and the highlight style still come from the theme (synergia.brand.paper).
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from synergia.brand import paper as P
from synergia.brand.animate import Step
from synergia.brand.canvas import Box, safe_for
from synergia.brand.typography import TextLayout, font, layout_text
from synergia.config import CFG, hex_to_rgb

L = CFG.layout
BLUEPRINT = getattr(L, "blueprint", "editorial")
W, H = CFG.brand.width, CFG.brand.height
SAFE = safe_for(H)
FOOT = SAFE.bottom - 110          # content stays above this (footer row below)


def _c(key: str, default: str):
    return hex_to_rgb(getattr(L, key, default))


# ---------------------------------------------------------------- helpers
def text(t: str, x: int, w: int, weight: str, size: int, min_size: int, where: str = "text", *,
         align: str = "left", ls: float = 1.12, maxh: int = 1100, color=None, accent=None,
         ) -> TextLayout:
    """A text block at y = 0 (move it into place with put / stack) in the theme's highlight style."""
    kw = P.highlight(where)
    if color is not None:
        kw["color"] = color
    if accent is not None and "marker" not in kw and "underline" not in kw:
        kw["accent_color"] = accent
    return layout_text(t, Box(x, 0, w, maxh), weight=weight, max_size=size, min_size=min_size,
                       align=align, valign="top", line_spacing=ls, **kw)


def put(lay: TextLayout, top: int) -> TextLayout:
    return lay.moved(dy=top - lay.top)


def lines(lay: TextLayout) -> int:
    return max((w.line for w in lay.words), default=0) + 1


def stack(items: list[tuple[TextLayout, int]], top: int) -> list[TextLayout]:
    """Place blocks one under the other; each item is (layout, gap after it)."""
    out, y = [], top
    for lay, gap in items:
        m = put(lay, y)
        out.append(m)
        y = m.top + m.height + gap
    return out


def total(items: list[tuple[TextLayout, int]]) -> int:
    return sum(l.height for l, _ in items) + sum(g for _, g in items[:-1])


def label(img: Image.Image, s: str, xy, size: int = 34, color=None, weight: str = P.STRONG_W,
          anchor: str = "ls") -> None:
    ImageDraw.Draw(img, "RGBA").text(xy, s, font=font(weight, size),
                                     fill=tuple(color or P.ACCENT2), anchor=anchor)


def card(img: Image.Image, box: Box, fill, radius: int = 48, shadow: int = 42) -> Image.Image:
    """A rounded card with a soft drop shadow."""
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([box.x, box.y + 22, box.right, box.bottom + 22], radius,
                                        fill=shadow)
    m = m.filter(ImageFilter.GaussianBlur(30))
    out = img.convert("RGBA")
    out.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (w, h), v) for v in (40, 20, 10)], m)))
    ImageDraw.Draw(out).rounded_rectangle([box.x, box.y, box.right, box.bottom], radius,
                                          fill=tuple(fill) + (255,))
    return out.convert("RGB")


def pill(img: Image.Image, s: str, cx: int, cy: int, bg, fg, size: int = 34) -> None:
    f = font(P.STRONG_W, size)
    w = f.getlength(s)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([cx - w / 2 - 34, cy - size * 0.95, cx + w / 2 + 34, cy + size * 0.95],
                        radius=size, fill=tuple(bg))
    d.text((cx, cy + 2), s, font=f, fill=tuple(fg), anchor="mm")


# ================================================================ notebook
class Notebook:
    """Ruled notebook paper: every text baseline sits on a rule."""
    X = P.NB_MARGIN + 36
    WCOL = SAFE.right - X

    @staticmethod
    def rule(k: int) -> int:
        return P.NB_TOP + k * P.NB_RULE

    def on_rules(self, lay: TextLayout, first_rule: int) -> TextLayout:
        """Move a block so its first baseline sits on rule `first_rule`."""
        first_baseline = min(w.y for w in lay.words) if lay.words else lay.top
        return lay.moved(dy=self.rule(first_rule) - first_baseline)

    def ruled(self, t, weight, size, min_size, where="text", rules_per_line: int = 1, **kw):
        """Text whose line spacing is a whole number of rules."""
        lay = None
        for s in range(size, min_size - 1, -2):
            lay = text(t, self.X, self.WCOL, weight, s, s, where, ls=P.NB_RULE * rules_per_line / s, **kw)
            if lay.height < 900:
                break
        return lay

    def next_rule(self, lay: TextLayout, gap_rules: int = 1) -> int:
        last = max((w.y for w in lay.words), default=lay.top)
        return (last - P.NB_TOP) // P.NB_RULE + 1 + gap_rules

    @staticmethod
    def sticky(img: Image.Image, s: str, x: int, y: int, size: int = 250, angle: float = -6) -> None:
        note = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(note)
        d.rectangle([24, 28, size + 24, size + 28], fill=(0, 0, 0, 40))        # shadow
        d.rectangle([20, 20, size + 20, size + 20], fill=_c("marker", "#FFE27A") + (255,))
        lay = text(s, 20 + 28, size - 56, P.STRONG_W, 40, 26, "text", align="center", ls=1.15,
                   color=P.INK, maxh=size - 60)
        lay = put(lay, 20 + (size - lay.height) // 2)
        note = lay.draw(note).convert("RGBA")
        note = note.rotate(angle, resample=Image.BICUBIC, expand=True)
        img.paste(note, (x, y), note)

    @staticmethod
    def circle(img: Image.Image, cx: int, cy: int, r: int, num: str) -> None:
        d = ImageDraw.Draw(img, "RGBA")
        for dx, dy, rr in ((0, 0, r), (3, -2, r + 4)):                    # two loose strokes
            d.ellipse([cx - rr + dx, cy - rr + dy, cx + rr + dx, cy + rr + dy],
                      outline=P.ACCENT + (220,), width=5)
        d.text((cx, cy + 4), num, font=font(P.NUM_W, int(r * 1.1)), fill=P.ACCENT, anchor="mm")

    def a_hook(self, img, data):
        title = self.ruled(data["concept"], P.SERIF, 112, 70, "headline", rules_per_line=2)
        title = self.on_rules(title, 5)
        hook = self.on_rules(self.ruled(data["hook_line"], P.STRONG_W, 58, 44), self.next_rule(title, 1))
        self.sticky(img, CFG.engine_a.wording.intro_label, 660, 250)
        P.footer(img, 1, 4)
        return img, [title, hook]

    def a_para(self, img, num, name, body):
        f = font(P.STRONG_W, 36)
        tab = f"{num:02d}  {name}"
        d = ImageDraw.Draw(img)
        y = self.rule(1)
        d.rectangle([self.X - 14, y - 46, self.X + f.getlength(tab) + 14, y + 8],
                    fill=_c("marker", "#FFE27A"))
        d.text((self.X, y - 4), tab, font=f, fill=P.INK, anchor="ls")
        para = self.on_rules(self.ruled(body, P.PARA_W, 58, 44, "paragraph"), 3)
        P.footer(img, num, 4)
        return img, [para]

    def a_shift(self, img, body):
        lay = self.ruled(body, P.SERIF, 90, 60, "headline", rules_per_line=2)
        n = lines(lay)
        first = max(3, (12 - 2 * n) // 2 + 2)
        lay = self.on_rules(lay, first)
        d = ImageDraw.Draw(img, "RGBA")
        top, bot = lay.top - 40, max((w.y for w in lay.words), default=lay.top) + 50
        for dx, dy in ((0, 0), (5, -4)):                                    # sketchy box
            d.rectangle([self.X - 30 + dx, top + dy, SAFE.right + 6 + dx, bot + dy],
                        outline=P.INK + (150,), width=3)
        P.footer(img, 4, 4)
        return img, [lay]

    def b_cover(self, img, data, swipe):
        title = self.on_rules(self.ruled(data["cover_title"], P.SERIF, 112, 64, "headline",
                                         rules_per_line=2), 3)
        lays = [title]
        if data.get("cover_subtitle"):
            lays.append(self.on_rules(self.ruled(data["cover_subtitle"], P.TEXT_W, 54, 40,
                                                 color=P.SOFT), self.next_rule(title, 1)))
        P.footer(img)
        if swipe:
            P.swipe_pill(img)
        return img, lays

    def b_point(self, img, i, p, page, pages):
        self.circle(img, self.X + 70, self.rule(0) + 10, 74, str(i))
        title = self.on_rules(self.ruled(p["title"], P.SERIF, 90, 60, "headline", rules_per_line=2), 3)
        body = self.on_rules(self.ruled(p["body"], P.TEXT_W, 54, 40, color=P.SOFT), self.next_rule(title, 1))
        P.footer(img, page, pages)
        return img, [title, body]


# ================================================================ poster
class Poster:
    """A big colour block holding the headline or number; text below it on the light sheet."""
    ON = _c("on_block", "#FFFFFF")
    BLOCK_ACCENT = _c("block_accent", "#CFC4FF")

    @staticmethod
    def block(img: Image.Image, bottom: int) -> Image.Image:
        a, b = _c("block", "#2A45F2"), _c("block2", "#4A2FD6")
        d = ImageDraw.Draw(img)
        for y in range(0, bottom):
            k = y / max(1, bottom)
            d.line([(0, y), (W, y)], fill=tuple(int(p + (q - p) * k) for p, q in zip(a, b)))
        return img

    def a_hook(self, img, data):
        split = 1110
        self.block(img, split)
        label(img, CFG.engine_a.wording.intro_label, (SAFE.x, SAFE.y + 90), 38, self.BLOCK_ACCENT)
        concept = text(data["concept"], SAFE.x, SAFE.w, P.SERIF, 172, 80, "headline", ls=0.98,
                       color=self.ON, maxh=640)
        concept = put(concept, split - 80 - concept.height)
        hook = put(text(data["hook_line"], SAFE.x, SAFE.w, P.STRONG_W, 64, 44, maxh=260), split + 90)
        P.footer(img, 1, 4)
        return img, [concept, hook]

    def a_para(self, img, num, name, body):
        split = 690
        self.block(img, split)
        label(img, f"{num:02d}", (SAFE.x - 8, split - 150), 250, self.ON, P.NUM_W)
        label(img, name, (SAFE.x, split - 70), 40, self.BLOCK_ACCENT)
        para = text(body, SAFE.x, SAFE.w, P.PARA_W, 68, 44, "paragraph", ls=1.24,
                    maxh=FOOT - split - 120)
        P.footer(img, num, 4)
        return img, [put(para, split + 90)]

    def a_shift(self, img, body):
        self.block(img, H)
        lay = text(body, SAFE.x, SAFE.w, P.SERIF, 116, 64, "headline", align="center", ls=1.04,
                   color=self.ON, maxh=900)
        P.footer(img, align="center", ink=self.ON, soft=self.ON)
        return img, [put(lay, SAFE.y + (FOOT - SAFE.y - lay.height) // 2)]

    def b_cover(self, img, data, swipe):
        split = 1150
        self.block(img, split)
        title = text(data["cover_title"], SAFE.x, SAFE.w, P.SERIF, 150, 72, "headline", ls=1.0,
                     color=self.ON, maxh=760)
        lays = [put(title, split - 80 - title.height)]
        if data.get("cover_subtitle"):
            lays.append(put(text(data["cover_subtitle"], SAFE.x, SAFE.w, P.TEXT_W, 50, 36,
                                 color=P.SOFT), split + 90))
        P.footer(img)
        if swipe:
            P.swipe_pill(img)
        return img, lays

    def b_point(self, img, i, p, page, pages):
        split = 760
        self.block(img, split)
        label(img, f"{i:02d}", (SAFE.x - 14, split - 70), 440, self.BLOCK_ACCENT, P.NUM_W)
        title = text(p["title"], SAFE.x, SAFE.w, P.SERIF, 96, 56, "headline", ls=1.04, maxh=330)
        body = text(p["body"], SAFE.x, SAFE.w, P.TEXT_W, 50, 34, color=P.SOFT, ls=1.34, maxh=300)
        P.footer(img, page, pages)
        return img, stack([(title, 44), (body, 0)], split + 90)


# ================================================================ cinematic
class Cinematic:
    """A thin frame, a huge faint watermark number, text anchored low like film titles."""
    X, BOTTOM = SAFE.x + 40, FOOT - 40

    def frame(self, img: Image.Image, mark: str | None = None) -> None:
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([60, 190, W - 60, SAFE.bottom + 50], outline=P.ACCENT + (90,), width=2)
        if mark:   # a faint watermark number, composited so it really is see-through
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((W - 110, 820), mark, font=font(P.NUM_W, 560),
                                       fill=P.ACCENT + (34,), anchor="rs")
            rgba = img.convert("RGBA")
            rgba.alpha_composite(layer)
            img.paste(rgba.convert("RGB"))

    def kicker(self, img: Image.Image, s: str, y: int) -> None:
        d = ImageDraw.Draw(img)
        d.line([(self.X, y - 12), (self.X + 64, y - 12)], fill=P.ACCENT, width=3)
        label(img, s, (self.X + 84, y), 34, P.ACCENT)

    def low(self, img, items, kicker: str | None = None) -> list[TextLayout]:
        top = self.BOTTOM - total(items)
        lays = stack(items, top)
        if kicker:
            self.kicker(img, kicker, lays[0].top - 46)
        return lays

    def a_hook(self, img, data):
        self.frame(img)
        w = SAFE.right - self.X
        concept = text(data["concept"], self.X, w, P.SERIF, 150, 76, "headline", ls=1.0, maxh=640)
        hook = text(data["hook_line"], self.X, w, P.STRONG_W, 56, 40, color=P.SOFT, maxh=240)
        lays = self.low(img, [(concept, 50), (hook, 0)], CFG.engine_a.wording.intro_label)
        P.footer(img, 1, 4)
        return img, lays

    def a_para(self, img, num, name, body):
        self.frame(img, f"{num:02d}")
        para = text(body, self.X, SAFE.right - self.X, P.PARA_W, 64, 42, "paragraph", ls=1.26, maxh=820)
        lays = self.low(img, [(para, 0)], name)
        P.footer(img, num, 4)
        return img, lays

    def a_shift(self, img, body):
        self.frame(img)
        lay = text(body, SAFE.x + 30, SAFE.w - 60, P.SERIF, 104, 60, "headline", align="center",
                   ls=1.08, maxh=900)
        P.footer(img, align="center")
        return img, [put(lay, SAFE.y + (FOOT - SAFE.y - lay.height) // 2)]

    def b_cover(self, img, data, swipe):
        self.frame(img)
        w = SAFE.right - self.X
        items = [(text(data["cover_title"], self.X, w, P.SERIF, 140, 70, "headline", ls=1.0,
                       maxh=760), 44)]
        if data.get("cover_subtitle"):
            items.append((text(data["cover_subtitle"], self.X, w, P.TEXT_W, 48, 34, color=P.SOFT), 0))
        lays = self.low(img, items)
        P.footer(img)
        if swipe:
            P.swipe_pill(img)
        return img, lays

    def b_point(self, img, i, p, page, pages):
        self.frame(img, f"{i:02d}")
        w = SAFE.right - self.X
        title = text(p["title"], self.X, w, P.SERIF, 100, 58, "headline", ls=1.04, maxh=360)
        body = text(p["body"], self.X, w, P.TEXT_W, 50, 34, color=P.SOFT, ls=1.34, maxh=320)
        lays = self.low(img, [(title, 40), (body, 0)], f"No. {i}")
        P.footer(img, page, pages)
        return img, lays


# ================================================================ cards
class Cards:
    """Content on a floating card, with a sticker label or a number badge on its top edge."""
    BOX_X, BOX_W = 120, W - 240
    IN_X, IN_W = 170, W - 340
    SURFACE = _c("card", "#FFFFFF")
    STICKER = _c("sticker", "#E4572E")

    def on_card(self, img, items, top_pad: int = 110, bottom_pad: int = 90):
        h = total(items) + top_pad + bottom_pad
        top = SAFE.y + 40 + max(0, (FOOT - SAFE.y - 40 - h) // 2)
        img = card(img, Box(self.BOX_X, top, self.BOX_W, h), self.SURFACE)
        return img, stack(items, top + top_pad), top

    def a_hook(self, img, data):
        concept = text(data["concept"], self.IN_X, self.IN_W, P.SERIF, 128, 64, "headline",
                       align="center", ls=1.02, maxh=560)
        hook = text(data["hook_line"], self.IN_X, self.IN_W, P.STRONG_W, 54, 38, align="center",
                    maxh=260)
        img, lays, top = self.on_card(img, [(concept, 56), (hook, 0)])
        pill(img, CFG.engine_a.wording.intro_label, W // 2, top, self.STICKER, (255, 255, 255))
        P.footer(img, 1, 4)
        return img, lays

    def a_para(self, img, num, name, body):
        para = text(body, self.IN_X, self.IN_W, P.PARA_W, 58, 40, "paragraph", align="center",
                    ls=1.28, maxh=860)
        img, lays, top = self.on_card(img, [(para, 0)])
        pill(img, f"{num:02d}  ·  {name}", W // 2, top, self.STICKER, (255, 255, 255))
        P.footer(img, num, 4)
        return img, lays

    def a_shift(self, img, body):
        lay = text(body, self.IN_X, self.IN_W, P.SERIF, 96, 56, "headline", align="center",
                   ls=1.06, maxh=860)
        img, lays, _ = self.on_card(img, [(lay, 0)], 90, 90)
        P.footer(img, align="center")
        return img, lays

    def b_cover(self, img, data, swipe):
        items = [(text(data["cover_title"], SAFE.x, SAFE.w, P.SERIF, 150, 72, "headline",
                       align="center", ls=1.0, maxh=760), 50)]
        if data.get("cover_subtitle"):
            items.append((text(data["cover_subtitle"], SAFE.x, SAFE.w, P.TEXT_W, 50, 34,
                               align="center", color=P.SOFT), 0))
        lays = stack(items, SAFE.y + (FOOT - SAFE.y - total(items)) // 2 - 20)
        P.footer(img)
        if swipe:
            P.swipe_pill(img)
        return img, lays

    def b_point(self, img, i, p, page, pages):
        title = text(p["title"], self.IN_X, self.IN_W, P.SERIF, 88, 54, "headline", align="center",
                     ls=1.04, maxh=360)
        body = text(p["body"], self.IN_X, self.IN_W, P.TEXT_W, 48, 34, align="center",
                    color=P.SOFT, ls=1.34, maxh=320)
        img, lays, top = self.on_card(img, [(title, 40), (body, 0)], 150, 100)
        d = ImageDraw.Draw(img)
        r = 86
        d.ellipse([W // 2 - r, top - r, W // 2 + r, top + r], fill=self.STICKER)
        d.text((W // 2, top + 6), str(i), font=font(P.NUM_W, 120), fill=(255, 255, 255), anchor="mm")
        P.footer(img, page, pages)
        return img, lays


# ================================================================ swiss
class Swiss:
    """Asymmetric grid: giant numeral top-left, a red bar, page count top-right, text bottom-left."""
    TOP = SAFE.y + 60

    def chrome(self, img, page: int | None, pages: int | None) -> None:
        d = ImageDraw.Draw(img)
        d.rectangle([SAFE.x, self.TOP, SAFE.x + 150, self.TOP + 18], fill=P.ACCENT)
        if page:
            d.text((SAFE.right, self.TOP + 22), f"{page}/{pages}", font=font(P.NUM_W, 46),
                   fill=P.INK, anchor="rs")

    def bottom(self, items) -> list[TextLayout]:
        return stack(items, FOOT - 20 - total(items))

    def a_hook(self, img, data):
        self.chrome(img, 1, 4)
        concept = put(text(data["concept"], SAFE.x, SAFE.w, P.SERIF, 196, 90, "headline", ls=0.94,
                           maxh=720), self.TOP + 110)
        hook = text(data["hook_line"], SAFE.x, SAFE.w, P.STRONG_W, 66, 44, maxh=280)
        lays = self.bottom([(hook, 0)])
        label(img, CFG.engine_a.wording.intro_label, (SAFE.x, lays[0].top - 40), 34, P.SOFT, P.TEXT_W)
        P.footer(img, show_page=False)
        return img, [concept, *lays]

    def a_para(self, img, num, name, body):
        self.chrome(img, num, 4)
        label(img, f"{num:02d}", (SAFE.x - 14, self.TOP + 400), 380, P.INK, P.NUM_W)
        label(img, name, (SAFE.x, self.TOP + 470), 40, P.ACCENT)
        para = text(body, SAFE.x, SAFE.w, P.PARA_W, 60, 42, "paragraph", ls=1.24, maxh=560)
        P.footer(img, show_page=False)
        return img, self.bottom([(para, 0)])

    def a_shift(self, img, body):
        self.chrome(img, 4, 4)
        lay = text(body, SAFE.x, SAFE.w, P.SERIF, 120, 64, "headline", ls=1.0, maxh=900)
        P.footer(img, show_page=False)
        return img, self.bottom([(lay, 0)])

    def b_cover(self, img, data, swipe):
        self.chrome(img, None, None)
        title = put(text(data["cover_title"], SAFE.x, SAFE.w, P.SERIF, 170, 80, "headline", ls=0.95,
                         maxh=860), self.TOP + 110)
        lays = [title]
        if data.get("cover_subtitle"):
            lays += self.bottom([(text(data["cover_subtitle"], SAFE.x, SAFE.w, P.TEXT_W, 52, 36,
                                       color=P.SOFT), 0)])
        P.footer(img, show_page=False)
        if swipe:
            P.swipe_pill(img)
        return img, lays

    def b_point(self, img, i, p, page, pages):
        self.chrome(img, page, pages)
        label(img, f"{i:02d}", (SAFE.x - 14, self.TOP + 430), 420, P.ACCENT, P.NUM_W)
        title = text(p["title"], SAFE.x, SAFE.w, P.SERIF, 104, 56, "headline", ls=1.0, maxh=380)
        body = text(p["body"], SAFE.x, SAFE.w, P.TEXT_W, 50, 34, color=P.SOFT, ls=1.32, maxh=320)
        P.footer(img, show_page=False)
        return img, self.bottom([(title, 40), (body, 0)])


BLUEPRINTS = {"notebook": Notebook, "poster": Poster, "cinematic": Cinematic, "cards": Cards,
              "swiss": Swiss}


def active():
    """The theme's blueprint, or None for the original editorial layout."""
    cls = BLUEPRINTS.get(BLUEPRINT)
    return cls() if cls else None


# ---------------------------------------------------------------- engine builders
def build_a(data: dict, seed: int, step_names: list[str]) -> list[Step]:
    bp = active()
    steps = []
    img, lays = bp.a_hook(P.background(seed, variant=0), data)
    steps.append(Step(img, lays))
    for idx, key in ((1, "gotcha"), (2, "mechanism")):
        img, lays = bp.a_para(P.background(seed, variant=idx), idx + 1, step_names[idx], data[key])
        steps.append(Step(img, lays))
    img, lays = bp.a_shift(P.background(seed, variant=3), data["shift"])
    steps.append(Step(img, lays))
    return steps


def build_b(data: dict, seed: int, swipe: bool = True, n_slides: int = 6) -> list[Step]:
    bp = active()
    steps = []
    img, lays = bp.b_cover(P.background(seed, variant=0), data, swipe)
    steps.append(Step(img, lays))
    for i, p in enumerate(data["points"], 1):
        img, lays = bp.b_point(P.background(seed, variant=i), i, p, i + 1, n_slides)
        steps.append(Step(img, lays))
    return steps
