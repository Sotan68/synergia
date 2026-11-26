"""Engine D — Brain Test: 3-4 of 10 procedurally generated mini-games with timers, ~30-45 s 9:16 MP4.

No Claude round-trip: every round (grids, colours, words, dots, cup shuffles) is generated from a
random seed, and recently used hooks / character pairs / words are avoided (synergia.history).
"""
from __future__ import annotations

import colorsys
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache, partial
from pathlib import Path

from PIL import Image, ImageDraw

from synergia import history
from synergia.brand.animate import FINAL, Step, full_frame, render_video
from synergia.brand import quiz, typography
from synergia.brand.canvas import SAFE, Box, draw_safe_zone
from synergia.brand.elements import draw_ring, draw_timer
from synergia.brand.quiz import ACCENT, ACCENT2, BOLD, HEAVY, MED, MUTED, SEMI, TEXT
from synergia.brand.typography import TextLayout, font
from synergia.config import CFG
from synergia.output import run_dir, save_meta

W, H = CFG.brand.width, CFG.brand.height
layout_text = partial(typography.layout_text, color=TEXT, accent_color=ACCENT)   # quiz colours
GAME = Box(quiz.INNER.x, SAFE.y + 290, quiz.INNER.w, 720)   # play area (y 540..1260), inside the card
TIMER_C = (W // 2, SAFE.bottom - 124)                  # countdown ring centre (inside the card)
TIMER_R = 52
REVEAL_HOLD = 1.8                                      # seconds the answer stays on screen


def _cfg(name: str, default):
    return getattr(getattr(CFG, "engine_d", None), name, default)


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def _fade(t: float, start: float, d: float = 0.22) -> float:
    return max(0.0, min(1.0, (t - start) / d))


# ---------------------------------------------------------------- RGBA drawing helpers
def _paste(im: Image.Image, sprite: Image.Image, x: int, y: int, alpha: float = 1.0) -> None:
    """Composite an RGBA sprite onto RGBA im in place, with extra opacity."""
    if alpha <= 0:
        return
    if alpha < 1:
        sprite = sprite.copy()
        sprite.putalpha(sprite.getchannel("A").point(lambda v: int(v * alpha)))
    im.alpha_composite(sprite, (int(x), int(y)))


class _Pen:
    """ImageDraw whose semi-transparent fills really blend onto an RGBA frame.

    Pillow writes RGBA pixels as they are when drawing on an RGBA image (a 40% shadow becomes a
    40%-opaque hole, which turns solid once the frame goes back to RGB). Shapes go on a clear
    layer instead, and flush() composites it onto the frame."""

    def __init__(self, im: Image.Image):
        self.im = im
        self.layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.layer)

    def __getattr__(self, name):
        return getattr(self.d, name)

    def flush(self) -> None:
        self.im.alpha_composite(self.layer)


def _layout(im: Image.Image, lay: TextLayout, alpha: float = 1.0, dy: float = 0.0) -> None:
    for i in range(len(lay.words)):
        spr, x, y = lay.sprite(i)
        _paste(im, spr, x, y + dy, alpha)


@lru_cache(maxsize=256)
def _text_sprite(text: str, weight: str, size: int, color: tuple) -> Image.Image:
    f = font(weight, size)
    l, t, r, b = f.getbbox(text, anchor="mm")
    im = Image.new("RGBA", (r - l + 8, b - t + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((-l + 4, -t + 4), text, font=f, fill=tuple(color) + (255,), anchor="mm")
    return im


def _center_text(im, text, cx, cy, weight=BOLD, size=60, color=TEXT, alpha=1.0, dy=0.0):
    spr = _text_sprite(text, weight, size, tuple(color))
    _paste(im, spr, cx - spr.width / 2, cy - spr.height / 2 + dy, alpha)


def _prompt_layout(text: str) -> TextLayout:
    """A centred question line at the top of the play area ("Which one is missing?")."""
    return layout_text(text, Box(GAME.x, GAME.y - 10, GAME.w, 110), weight=BOLD, max_size=66,
                       min_size=44, align="center", valign="top")


def _timer(im: Image.Image, t: float, start: float, secs: int) -> None:
    if start <= t < start + secs:
        left = start + secs - t
        _ = draw_timer(im, *TIMER_C, TIMER_R, left / secs, math.ceil(left - 1e-6),
                       alpha=_fade(t, start, 0.15))


def _timer_sfx(start: float, secs: int) -> list[tuple[float, str]]:
    return [(start + i, "tick") for i in range(secs)] + [(start + secs, "buzz")]


# ---------------------------------------------------------------- games
@dataclass
class Game:
    label: str                         # small label above the instruction ("Stroop test")
    instruction: str                   # typed at the top of the round
    duration: float = 0.0              # seconds after the instruction is typed
    sfx: list[tuple[float, str]] = field(default_factory=list)
    used: dict = field(default_factory=dict)   # history keys -> items used

    def draw(self, im: Image.Image, t: float) -> None:   # im is RGBA, drawn on in place
        raise NotImplementedError


INKS = {"RED": (255, 77, 77), "BLUE": (70, 140, 255), "GREEN": (60, 205, 95),
        "YELLOW": (238, 172, 0), "PURPLE": (176, 104, 255), "ORANGE": (255, 140, 20)}


class Stroop(Game):
    """Colour words flash in mismatched ink; say the ink colour out loud."""

    def __init__(self, level: float, rng: random.Random):
        super().__init__("Stroop test", "Say the **colour**, not the word")
        self.n = 8
        self.start = 0.3
        self.every = round(_lerp(1.0, 0.45, level), 2)
        names = list(INKS)
        seq: list[tuple[str, str]] = []
        while len(seq) < self.n:
            w, ink = rng.choice(names), rng.choice(names)
            if w == ink or (seq and (w == seq[-1][0] or ink == seq[-1][1])):
                continue
            seq.append((w, ink))
        self.seq = seq
        self.end = self.start + self.n * self.every
        self.duration = self.end + REVEAL_HOLD
        self.sfx = [(self.start + k * self.every, "tick") for k in range(self.n)] + [(self.end, "ding")]
        self.big = 176
        while max(font(HEAVY, self.big).getlength(w) for w in INKS) > GAME.w - 40:
            self.big -= 4
        self.recap_q = _prompt_layout("Did you get all **8** right?")

    def draw(self, im, t):
        cx, cy = GAME.cx, GAME.cy - 30
        if t < self.end:
            if t < self.start:
                return
            k = min(self.n - 1, int((t - self.start) / self.every))
            local = t - self.start - k * self.every
            w, ink = self.seq[k]
            a = _fade(local, 0, 0.06)
            _center_text(im, w, cx, cy, HEAVY, self.big, INKS[ink], a, (1 - a) * 14)
            # progress dots
            gap = 34
            x0 = cx - gap * (self.n - 1) / 2
            d = _Pen(im)
            for i in range(self.n):
                col = TEXT if i <= k else MUTED
                r = 8 if i == k else 6
                x = x0 + i * gap
                d.ellipse([x - r, cy + 190 - r, x + r, cy + 190 + r], fill=col + ((255,) if i <= k else (110,)))
            d.flush()
            return
        # recap: the whole sequence as a 2 x 4 table in ink colours
        a = _fade(t, self.end, 0.3)
        _layout(im, self.recap_q, a)
        col_x = (GAME.x + GAME.w * 0.26, GAME.x + GAME.w * 0.74)
        size = _fit(max(INKS, key=lambda k: font(HEAVY, 84).getlength(k)), HEAVY, 84,
                    int(GAME.w * 0.46))
        for i, (w, ink) in enumerate(self.seq):
            x, y = col_x[i % 2], GAME.y + 190 + (i // 2) * 128
            _center_text(im, w, x, y, HEAVY, size, INKS[ink], a)


# Character pairs (base, odd) by difficulty; either order may be used.
PAIRS = [
    [("O", "Q"), ("E", "F"), ("P", "R"), ("C", "G"), ("V", "Y"), ("M", "W"), ("3", "8"), ("U", "V"),
     ("K", "X"), ("1", "7"), ("T", "Y"), ("A", "H"), ("L", "E"), ("2", "7"), ("S", "Z")],
    [("b", "d"), ("p", "q"), ("6", "9"), ("M", "N"), ("5", "S"), ("n", "h"), ("u", "v"), ("m", "n"),
     ("E", "B"), ("H", "N"), ("c", "e"), ("a", "o"), ("2", "Z"), ("G", "6"), ("X", "Y")],
    [("O", "0"), ("8", "B"), ("D", "O"), ("C", "O"), ("n", "r"), ("v", "y"), ("h", "b"), ("Q", "O"),
     ("3", "5"), ("6", "8"), ("0", "8"), ("9", "g"), ("e", "o"), ("R", "B"), ("5", "6")],
]


class _FindOne(Game):
    """Shared timeline for 'spot the different one in a grid' games."""
    APPEAR = 0.25

    def _setup_timeline(self) -> None:
        self.secs = int(_cfg("timer_seconds", 4))
        self.reveal = self.APPEAR + self.secs
        self.duration = self.reveal + REVEAL_HOLD
        self.sfx = [(0.0, "pop")] + _timer_sfx(self.APPEAR, self.secs) + [(self.reveal + 0.3, "ding")]

    def draw(self, im, t):
        self.draw_puzzle(im, _fade(t, 0, self.APPEAR))
        _timer(im, t, self.APPEAR, self.secs)
        if t >= self.reveal:
            self.draw_answer(im, t)

    def draw_puzzle(self, im, a: float) -> None:
        _paste(im, self.grid, GAME.x, GAME.y, a)

    def draw_answer(self, im, t):
        raise NotImplementedError


class OddChar(_FindOne):
    def __init__(self, level: float, rng: random.Random):
        tier = PAIRS[min(2, int(level * 3))]
        pair = history.pick_fresh(rng, tier, 1, "brain.pairs")[0]
        base, odd = pair if rng.random() < 0.5 else pair[::-1]
        super().__init__("Odd one out", f"Find the **{odd}**", used={"brain.pairs": [pair]})
        cols, rows = round(_lerp(6, 9, level)), round(_lerp(8, 12, level))
        self.cell = cell = min(GAME.w / cols, GAME.h / rows)
        size = int(cell * 0.74)
        gx = (GAME.w - cell * cols) / 2
        gy = (GAME.h - cell * rows) / 2
        self.pos = (rng.randrange(cols), rng.randrange(rows))
        self.grid = Image.new("RGBA", (GAME.w, GAME.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(self.grid)
        f = font(BOLD, size)
        for c in range(cols):
            for r in range(rows):
                ch = odd if (c, r) == self.pos else base
                d.text((gx + (c + 0.5) * cell, gy + (r + 0.5) * cell), ch, font=f,
                       fill=TEXT + (255,), anchor="mm")
        self.centre = (GAME.x + gx + (self.pos[0] + 0.5) * cell, GAME.y + gy + (self.pos[1] + 0.5) * cell)
        self.odd, self.size = odd, size
        self._setup_timeline()

    def draw_answer(self, im, t):
        cx, cy = self.centre
        _center_text(im, self.odd, cx, cy, BOLD, self.size, ACCENT, _fade(t, self.reveal, 0.15))
        draw_ring(im, int(cx), int(cy), int(self.cell * 0.56), _ease((t - self.reveal) / 0.45))


class OddColour(_FindOne):
    def __init__(self, level: float, rng: random.Random):
        super().__init__("Colour vision", "Spot the **different** shade")
        cols, rows = round(_lerp(4, 6, level)), round(_lerp(5, 8, level))
        cell = min(GAME.w / cols, GAME.h / rows)
        gap = max(8, int(cell * 0.08))
        hue = rng.random()
        sat, val = rng.uniform(0.45, 0.7), rng.uniform(0.62, 0.8)
        delta = _lerp(0.16, 0.055, level) * rng.choice((1, -1))
        base = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, val))
        oddc = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, max(0, min(1, val + delta))))
        gx = (GAME.w - cell * cols) / 2
        gy = (GAME.h - cell * rows) / 2
        self.pos = (rng.randrange(cols), rng.randrange(rows))
        self.grid = Image.new("RGBA", (GAME.w, GAME.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(self.grid)
        for c in range(cols):
            for r in range(rows):
                x, y = gx + c * cell + gap / 2, gy + r * cell + gap / 2
                col = oddc if (c, r) == self.pos else base
                d.rounded_rectangle([x, y, x + cell - gap, y + cell - gap], cell * 0.16, fill=col + (255,))
        self.centre = (GAME.x + gx + (self.pos[0] + 0.5) * cell, GAME.y + gy + (self.pos[1] + 0.5) * cell)
        self.cell = cell
        self._setup_timeline()

    def draw_answer(self, im, t):
        cx, cy = self.centre
        draw_ring(im, int(cx), int(cy), int(self.cell * 0.66), _ease((t - self.reveal) / 0.45),
                  color=TEXT, width=10)


WORDS = """apple anchor arrow bakery balloon banana basket battery beach bear bell bicycle blanket
boat bone book bottle bread bridge brush bucket butter button cabin cactus cake camera candle
canoe carpet carrot castle cat chair cheese cherry chess circus clock cloud coat coffee coin
comet compass cookie corn crown cup curtain desert diamond dolphin door dragon drum duck eagle
engine envelope feather fence fire flag flute forest fork fountain fox garden ghost giraffe
glove goat guitar hammer harbor hat helmet honey horse island jacket jungle kettle key kite
ladder lamp lantern lemon letter library lion lizard magnet map marble mask meadow mirror monkey
moon mountain mouse needle nest ocean office onion orange owl paint palace panda paper parrot
peach pencil penguin pepper piano pillow pirate pizza planet plate pocket pumpkin puzzle queen
rabbit radio rainbow river robot rocket rope saddle sailor salad sand scarf school shark shell
ship shoe silver skate snail snake soap sock spider spoon stamp star statue stone storm sugar
sun sweater sword table tiger tomato tower tractor train treasure tree trumpet tunnel turtle
umbrella valley vase violin volcano wagon wallet watch whale wheel window wizard wolf zebra
acorn almond antler apron attic badge bagel bamboo bandage barrel beacon beetle blossom bonnet
bracelet bubble cabbage canyon cape cargo cellar chimney cinema cobweb collar copper coral cotton
crayon cricket cushion daisy dart denim dice donkey dune easel ember fabric falcon ferry fiddle
fig flannel flask fossil frame gadget galaxy garlic gem glacier goblet grape gravel hammock
harp hedge hive hook igloo ink ivory jar jelly jigsaw kayak kiwi knot lace lagoon lava leaf
lobster locket lotus mango maple mitten mosaic moss mug mustard napkin noodle oak oar olive
orbit otter oven paddle palette parcel pearl pebble pepperoni pigeon pine plum pond poppy
quartz quill quilt raft raisin raven reef ribbon saffron satchel scroll seal shovel sled slipper
spark sponge squid stool straw tablet teapot thimble thistle ticket tile toast tulip tuba
twig velvet vine waffle walnut wand willow yarn yogurt""".split()


class Memory(Game):
    def __init__(self, level: float, rng: random.Random):
        super().__init__("Memory test", "Remember these **words**")
        n = round(_lerp(6, 9, level))
        self.words = [w.upper() for w in history.pick_fresh(rng, WORDS, n, "brain.words")]
        self.used = {"brain.words": [w.lower() for w in self.words]}
        self.missing = rng.choice(self.words)
        rest = [w for w in self.words if w != self.missing]
        rng.shuffle(rest)
        self.show = float(_cfg("memory_seconds", 3))
        self.secs = int(_cfg("timer_seconds", 4))
        self.hide = 0.2 + self.show
        self.q = self.hide + 0.45
        self.reveal = self.q + 0.3 + self.secs
        self.duration = self.reveal + REVEAL_HOLD
        self.sfx = ([(0.0, "pop")] + [(0.2 + i, "tick") for i in range(int(self.show))] +
                    [(self.hide, "whoosh"), (self.q, "pop")] + _timer_sfx(self.q + 0.3, self.secs) +
                    [(self.reveal + 0.3, "ding")])
        self.grid_all = self._grid(self.words, GAME.y, GAME.bottom)
        self.grid_rest = self._grid(rest, GAME.y + 100, GAME.bottom - 160)   # room for the answer
        self.question = _prompt_layout("Which one is **missing**?")

    @staticmethod
    def _grid(words: list[str], top: int, bottom: int) -> Image.Image:
        """The words in 2-3 columns, centred vertically between top and bottom."""
        cols = 2 if len(words) <= 8 else 3
        rows = math.ceil(len(words) / cols)
        cw = GAME.w / cols
        rh = min(130, (bottom - top) / rows)
        top += (bottom - top - rows * rh) / 2
        size = 64 if cols == 2 else 52
        f = font(BOLD, size)
        while max(f.getlength(w) for w in words) > cw - 24:
            size -= 2
            f = font(BOLD, size)
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i, w in enumerate(words):
            c, r = i % cols, i // cols
            d.text((GAME.x + (c + 0.5) * cw, top + (r + 0.5) * rh), w, font=f, fill=TEXT + (255,),
                   anchor="mm")
        return im

    def draw(self, im, t):
        if t < self.hide + 0.25:
            a = _fade(t, 0, 0.2) * (1 - _fade(t, self.hide, 0.25))
            _paste(im, self.grid_all, 0, 0, a)
            if t < self.hide:
                left = self.hide - t
                _ = draw_timer(im, *TIMER_C, TIMER_R, left / self.show, math.ceil(left - 1e-6),
                               alpha=_fade(t, 0.2, 0.15))
            return
        a = _fade(t, self.q, 0.25)
        _layout(im, self.question, a)
        _paste(im, self.grid_rest, 0, 0, a)
        _timer(im, t, self.q + 0.3, self.secs)
        if t >= self.reveal:
            b = _fade(t, self.reveal, 0.3)
            y = GAME.bottom - 40
            _center_text(im, "Missing", GAME.cx, y - 82, SEMI, 30, MUTED, b)
            _center_text(im, self.missing, GAME.cx, y, HEAVY, 92, ACCENT, b, (1 - b) * 16)


class CountFlash(Game):
    def __init__(self, level: float, rng: random.Random):
        super().__init__("Speed count", "Count the **dots**")
        lo, hi = round(_lerp(6, 13, level)), round(_lerp(9, 18, level))
        self.n = rng.randint(lo, hi)
        self.flash = round(_lerp(1.4, 0.8, level), 2)
        r = 30
        pts: list[tuple[float, float]] = []
        area = Box(GAME.x + 40, GAME.y + 140, GAME.w - 80, GAME.h - 200)
        while len(pts) < self.n:
            p = (rng.uniform(area.x, area.right), rng.uniform(area.y, area.bottom))
            if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > (2.7 * r) ** 2 for q in pts):
                pts.append(p)
        self.dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(self.dots)
        for x, y in pts:
            col = rng.choice((ACCENT, ACCENT2, TEXT))
            d.ellipse([x - r, y - r, x + r, y + r], fill=col + (255,))
        self.on, self.off = 0.3, 0.3 + self.flash
        self.secs = int(_cfg("timer_seconds", 4))
        self.q = self.off + 0.35
        self.reveal = self.q + 0.3 + self.secs
        self.duration = self.reveal + REVEAL_HOLD
        self.sfx = ([(self.on, "pop"), (self.off, "whoosh"), (self.q, "pop")] +
                    _timer_sfx(self.q + 0.3, self.secs) + [(self.reveal + 0.3, "ding")])
        self.question = _prompt_layout("How many **dots**?")

    def draw(self, im, t):
        if t < self.q:
            a = _fade(t, self.on, 0.08) * (1 - _fade(t, self.off, 0.08))
            _paste(im, self.dots, 0, 0, a)
            return
        _layout(im, self.question, _fade(t, self.q, 0.25))
        _timer(im, t, self.q + 0.3, self.secs)
        if t >= self.reveal:
            b = _fade(t, self.reveal, 0.3)
            _paste(im, self.dots, 0, 0, 0.3 * b)
            _center_text(im, str(self.n), GAME.cx, GAME.cy + 30, HEAVY, 230, ACCENT, b, (1 - b) * 20)


@lru_cache(maxsize=1)
def _cup_sprite() -> Image.Image:
    """An upside-down cup: narrow top, wide rim, purple -> blue gradient, drawn at 4x."""
    w, h, s = 210, 230, 4
    im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    mask = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(mask)
    top, bot = 0.28, 0.5   # half-widths (fraction of w) at top and bottom
    md.polygon([(w * (0.5 - top) * s, 18 * s), (w * (0.5 + top) * s, 18 * s),
                (w * (0.5 + bot) * s, (h - 26) * s), (w * (0.5 - bot) * s, (h - 26) * s)], fill=255)
    md.ellipse([w * (0.5 - top) * s, 0, w * (0.5 + top) * s, 36 * s], fill=255)
    md.ellipse([0, (h - 52) * s, w * s, h * s], fill=255)
    grad = Image.new("RGBA", im.size)
    gd = ImageDraw.Draw(grad)
    for y in range(im.height):
        k = y / im.height
        gd.line([(0, y), (im.width, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(ACCENT2, ACCENT)) + (255,))
    im.paste(grad, (0, 0), mask)
    base = tuple(int(c * 0.62) for c in ACCENT2)          # the cup's closed end, a deeper purple
    ImageDraw.Draw(im).ellipse([w * (0.5 - top) * s, 0, w * (0.5 + top) * s, 36 * s],
                               fill=base + (255,))
    d = _Pen(im)
    d.ellipse([w * (0.5 - top) * s + 3 * s, 3 * s, w * (0.5 + top) * s - 3 * s, 33 * s],
              outline=(255, 255, 255, 70), width=2 * s)
    d.rounded_rectangle([w * 0.3 * s, 60 * s, w * 0.35 * s, (h - 60) * s], radius=3 * s,
                        fill=(255, 255, 255, 64))           # shine
    d.flush()
    return im.resize((w, h), Image.LANCZOS)


class ShellGame(Game):
    SLOTS = (-238, 0, 238)

    def __init__(self, level: float, rng: random.Random):
        super().__init__("Shell game", "Follow the **ball**")
        self.ball_cup = rng.randrange(3)
        self.n_swaps = round(_lerp(4, 9, level))
        self.swap_d = round(_lerp(0.62, 0.3, level), 2)
        self.lift = 170
        self.t_show, self.t_lower = 0.3, 1.3
        self.t_swaps = self.t_lower + 0.55
        swaps, last = [], None
        for _ in range(self.n_swaps):
            pair = tuple(sorted(rng.sample(range(3), 2)))
            if pair == last:
                pair = tuple(sorted({0, 1, 2} - {pair[rng.randrange(2)]}))
            swaps.append(pair)
            last = pair
        self.swaps = swaps
        # slot_of[cup] after each swap
        self.states = [[0, 1, 2]]
        for a, b in swaps:
            s = list(self.states[-1])
            ca, cb = s.index(a), s.index(b)
            s[ca], s[cb] = b, a
            self.states.append(s)
        self.end_swaps = self.t_swaps + self.n_swaps * self.swap_d
        self.secs = int(_cfg("timer_seconds", 4))
        self.q = self.end_swaps + 0.3
        self.reveal = self.q + 0.3 + self.secs
        self.duration = self.reveal + REVEAL_HOLD
        self.sfx = ([(0.0, "pop"), (self.t_lower, "whoosh")] +
                    [(self.t_swaps + i * self.swap_d, "tick") for i in range(self.n_swaps)] +
                    [(self.q, "pop")] + _timer_sfx(self.q + 0.3, self.secs) +
                    [(self.reveal, "whoosh"), (self.reveal + 0.3, "ding")])
        self.question = _prompt_layout("Where is the **ball**?")
        self.floor = GAME.y + 520

    def _cup_xy(self, cup: int, t: float) -> tuple[float, float]:
        """Centre-x and lift (px above the floor) of a cup at time t."""
        if t < self.t_swaps:
            lift = self.lift * (1 - _ease((t - self.t_lower) / 0.45))
            return GAME.cx + self.SLOTS[cup], lift
        i = int((t - self.t_swaps) / self.swap_d)
        if i >= self.n_swaps:
            return GAME.cx + self.SLOTS[self.states[-1].index(cup)], 0.0
        k = _ease((t - self.t_swaps - i * self.swap_d) / self.swap_d)
        s0, s1 = self.states[i], self.states[i + 1]
        a, b = s0.index(cup), s1.index(cup)
        x = _lerp(self.SLOTS[a], self.SLOTS[b], k)
        arc = 0.0
        if a != b:
            arc = math.sin(math.pi * k) * (70 if a < b else -30)
        return GAME.cx + x, arc

    def draw(self, im, t):
        cup = _cup_sprite()
        a = _fade(t, 0, 0.25)
        # The ball sits under its cup's slot; it's only visible while that cup is lifted.
        final_slot = self.states[-1].index(self.ball_cup)
        reveal_k = _ease((t - self.reveal) / 0.35) if t >= self.reveal else 0.0
        ball_x = self._cup_xy(self.ball_cup, t)[0]
        d = _Pen(im)
        for c in range(3):   # soft floor shadows
            x, _ = self._cup_xy(c, t)
            d.ellipse([x - 95, self.floor - 12, x + 95, self.floor + 14], fill=((0, 0, 0) if quiz.SURFACE_DARK else quiz.TEXT) + (int(34 * a),))
        d.flush()
        br = 40
        _ball = _ball_sprite(br)
        if t < self.t_swaps or t >= self.reveal:
            _paste(im, _ball, ball_x - br - 6, self.floor - 2 * br - 6, a)
        for c in range(3):
            x, lift = self._cup_xy(c, t)
            if t >= self.reveal and c == self.ball_cup:
                lift = self.lift * 0.9 * reveal_k
            _paste(im, cup, x - cup.width / 2, self.floor - cup.height + 18 - lift, a)
        if t >= self.q:
            b = _fade(t, self.q, 0.25)
            _layout(im, self.question, b)
            for i, sx in enumerate(self.SLOTS):
                col = ACCENT if (t >= self.reveal and i == final_slot) else MUTED
                _center_text(im, str(i + 1), GAME.cx + sx, self.floor + 70, HEAVY, 56, col, b)
        _timer(im, t, self.q + 0.3, self.secs)


@lru_cache(maxsize=4)
def _ball_sprite(r: int) -> Image.Image:
    s, pad = 4, 6
    size = (2 * r + 2 * pad) * s
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([pad * s, pad * s, size - pad * s, size - pad * s],
                               fill=(255, 196, 64, 255))
    d = _Pen(im)
    d.ellipse([(pad + r * 0.45) * s, (pad + r * 0.35) * s, (pad + r * 0.95) * s, (pad + r * 0.8) * s],
              fill=(255, 255, 255, 120))
    d.flush()
    return im.resize((size // s, size // s), Image.LANCZOS)



def _fit(text: str, weight: str, size: int, width: int) -> int:
    while size > 30 and font(weight, size).getlength(text) > width:
        size -= 4
    return size


def _note(im, text, a, dy=0):
    """Small muted explanation line under the answer."""
    _center_text(im, text, GAME.cx, GAME.bottom - 60, SEMI, 38, MUTED, a, dy)


class QuickMath(_FindOne):
    """An order-of-operations trap: most people go left to right."""

    def __init__(self, level: float, rng: random.Random):
        super().__init__("Quick math", "Solve it in your **head**")
        n_ops = round(_lerp(2, 4, level))
        while True:
            n_chunks = rng.randint(2, max(2, n_ops))
            per = [0] * n_chunks
            for _ in range(n_ops - (n_chunks - 1)):
                per[rng.randrange(1, n_chunks)] += 1     # x / ÷ after a + or − (the trap)
            parts = []
            for c in range(n_chunks):
                v = rng.randint(2, 9)
                txt = str(v)
                for _ in range(per[c]):
                    divs = [d for d in range(2, 10) if v % d == 0 and v // d > 1]
                    if divs and rng.random() < 0.45:
                        d = rng.choice(divs)
                        v //= d
                        txt += f" ÷ {d}"
                    else:
                        m = rng.randint(2, 9)
                        v *= m
                        txt += f" × {m}"
                parts.append((txt, v))
            total, expr = parts[0][1], parts[0][0]
            for txt, v in parts[1:]:
                sign = "+" if rng.random() < 0.65 else "−"
                total = total + v if sign == "+" else total - v
                expr += f" {sign} {txt}"
            if 0 <= total <= 200 and any(per[1:]):
                break
        self.expr, self.answer = expr, total
        self.size = _fit(expr, HEAVY, 112, GAME.w - 20)
        self._setup_timeline()

    def draw_puzzle(self, im, a):
        _center_text(im, self.expr, GAME.cx, GAME.cy - 90, HEAVY, self.size, TEXT, a)

    def draw(self, im, t):
        super().draw(im, t)
        if t < self.reveal:
            _center_text(im, "= ?", GAME.cx, GAME.cy + 70, HEAVY, 110, MUTED, _fade(t, 0, self.APPEAR))

    def draw_answer(self, im, t):
        b = _fade(t, self.reveal, 0.25)
        _center_text(im, f"= {self.answer}", GAME.cx, GAME.cy + 70, HEAVY, 130, ACCENT, b,
                     (1 - b) * 16)
        _note(im, "× and ÷ come before + and −", b)


def _sequence(level: float, rng: random.Random) -> tuple[list[int], int, str]:
    """(shown terms, answer, rule) from a family chosen by difficulty."""
    tier = min(2, int(level * 3))
    fams = [["add", "double", "sub"], ["square", "growing", "triple"], ["fib", "alt", "prime"]][tier]
    f = rng.choice(fams)
    if f == "add":
        a, d = rng.randint(1, 20), rng.randint(3, 9)
        seq, rule = [a + d * i for i in range(6)], f"+{d} each time"
    elif f == "sub":
        d = rng.randint(3, 9)
        a = d * 6 + rng.randint(5, 30)
        seq, rule = [a - d * i for i in range(6)], f"−{d} each time"
    elif f == "double":
        a = rng.randint(1, 6)
        seq, rule = [a * 2 ** i for i in range(6)], "×2 each time"
    elif f == "triple":
        a = rng.randint(1, 3)
        seq, rule = [a * 3 ** i for i in range(6)], "×3 each time"
    elif f == "square":
        s0 = rng.randint(1, 5)
        seq, rule = [(s0 + i) ** 2 for i in range(6)], "Square numbers"
    elif f == "growing":
        a, step = rng.randint(1, 10), rng.randint(1, 3)
        seq = [a]
        for i in range(5):
            seq.append(seq[-1] + step * (i + 1))
        rule = "The gap grows by 1 each time" if step == 1 else f"The gap grows by {step} each time"
    elif f == "fib":
        x, y = rng.randint(1, 4), rng.randint(2, 6)
        seq = [x, y]
        while len(seq) < 6:
            seq.append(seq[-1] + seq[-2])
        rule = "Add the two numbers before"
    elif f == "alt":
        a, p, q = rng.randint(2, 9), rng.randint(3, 7), rng.randint(1, 2)
        seq = [a]
        for i in range(5):
            seq.append(seq[-1] + p if i % 2 == 0 else seq[-1] - q)
        rule = f"+{p}, −{q}, repeat"
    else:
        primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
        k = rng.randint(0, 6)
        seq, rule = primes[k:k + 6], "Prime numbers"
    return seq[:5], seq[5], rule


class NextNumber(_FindOne):
    def __init__(self, level: float, rng: random.Random):
        super().__init__("Next number", "What comes **next**?")
        self.terms, self.answer, self.rule = _sequence(level, rng)
        self.prefix = ",  ".join(map(str, self.terms)) + ",  "
        self.size = _fit(self.prefix + str(max(self.answer, 99)), HEAVY, 104, GAME.w - 20)
        self._setup_timeline()

    def _row(self, im, last: str, color, a, b=1.0):
        f = font(HEAVY, self.size)
        head = self.prefix.rstrip()
        w0, w1 = f.getlength(self.prefix), f.getlength(last)
        x0 = GAME.cx - (w0 + w1) / 2
        y = GAME.cy - 40
        _center_text(im, head, x0 + f.getlength(head) / 2, y, HEAVY, self.size, TEXT, a)
        _center_text(im, last, x0 + w0 + w1 / 2, y, HEAVY, self.size, color, a * b)

    def draw_puzzle(self, im, a):
        self._row(im, "?", ACCENT2, a)

    def draw(self, im, t):
        if t < self.reveal:
            self.draw_puzzle(im, _fade(t, 0, self.APPEAR))
        _timer(im, t, self.APPEAR, self.secs)
        if t >= self.reveal:
            self.draw_answer(im, t)

    def draw_answer(self, im, t):
        b = _fade(t, self.reveal, 0.25)
        self._row(im, str(self.answer), ACCENT, 1.0, b)
        _note(im, self.rule, b)


class Illusion(_FindOne):
    """Müller-Lyer lines or Ebbinghaus circles: the 'obvious' answer is usually wrong."""

    def __init__(self, level: float, rng: random.Random):
        self.kind = rng.choice(("lines", "circles"))
        self.equal = rng.random() < 0.6
        super().__init__("Optical illusion", "Which line is **longest**?" if self.kind == "lines"
                         else "Which orange circle is **bigger**?")
        ss = 3
        grid = Image.new("RGBA", (GAME.w * ss, GAME.h * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(grid)
        lab = font(HEAVY, 54 * ss)
        delta = 0 if self.equal else round(_lerp(34, 16, level))
        if self.kind == "lines":
            L, fin, w = 420, 44, 9
            order = rng.sample(["out", "in", "none"], 3)    # in = >---< (looks longest)
            self.ends = []
            for i, kind in enumerate(order):
                y = 150 + i * 200
                # the trick: when one is really longer, it's the one that LOOKS shortest (<--->)
                half = (L + (delta if kind == "out" else 0)) / 2
                x0, x1 = GAME.w / 2 - half, GAME.w / 2 + half
                self.ends.append((x0, x1))
                d.line([(x0 * ss, y * ss), (x1 * ss, y * ss)], fill=TEXT + (255,), width=w * ss)
                if kind != "none":
                    sgn = -1 if kind == "in" else 1         # fin direction relative to the line
                    for x, out in ((x0, -1), (x1, 1)):
                        for dy in (-1, 1):
                            tx, ty = x - out * sgn * fin, y + dy * fin
                            d.line([(x * ss, y * ss), (tx * ss, ty * ss)], fill=TEXT + (255,), width=w * ss)
                d.text((20 * ss, y * ss), "ABC"[i], font=lab, fill=MUTED + (255,), anchor="lm")
            self.answer = ("All three are the same length!" if self.equal else
                           f"{'ABC'[order.index('out')]} is actually the longest")
        else:
            cy = GAME.h / 2 - 50
            big_r = 52 + (round(delta * 0.4) if not self.equal else 0)  # the one among big circles
            # A's ring reaches 142 + 58 = 200 px from its centre, B's 84 + 17 = 101; the groups
            # are up to 114 px apart. Centre the pair as a whole.
            gap = max(50, min(114, GAME.w - 2 * 200 - 2 * 101 - 20))
            ax = (GAME.w - (2 * 200 + gap + 2 * 101)) / 2 + 200
            for cx, r, ring_r, dist, cnt, name in ((ax, big_r, 58, 142, 6, "A"),
                                                   (ax + 200 + gap + 101, 52, 17, 84, 8, "B")):
                for k in range(cnt):
                    ang = 2 * math.pi * k / cnt
                    x, y = cx + dist * math.cos(ang), cy + dist * math.sin(ang)
                    d.ellipse([(x - ring_r) * ss, (y - ring_r) * ss, (x + ring_r) * ss, (y + ring_r) * ss],
                              fill=ACCENT2 + (255,))
                d.ellipse([(cx - r) * ss, (cy - r) * ss, (cx + r) * ss, (cy + r) * ss],
                          fill=(255, 150, 40, 255))
                d.text((cx * ss, (cy + 245) * ss), name, font=lab, fill=MUTED + (255,), anchor="mm")
            self.answer = "They're exactly the same size!" if self.equal else "A is actually bigger"
        self.grid = grid.resize((GAME.w, GAME.h), Image.LANCZOS)
        self._setup_timeline()

    def draw_answer(self, im, t):
        b = _fade(t, self.reveal, 0.3)
        if self.kind == "lines":   # dashed guides at the shortest line's ends
            d = _Pen(im)
            x0, x1 = min(self.ends, key=lambda e: e[1] - e[0])
            for x in (x0, x1):
                X = GAME.x + x
                for y in range(GAME.y + 90, GAME.y + 610, 26):
                    d.line([(X, y), (X, y + 14)], fill=ACCENT + (int(255 * b),), width=4)
            d.flush()
        _note(im, self.answer, b)


class Scramble(_FindOne):
    def __init__(self, level: float, rng: random.Random):
        super().__init__("Word scramble", "Unscramble the **word**")
        lo, hi = round(_lerp(5, 7, level)), round(_lerp(6, 9, level))
        pool = [w for w in WORDS if lo <= len(w) <= hi] or WORDS
        self.word = history.pick_fresh(rng, pool, 1, "brain.words")[0].upper()
        self.used = {"brain.words": [self.word.lower()]}
        letters = list(self.word)
        while "".join(letters) == self.word or letters[0] == self.word[0]:
            rng.shuffle(letters)
        self.letters = letters
        n = len(letters)
        self.tile = int(min(104, (GAME.w - 14 * (n - 1)) / n))
        self._setup_timeline()

    def _tiles(self, im, text, y, fill, a, ink_col=TEXT):
        n, tile, gap = len(text), self.tile, 14
        x0 = GAME.cx - (n * tile + (n - 1) * gap) / 2
        d = _Pen(im)
        for i in range(n):
            x = x0 + i * (tile + gap)
            d.rounded_rectangle([x, y, x + tile, y + tile], tile * 0.2, fill=tuple(fill) + (int(255 * a),))
        d.flush()
        for i, ch in enumerate(text):
            x = x0 + i * (tile + gap)
            _center_text(im, ch, x + tile / 2, y + tile / 2, HEAVY, int(tile * 0.58), ink_col, a)

    def draw_puzzle(self, im, a):
        tint = (234, 230, 255) if not quiz.SURFACE_DARK else \
            tuple(int(s * 0.75 + c * 0.25) for s, c in zip(quiz.BG, ACCENT2))   # on dark cards
        self._tiles(im, self.letters, GAME.cy - 170, tint, a)       # lavender tint

    def draw_answer(self, im, t):
        b = _fade(t, self.reveal, 0.3)
        self._tiles(im, self.word, GAME.cy + 40, ACCENT, b, (255, 255, 255))


GAMES = {"stroop": Stroop, "odd_char": OddChar, "odd_colour": OddColour, "memory": Memory,
         "count": CountFlash, "shell": ShellGame, "math": QuickMath, "sequence": NextNumber,
         "illusion": Illusion, "scramble": Scramble}
GAME_TITLES = {"stroop": "Stroop test", "odd_char": "Odd one out", "odd_colour": "Colour vision",
               "memory": "Memory test", "count": "Speed count", "shell": "Shell game", "math": "Quick math",
               "sequence": "Next number", "illusion": "Optical illusion", "scramble": "Word scramble"}

# Written like a person would say them: short, no trailing full stops, no "X. Y." beats.
HOOKS = [
    "Only **3%** get all {n} right", "Most people fail round **{last}**",
    "Bet you can't get all **{n}**", "Can you pass all **{n}** rounds?",
    "Let's see how **sharp** you are", "Round **{last}** gets almost everyone",
    "Nobody gets round **{last}** on the first try", "Get all {n} and you're in the **top 5%**",
    "This is harder than it **looks**", "How fast is your **brain** today?",
    "Don't scroll until you finish all **{n}**", "Only **1 in 20** people get them all",
    "You won't get round **{last}**", "Try this without **pausing**",
    "Is your brain **faster** than average?", "Quick brain test before you **scroll**",
    "Get {n}/{n} and you're a **genius**", "Test your focus in **40 seconds**",
    "Be honest about your **score**", "Your attention span is about to get **tested**",
]
TITLES = [
    "Only 3% pass this brain test", "Can you pass all {n} rounds?", "Test your brain in 40 seconds",
    "How sharp is your brain? ({n} rounds)", "Most people fail round {last}", "Are you in the top 5%?",
]
CAPTIONS = [
    "Comment your score out of {n}", "Which round got you? Tell me in the comments",
    "Send this to the smartest person you know", "Got less than {n}? Try again before you scroll",
    "Drop your score, let's see who's sharpest",
]


# ---------------------------------------------------------------- steps
def _round_step(game: Game, idx: int, n: int, bg: Image.Image) -> tuple[Step, float]:
    base = bg.copy()
    quiz.header(base, game.label, num=idx + 1)
    quiz.footer(base, idx + 2, n + 2)
    # one line if it fits at >= 44 px (the box is one line tall), so it never runs into the
    # play area's question line
    instr = layout_text(game.instruction, Box(GAME.x, quiz.CONTENT_TOP + 6, GAME.w, 84),
                        weight=BOLD, max_size=64, min_size=44, align="center", valign="top")
    n_chars = sum(len(w.text) + 1 for w in instr.words)
    start, window = 0.15, max(0.6, min(1.3, n_chars * 0.035))
    t0 = start + window + 0.35

    def overlay(img: Image.Image, t: float) -> Image.Image:
        if t < t0:
            return img
        im = img.convert("RGBA")
        game.draw(im, min(t - t0, game.duration))   # FINAL -> the end state
        return im.convert("RGB")

    step = Step(base, [instr], overlay=overlay, sfx=[(t0 + s, name) for s, name in game.sfx],
                type_start=start, type_window=window)
    return step, t0 + game.duration


def _sheet_step(bg: Image.Image, head: str, big: str, small: str, total: int | None,
                page: int, pages: int, right: str | None = None) -> tuple[Step, float]:
    """Cover / ending: header, big line, small line, and the 'Your score ___ / 4' line."""
    base = bg.copy()
    big_l, small_l = quiz.title_sheet(base, head, big, small, total, right, page, pages,
                                     big_max=116, big_min=64)
    chars = sum(len(w.text) + 1 for lay in (big_l, small_l) for w in lay.words)
    window = max(0.9, min(2.0, chars * 0.035))
    step = Step(base, [big_l, small_l], type_start=0.2, type_window=window)
    return step, 0.2 + window + 1.4


def build(seed: int | None = None) -> tuple[list[Step], list[float], dict]:
    seed = seed if seed is not None else random.randint(0, 10_000_000)
    rng = random.Random(seed)
    lo, hi = _cfg("rounds", [3, 4])
    n = rng.randint(int(lo), int(hi))
    keys = history.pick_fresh(rng, list(GAMES), n, "brain.games")   # rotate through all 10
    levels = [i / (n - 1) if n > 1 else 0.5 for i in range(n)]
    games = [GAMES[k](lv, rng) for k, lv in zip(keys, levels)]
    max_s = float(_cfg("max_seconds", 50))
    while len(games) > 3 and sum(g.duration + 2 for g in games) + 7 > max_s:
        drop = max(range(1, len(games) - 1), key=lambda i: games[i].duration)   # keep first/last
        del games[drop], keys[drop]
    n = len(games)

    fmt = {"n": n, "last": n}
    hook = history.pick_fresh(rng, HOOKS, 1, "brain.hooks")[0]
    steps, durs = [], []
    s, d = _sheet_step(quiz.background(seed, variant=0), "Brain test", hook.format(**fmt),
                       "Keep score as you go", n, 1, n + 2)
    steps.append(s), durs.append(d)
    for i, g in enumerate(games):
        s, d = _round_step(g, i, n, quiz.background(seed, variant=i + 1))
        steps.append(s), durs.append(d)
    s, d = _sheet_step(quiz.background(seed, variant=n + 1), "Brain test",
                       "How many did you get **right**?", "Comment your score below", n,
                       n + 2, n + 2)
    steps.append(s), durs.append(d)

    used: dict[str, list] = {"brain.hooks": [hook], "brain.games": list(keys)}
    for g in games:
        for k, items in g.used.items():
            used.setdefault(k, []).extend(items)
    title = rng.choice(TITLES).format(**fmt)
    pool = list(CFG.hashtags.D) or ["#braintest"]      # first one always, then 5 of the rest
    tags = pool[:1] + rng.sample(pool[1:], min(5, len(pool) - 1))
    data = {"title": title, "hook": hook.format(**fmt).replace("**", ""),
            "games": [GAME_TITLES[k] for k in keys], "seed": seed,
            "caption": rng.choice(CAPTIONS).format(**fmt), "hashtags": tags, "_used": used}
    return steps, durs, data


def produce(debug: bool = False, seed: int | None = None) -> Path:
    steps, durs, data = build(seed)
    used = data.pop("_used")
    out = run_dir("D", data["title"])
    if debug:   # stills are only useful for checking layout (safe-zone overlay); videos don't need them
        names = ["00_cover"] + [f"{i:02d}_round{i}" for i in range(1, len(steps) - 1)] + ["99_outro"]
        for step, name in zip(steps, names):
            draw_safe_zone(full_frame(step)).save(out / f"{name}.png", optimize=True)
    d = getattr(CFG, "engine_d", None)
    track = render_video(steps, durs, out / "brain_test.mp4", getattr(d, "fps", 30),
                         getattr(d, "word_fade_ms", 120), getattr(d, "crossfade_ms", 250))
    if track:
        data["music"] = track
    for k, items in used.items():
        history.remember(k, items)
    save_meta(out, data)
    return out
