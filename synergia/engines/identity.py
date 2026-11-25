"""Engine E — Which One Are You: self-identification videos written by Claude.

Two modes:
- checklist: "7 signs you're a ..." - each sign types out and its box gets ticked; "comment your score".
- pick:      "Pick a door..." - 3-4 option cards, a short timer, then one reveal slide per option.
"""
from __future__ import annotations

import math
import random
import re
from functools import partial
from pathlib import Path

from PIL import Image, ImageDraw

from synergia import history
from synergia.brand.animate import Step, full_frame, render_video
from synergia.brand.canvas import SAFE, Box, centred_top, draw_safe_zone
from synergia.brand import quiz, typography
from synergia.brand.elements import _patch, draw_check, draw_timer
from synergia.brand.quiz import ACCENT, ACCENT2, BOLD, HEAVY, MUTED, SEMI, TEXT
from synergia.brand.typography import TextLayout, font, strip_markup
from synergia.config import CFG, hex_to_rgb
from synergia.llm.bridge import check_text, normalize_common
from synergia.llm.prompts import checklist_prompt, pick_prompt
from synergia.output import run_dir, save_meta

W, H = CFG.brand.width, CFG.brand.height
layout_text = partial(typography.layout_text, color=TEXT, accent_color=ACCENT)   # quiz colours
SHAPES = ("circle", "triangle", "square", "star", "hexagon", "diamond")
STYLES = ("numbers", "colours", "shapes", "doors")
PALETTE = [ACCENT, ACCENT2, (255, 128, 170), (70, 210, 190)]


def _cfg(name: str, default):
    return getattr(getattr(CFG, "engine_e", None), name, default)


def _chars(*lays: TextLayout) -> int:
    return sum(len(w.text) + 1 for lay in lays for w in lay.words)


def _window(n_chars: int, lo: float, hi: float) -> float:
    return max(lo, min(hi, n_chars * 0.035))


HEAD = "Quick quiz"            # header on every slide


def _sheet_step(bg: Image.Image, big: str, small: str, total: int | None, page: int,
                pages: int) -> tuple[Step, float]:
    """Cover / ending: header, big line, small line, optional 'Your score ___ / 7' line."""
    base = bg.copy()
    big_l, small_l = quiz.title_sheet(base, HEAD, big, small, total, None, page, pages,
                                     big_max=108, big_min=60)
    window = _window(_chars(big_l, small_l), 1.0, 2.2)
    return Step(base, [big_l, small_l], type_start=0.2, type_window=window), 0.2 + window + 1.6


def _render(steps: list[Step], durs: list[float], out: Path, video: str, names: list[str],
            debug: bool, data: dict) -> Path:
    for step, name in zip(steps, names):
        img = full_frame(step)
        if debug:
            img = draw_safe_zone(img)
        img.save(out / f"{name}.png", optimize=True)
    track = render_video(steps, durs, out / video, int(_cfg("fps", 30)),
                         int(_cfg("word_fade_ms", 120)), int(_cfg("crossfade_ms", 250)))
    if track:
        data["music"] = track
    history.remember("identity.topics", [data.get("topic") or strip_markup(data["cover_title"])])
    save_meta(out, data)
    return out


# ================================================================ checklist
class Checklist:
    """Engine-like namespace for cli._script_loop: prompt / validate / review_fields."""

    @staticmethod
    def prompt(topic: str) -> str:
        return checklist_prompt(topic, random.randint(5, 8))

    @staticmethod
    def validate(data: dict) -> list[str]:
        errors: list[str] = []
        check_text(data, "cover_title", 12, errors)
        signs = data.get("signs")
        if not isinstance(signs, list) or not 5 <= len(signs) <= 8:
            errors.append('"signs" must be a list of 5 to 8 items')
        else:
            for i, s in enumerate(signs, 1):
                e: list[str] = []
                check_text({"sign": s}, "sign", 9, e)
                errors += [f"sign {i}: {x}" for x in e]
        if not errors:
            normalize_common(data)
            data["signs"] = [str(s).strip().rstrip(".") for s in signs]
            if not data["title"]:
                data["title"] = strip_markup(data["cover_title"])
        return errors

    @staticmethod
    def review_fields(data: dict) -> list[tuple[str, str]]:
        f = [("Post title", "title"), ("Cover title", "cover_title")]
        f += [(f"Sign {i + 1}", f"signs.{i}") for i in range(len(data.get("signs", [])))]
        return f + [("Caption", "caption")]


def _checklist_steps(data: dict, seed: int) -> tuple[list[Step], list[float]]:
    signs = data["signs"]
    n = len(signs)
    steps, durs = [], []
    s, d = _sheet_step(quiz.background(seed, variant=0), data["cover_title"],
                       "Count how many sound like **you**", n, 1, n + 2)
    steps.append(s), durs.append(d)

    # The list sits left-aligned under the header, centred vertically in the space left.
    bg = quiz.background(seed, variant=1)
    header = layout_text(data["cover_title"], Box(quiz.INNER.x, 0, quiz.INNER.w, 190), weight=BOLD,
                         max_size=60, min_size=40, valign="top", line_spacing=1.12)
    head_gap, row_gap = 56, 26
    area_h = quiz.AREA.h - header.height - head_gap
    slot = min(150, area_h // n)
    box = int(min(58, slot * 0.5))
    text_w = quiz.INNER.w - box - 30
    rows = [layout_text(sg, Box(0, 0, text_w, slot - row_gap), weight=BOLD, max_size=50,
                        min_size=30, valign="top", line_spacing=1.12) for sg in signs]
    # one font size for every row, so the list looks even
    size = min(r.size for r in rows)
    rows = [layout_text(sg, Box(0, 0, text_w, slot - row_gap), weight=BOLD, max_size=size,
                        min_size=size, valign="top", line_spacing=1.12) for sg in signs]
    row_hs = [max(r.height, box) for r in rows]
    block_h = header.height + head_gap + sum(row_hs) + row_gap * (n - 1)
    left = quiz.INNER.x
    y = centred_top(block_h, quiz.AREA)
    header = header.moved(dx=left - quiz.INNER.x, dy=y)
    y += header.height + head_gap
    text_x = left + box + 30
    box_y = []
    for i, r in enumerate(rows):
        rows[i] = r.moved(dx=text_x, dy=y + (row_hs[i] - r.height) // 2)
        box_y.append(y + (row_hs[i] - box) // 2)
        y += row_hs[i] + row_gap

    for i in range(n):
        base = bg.copy()
        quiz.header(base, HEAD)
        quiz.footer(base, i + 2, n + 2)
        base = header.draw(base)
        for j in range(i):
            base = rows[j].draw(base)
            base = draw_check(base, left, box_y[j], box, 1.0)
        window = _window(_chars(rows[i]), 0.8, 1.7)
        start = 0.15
        tick = start + window + 0.15

        def overlay(img, t, i=i, tick=tick):
            img = draw_check(img, left, box_y[i], box, 0.0, alpha=min(1.0, t / 0.2))
            if t >= tick:
                img = draw_check(img, left, box_y[i], box, min(1.0, (t - tick) / 0.25))
            return img

        steps.append(Step(base, [rows[i]], overlay=overlay, sfx=[(tick, "pop")],
                          type_start=start, type_window=window))
        durs.append(tick + 0.25 + (1.6 if i == n - 1 else 0.55))

    s, d = _sheet_step(quiz.background(seed, variant=2), "How many did you **check**?",
                       "Comment your score below", n, n + 2, n + 2)
    steps.append(s), durs.append(d)
    return steps, durs


def produce_checklist(data: dict, debug: bool = False) -> Path:
    seed = random.randint(0, 10_000_000)
    steps, durs = _checklist_steps(data, seed)
    out = run_dir("E", data["title"])
    names = ["01_cover"] + [f"{i + 2:02d}_sign{i + 1}" for i in range(len(steps) - 2)] + ["99_outro"]
    # Only keep the cover, the full list and the outro as PNGs.
    keep = {0, len(steps) - 2, len(steps) - 1}
    steps_png = [s for i, s in enumerate(steps) if i in keep]
    names_png = ["01_cover", "02_checklist", "03_outro"]
    for step, name in zip(steps_png, names_png):
        img = full_frame(step)
        if debug:
            img = draw_safe_zone(img)
        img.save(out / f"{name}.png", optimize=True)
    return _render(steps, durs, out, "identity.mp4", [], debug, data)


# ================================================================ pick one
class Pick:
    @staticmethod
    def prompt(topic: str) -> str:
        return pick_prompt(topic, random.choice((3, 4, 4)))

    @staticmethod
    def validate(data: dict) -> list[str]:
        errors: list[str] = []
        check_text(data, "cover_title", 12, errors)
        style = str(data.get("style") or "").lower().strip()
        style = {"colors": "colours", "color": "colours", "number": "numbers", "door": "doors",
                 "shape": "shapes"}.get(style, style)
        if style not in STYLES:
            errors.append(f'"style" must be one of {", ".join(STYLES)}')
        opts = data.get("options")
        if not isinstance(opts, list) or len(opts) not in (3, 4):
            errors.append('"options" must be a list of 3 or 4 items')
            return errors
        shapes = []
        for i, o in enumerate(opts, 1):
            if not isinstance(o, dict):
                errors.append(f"option {i} must be an object")
                continue
            e: list[str] = []
            check_text(o, "label", 3, e)
            check_text(o, "trait", 25, e)
            if style == "colours" and not re.fullmatch(r"#?[0-9a-fA-F]{6}", str(o.get("color", ""))):
                e.append('"color" must be a hex colour like "#4F8CFF"')
            if style == "shapes":
                sh = str(o.get("shape", "")).lower().strip()
                if sh not in SHAPES:
                    e.append(f'"shape" must be one of {", ".join(SHAPES)}')
                shapes.append(sh)
            errors += [f"option {i}: {x}" for x in e]
        if style == "shapes" and len(set(shapes)) != len(shapes):
            errors.append("every option needs a different shape")
        if not errors:
            normalize_common(data)
            data["style"] = style
            for o in opts:
                if style == "colours":
                    o["color"] = "#" + str(o["color"]).lstrip("#")
                if style == "shapes":
                    o["shape"] = str(o["shape"]).lower().strip()
            if not data["title"]:
                data["title"] = strip_markup(data["cover_title"])
        return errors

    @staticmethod
    def review_fields(data: dict) -> list[tuple[str, str]]:
        f = [("Post title", "title"), ("Cover title", "cover_title")]
        for i in range(len(data.get("options", []))):
            f += [(f"Option {i + 1}", f"options.{i}.label"), (f"  reveals", f"options.{i}.trait")]
        return f + [("Caption", "caption")]


def _shape_points(shape: str, cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    def poly(n, rot, rr=None):
        return [(cx + (rr or r) * math.cos(rot + 2 * math.pi * k / n),
                 cy + (rr or r) * math.sin(rot + 2 * math.pi * k / n)) for k in range(n)]
    if shape == "triangle":
        return poly(3, -math.pi / 2, r * 1.12)
    if shape == "square":
        return poly(4, math.pi / 4, r * 1.1)
    if shape == "hexagon":
        return poly(6, 0)
    if shape == "diamond":
        return [(cx, cy - r * 1.15), (cx + r * 0.8, cy), (cx, cy + r * 1.15), (cx - r * 0.8, cy)]
    if shape == "star":
        pts = []
        for k in range(10):
            rr = r * 1.12 if k % 2 == 0 else r * 0.5
            a = -math.pi / 2 + math.pi * k / 5
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        return pts
    return []


def draw_symbol(img: Image.Image, style: str, i: int, opt: dict, cx: int, cy: int,
                size: int) -> Image.Image:
    """The option's symbol, centred at (cx, cy), fitting a size x size square."""
    col = hex_to_rgb(opt["color"]) if style == "colours" else PALETTE[i % len(PALETTE)]
    pad = 8
    box = size + 2 * pad

    def draw(d: ImageDraw.ImageDraw, s: int) -> None:
        c = box * s / 2
        r = size * s * 0.42
        if style == "colours":
            d.ellipse([c - r * 1.12, c - r * 1.12, c + r * 1.12, c + r * 1.12], fill=col + (60,))
            d.ellipse([c - r, c - r, c + r, c + r], fill=col + (255,))
        elif style == "shapes":
            if opt["shape"] == "circle":
                d.ellipse([c - r, c - r, c + r, c + r], fill=col + (255,))
            else:
                d.polygon(_shape_points(opt["shape"], c, c, r), fill=col + (255,))
        elif style == "doors":
            w2, h2 = r * 0.72, r * 1.05
            d.rounded_rectangle([c - w2, c - h2, c + w2, c + h2], radius=w2 * 0.9, fill=col + (255,))
            panel = tuple(int(v * 0.78) for v in col) + (255,)   # recessed door panel
            d.rounded_rectangle([c - w2 * 0.72, c - h2 * 0.8, c + w2 * 0.72, c + h2 * 0.92],
                                radius=w2 * 0.6, fill=panel)
            kr = r * 0.075
            d.ellipse([c + w2 * 0.38 - kr, c + h2 * 0.1 - kr, c + w2 * 0.38 + kr, c + h2 * 0.1 + kr],
                      fill=(255, 230, 150, 255))
            f = font(HEAVY, int(r * 0.5))
            d.text((c, c - h2 * 0.32), str(i + 1), font=f, fill=(255, 255, 255, 235), anchor="mm")
        else:   # numbers
            f = font(HEAVY, int(size * s * 0.82))
            d.text((c, c), str(i + 1), font=f, fill=col + (255,), anchor="mm")

    return _patch(img, cx - box // 2, cy - box // 2, box, box, draw)


def _card(img: Image.Image, x: int, y: int, w: int, h: int, alpha: float = 1.0) -> Image.Image:
    def draw(d: ImageDraw.ImageDraw, s: int) -> None:
        d.rounded_rectangle([2 * s, 2 * s, (w - 2) * s, (h - 2) * s], radius=34 * s,
                            fill=TEXT + (int(10 * alpha),),
                            outline=TEXT + (int(34 * alpha),), width=2 * s)
    return _patch(img, x, y, w, h, draw)


def _pick_steps(data: dict, seed: int) -> tuple[list[Step], list[float]]:
    opts, style = data["options"], data["style"]
    n = len(opts)
    steps, durs = [], []

    # ---- cover: setup line typed, then cards pop in, then a short timer
    # Title, cards, prompt and the timer's space are centred as one block.
    base = quiz.background(seed, variant=0)
    quiz.header(base, HEAD)
    quiz.footer(base, 1, n + 2)
    title = layout_text(data["cover_title"], Box(quiz.INNER.x, 0, quiz.INNER.w, 220), weight=HEAVY,
                        max_size=72, min_size=48, align="center", valign="top", line_spacing=1.1)
    gap = 30
    if n == 4:
        cw, ch = (quiz.INNER.w - gap) // 2, 250
        grid_w, grid_h = 2 * cw + gap, 2 * ch + gap
    else:
        cw, ch = (quiz.INNER.w - 2 * gap) // 3, 420
        grid_w, grid_h = 3 * cw + 2 * gap, ch
    prompt = layout_text("Pick one and **remember it**", Box(quiz.INNER.x, 0, quiz.INNER.w, 80),
                         weight=SEMI, max_size=50, min_size=36, align="center", valign="top",
                         color=MUTED)
    timer_r, timer_gap = 50, 82            # timer centre sits timer_gap below the prompt
    block_h = title.height + 50 + grid_h + 30 + prompt.height + timer_gap + timer_r + 12
    top = centred_top(block_h, quiz.AREA)
    title = title.moved(dy=top)
    gx, gy = W // 2 - grid_w // 2, title.top + title.height + 50
    if n == 4:
        cells = [(gx + (k % 2) * (cw + gap), gy + (k // 2) * (ch + gap)) for k in range(4)]
    else:
        cells = [(gx + k * (cw + gap), gy) for k in range(3)]
    prompt = prompt.moved(dy=gy + grid_h + 30)
    labels = [layout_text(o["label"], Box(x + 16, y + ch - 96, cw - 32, 70), weight=BOLD,
                          max_size=44, min_size=28, align="center", valign="center")
              for (x, y), o in zip(cells, opts)]
    window = _window(_chars(title), 1.0, 2.0)
    t_cards = 0.15 + window + 0.3
    stagger = 0.18
    t_prompt = t_cards + n * stagger + 0.2
    secs = int(_cfg("pick_timer_seconds", 3))
    t_timer = t_prompt + 0.35
    timer_c = (W // 2, min(SAFE.bottom - 124, prompt.top + prompt.height + timer_gap))

    def cover_overlay(img, t):
        im = img.convert("RGBA")
        for k, ((x, y), o) in enumerate(zip(cells, opts)):
            a = max(0.0, min(1.0, (t - t_cards - k * stagger) / 0.2))
            if a <= 0:
                continue
            _card(im, x, y, cw, ch, a)
            if a >= 1:   # the card fades in, then its symbol and label pop on
                sym = int(min(cw, ch - 110) * 0.78)
                draw_symbol(im, style, k, o, x + cw // 2, y + (ch - 90) // 2 + 4, sym)
                _paste_layout(im, labels[k])
        if t >= t_prompt:
            _paste_layout(im, prompt, min(1.0, (t - t_prompt) / 0.25))
        if t_timer <= t < t_timer + secs:
            left = t_timer + secs - t
            draw_timer(im, *timer_c, timer_r, left / secs, math.ceil(left - 1e-6))
        return im.convert("RGB")

    steps.append(Step(base, [title], overlay=cover_overlay,
                      sfx=[(t_cards + k * stagger, "pop") for k in range(n)] +
                          [(t_timer + i, "tick") for i in range(secs)],
                      type_start=0.15, type_window=window))
    durs.append(t_timer + secs + 0.15)

    # ---- one reveal per option
    for k, o in enumerate(opts):
        # label, symbol, option name and trait, centred as one block
        base = quiz.background(seed, variant=k + 1)
        quiz.header(base, "If you picked")
        quiz.footer(base, k + 2, n + 2)
        sym = 330
        lab = layout_text(o["label"], Box(quiz.INNER.x, 0, quiz.INNER.w, 110), weight=HEAVY,
                          max_size=84, min_size=52, align="center", valign="top", all_accent=True)
        head_h = sym + 25                       # symbol, gap
        trait_y = head_h + lab.height + 70
        trait = layout_text(o["trait"], Box(quiz.INNER.x, 0, quiz.INNER.w, quiz.AREA.h - trait_y),
                            weight=BOLD, max_size=66, min_size=42, align="center", valign="top",
                            line_spacing=1.2)
        top = centred_top(trait_y + trait.height, quiz.AREA)
        base = draw_symbol(base, style, k, o, W // 2, top + sym // 2, sym)
        lab = lab.moved(dy=top + head_h)
        trait = trait.moved(dy=top + trait_y)
        base = lab.draw(base)
        window = _window(_chars(trait), 1.2, 2.8)
        steps.append(Step(base, [trait], sfx=[(0.0, "whoosh")], type_start=0.3, type_window=window))
        durs.append(0.3 + window + float(_cfg("reveal_seconds", 2.2)))

    s, d = _sheet_step(quiz.background(seed, variant=n + 1), "Which one did you **pick**?",
                       "Tell me in the comments", None, n + 2, n + 2)
    steps.append(s), durs.append(d)
    return steps, durs


def _paste_layout(im: Image.Image, lay: TextLayout, alpha: float = 1.0) -> None:
    for i in range(len(lay.words)):
        spr, x, y = lay.sprite(i)
        if alpha < 1:
            spr = spr.copy()
            spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
        im.alpha_composite(spr, (x, y))


def produce_pick(data: dict, debug: bool = False) -> Path:
    seed = random.randint(0, 10_000_000)
    steps, durs = _pick_steps(data, seed)
    out = run_dir("E", data["title"])
    names = ["01_cover"] + [f"{i + 2:02d}_option{i + 1}" for i in range(len(steps) - 2)] + ["99_outro"]
    return _render(steps, durs, out, "identity.mp4", names, debug, data)
