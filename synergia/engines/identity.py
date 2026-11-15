"""Engine E — Which One Are You: self-identification videos written by Claude.

Two modes:
- checklist: "7 signs you're a ..." - each sign types out and its box gets ticked; "comment your score".
- pick:      "Pick a door..." - 3-4 option cards, a short timer, then one reveal slide per option.
"""
from __future__ import annotations

import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw

from synergia import history
from synergia.brand.animate import Step, full_frame, render_video
from synergia.brand.backgrounds import make_background
from synergia.brand.canvas import SAFE, Box, draw_safe_zone
from synergia.brand.elements import _patch, draw_check, draw_timer, draw_wordmark
from synergia.brand.typography import (ACCENT, ACCENT2, MUTED, TEXT, TextLayout, draw_label, font,
                                     layout_text, strip_markup)
from synergia.config import CFG, hex_to_rgb
from synergia.llm.bridge import check_text, normalize_common
from synergia.llm.prompts import checklist_prompt, pick_prompt
from synergia.output import run_dir, save_meta

W, H = CFG.brand.width, CFG.brand.height
SHAPES = ("circle", "triangle", "square", "star", "hexagon", "diamond")
STYLES = ("numbers", "colours", "shapes", "doors")
PALETTE = [ACCENT, ACCENT2, (255, 128, 170), (70, 210, 190)]


def _cfg(name: str, default):
    return getattr(getattr(CFG, "engine_e", None), name, default)


def _chars(*lays: TextLayout) -> int:
    return sum(len(w.text) + 1 for lay in lays for w in lay.words)


def _window(n_chars: int, lo: float, hi: float) -> float:
    return max(lo, min(hi, n_chars * 0.035))


def _label_c(img: Image.Image, text: str, y: int, size: int = 32, color=ACCENT2) -> None:
    w = draw_label(Image.new("RGB", (1, 1)), text, 0, 0, size=size, tracking=0.22)
    draw_label(img, text, W // 2 - w // 2, y, size=size, color=color, tracking=0.22)


def _text_step(bg: Image.Image, label: str, big: str, small: str) -> tuple[Step, float]:
    base = bg.copy()
    draw_wordmark(base, align="center")
    big_l = layout_text(big, Box(SAFE.x, SAFE.y + 260, SAFE.w, 460), weight="black", max_size=112,
                        min_size=60, align="center", valign="bottom", line_spacing=1.1)
    small_l = layout_text(small, Box(SAFE.x, big_l.top + big_l.height + 60, SAFE.w, 200),
                          weight="medium", max_size=54, min_size=36, align="center", valign="top",
                          color=MUTED)
    _label_c(base, label, big_l.top - 70, 34)
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
    s, d = _text_step(make_background(seed, variant=0), "HOW MANY APPLY TO YOU?",
                      data["cover_title"], "Count them. **Be honest.**")
    steps.append(s), durs.append(d)

    bg = make_background(seed, variant=1)
    header = layout_text(data["cover_title"], Box(SAFE.x, SAFE.y + 20, SAFE.w, 190), weight="bold",
                         max_size=60, min_size=40, valign="top", line_spacing=1.12)
    top = header.top + header.height + 60
    area_h = SAFE.bottom - 120 - top
    row_h = min(150, area_h // n)
    box = int(min(58, row_h * 0.5))
    text_x = SAFE.x + box + 30
    rows = [layout_text(sg, Box(text_x, top + i * row_h + 6, SAFE.right - text_x, row_h - 12),
                        weight="bold", max_size=50, min_size=30, valign="center", line_spacing=1.12)
            for i, sg in enumerate(signs)]
    # one font size for every row, so the list looks even
    size = min(r.size for r in rows)
    rows = [layout_text(sg, Box(text_x, top + i * row_h + 6, SAFE.right - text_x, row_h - 12),
                        weight="bold", max_size=size, min_size=size, valign="center", line_spacing=1.12)
            for i, sg in enumerate(signs)]
    box_y = [top + i * row_h + (row_h - box) // 2 for i in range(n)]

    for i in range(n):
        base = bg.copy()
        draw_wordmark(base)
        base = header.draw(base)
        for j in range(i):
            base = rows[j].draw(base)
            base = draw_check(base, SAFE.x, box_y[j], box, 1.0)
        window = _window(_chars(rows[i]), 0.8, 1.7)
        start = 0.15
        tick = start + window + 0.15

        def overlay(img, t, i=i, tick=tick):
            img = draw_check(img, SAFE.x, box_y[i], box, 0.0, alpha=min(1.0, t / 0.2))
            if t >= tick:
                img = draw_check(img, SAFE.x, box_y[i], box, min(1.0, (t - tick) / 0.25))
            return img

        steps.append(Step(base, [rows[i]], overlay=overlay, sfx=[(tick, "pop")],
                          type_start=start, type_window=window))
        durs.append(tick + 0.25 + (1.6 if i == n - 1 else 0.55))

    s, d = _text_step(make_background(seed, variant=2), "YOUR SCORE",
                      "How many did you **check**?", f"Comment your score: **?/{n}**")
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
            f = font("black", int(r * 0.5))
            d.text((c, c - h2 * 0.32), str(i + 1), font=f, fill=(255, 255, 255, 235), anchor="mm")
        else:   # numbers
            f = font("black", int(size * s * 0.82))
            d.text((c, c), str(i + 1), font=f, fill=col + (255,), anchor="mm")

    return _patch(img, cx - box // 2, cy - box // 2, box, box, draw)


def _card(img: Image.Image, x: int, y: int, w: int, h: int, alpha: float = 1.0) -> Image.Image:
    def draw(d: ImageDraw.ImageDraw, s: int) -> None:
        d.rounded_rectangle([2 * s, 2 * s, (w - 2) * s, (h - 2) * s], radius=34 * s,
                            fill=(255, 255, 255, int(16 * alpha)),
                            outline=(255, 255, 255, int(46 * alpha)), width=2 * s)
    return _patch(img, x, y, w, h, draw)


def _pick_steps(data: dict, seed: int) -> tuple[list[Step], list[float]]:
    opts, style = data["options"], data["style"]
    n = len(opts)
    steps, durs = [], []

    # ---- cover: setup line typed, then cards pop in, then a short timer
    base = make_background(seed, variant=0)
    draw_wordmark(base, align="center")
    title = layout_text(data["cover_title"], Box(SAFE.x, SAFE.y + 40, SAFE.w, 220), weight="black",
                        max_size=76, min_size=48, align="center", valign="top", line_spacing=1.1)
    area = Box(SAFE.x, title.top + title.height + 60, SAFE.w, 0)
    if n == 4:
        cw, ch, gap = 405, 290, 30
        cells = [(area.x + (k % 2) * (cw + gap), area.y + (k // 2) * (ch + gap)) for k in range(4)]
    else:
        cw, ch, gap = 260, 420, 30
        cells = [(area.x + k * (cw + gap), area.y) for k in range(3)]
    grid_bottom = max(y for _, y in cells) + ch
    labels = [layout_text(o["label"], Box(x + 16, y + ch - 96, cw - 32, 70), weight="bold",
                          max_size=44, min_size=28, align="center", valign="center")
              for (x, y), o in zip(cells, opts)]
    prompt = layout_text("Pick one. **Remember it.**", Box(SAFE.x, grid_bottom + 34, SAFE.w, 80),
                         weight="semibold", max_size=50, min_size=36, align="center", valign="top",
                         color=MUTED)
    window = _window(_chars(title), 1.0, 2.0)
    t_cards = 0.15 + window + 0.3
    stagger = 0.18
    t_prompt = t_cards + n * stagger + 0.2
    secs = int(_cfg("pick_timer_seconds", 3))
    t_timer = t_prompt + 0.35
    timer_c = (W // 2, min(SAFE.bottom - 110, int(prompt.top + prompt.height + 95)))

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
            draw_timer(im, *timer_c, 50, left / secs, math.ceil(left - 1e-6))
        return im.convert("RGB")

    steps.append(Step(base, [title], overlay=cover_overlay,
                      sfx=[(t_cards + k * stagger, "pop") for k in range(n)] +
                          [(t_timer + i, "tick") for i in range(secs)],
                      type_start=0.15, type_window=window))
    durs.append(t_timer + secs + 0.15)

    # ---- one reveal per option
    for k, o in enumerate(opts):
        base = make_background(seed, variant=k + 1)
        draw_wordmark(base, align="center")
        _label_c(base, "IF YOU PICKED", SAFE.y + 50, 30, MUTED)
        base = draw_symbol(base, style, k, o, W // 2, SAFE.y + 290, 330)
        lab = layout_text(o["label"], Box(SAFE.x, SAFE.y + 480, SAFE.w, 110), weight="black",
                          max_size=84, min_size=52, align="center", valign="top", all_accent=True)
        trait = layout_text(o["trait"], Box(SAFE.x, lab.top + lab.height + 70, SAFE.w,
                                            SAFE.bottom - 140 - (lab.top + lab.height + 70)),
                            weight="bold", max_size=66, min_size=42, align="center", valign="top",
                            line_spacing=1.2)
        base = lab.draw(base)
        window = _window(_chars(trait), 1.2, 2.8)
        steps.append(Step(base, [trait], sfx=[(0.0, "whoosh")], type_start=0.3, type_window=window))
        durs.append(0.3 + window + float(_cfg("reveal_seconds", 2.2)))

    s, d = _text_step(make_background(seed, variant=n + 1), "YOUR TURN",
                      "Which one did you **pick**?", "Comment below. **Be honest.**")
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
