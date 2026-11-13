"""Engine A — 10-Second Psychology Explainer: 4 PNG frames + ~11s 9:16 MP4 with word-by-word reveal."""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from synergia.brand.backgrounds import make_background
from synergia.brand.canvas import SAFE, Box, draw_safe_zone
from synergia.brand.elements import draw_wordmark
from synergia.brand.typography import (ACCENT, ACCENT2, MUTED, TextLayout, draw_label, layout_text,
                                       strip_markup)
from synergia.config import CFG
from synergia.llm.bridge import check_text, normalize_common, words
from synergia.llm.prompts import psychology_prompt
from synergia.output import run_dir, save_meta
from synergia.video import FrameWriter

LIMITS = {"hook_line": 10, "gotcha": 40, "mechanism": 35, "shift": 20}
REF_WORDS = [12, 34, 30, 16]          # word counts the base durations are tuned for
STEP_LABELS = ["", "THE MIRROR", "THE MECHANISM", "THE SHIFT"]
STEP_FILES = ["01_hook", "02_mirror", "03_mechanism", "04_shift"]


def prompt(concept: str) -> str:
    return psychology_prompt(concept)


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    if not str(data.get("concept") or "").strip():
        errors.append('"concept" is missing')
    for k, lim in LIMITS.items():
        check_text(data, k, lim, errors)
    if not errors:
        normalize_common(data)
    return errors


def review_fields(_: dict) -> list[tuple[str, str]]:
    return [("Concept", "concept"), ("1. Hook line", "hook_line"), ("2. Gotcha", "gotcha"),
            ("3. Mechanism", "mechanism"), ("4. Shift", "shift"), ("Caption", "caption")]


# ---------------------------------------------------------------- frame composition
@dataclass
class Step:
    base: Image.Image            # background + static elements
    layouts: list[TextLayout]    # text revealed word by word, in order


def _content_box() -> Box:
    return Box(SAFE.x, SAFE.y + 130, SAFE.w, SAFE.h - 230)


def _step_header(img: Image.Image, idx: int, box: Box) -> None:
    draw_label(img, f"{idx + 1:02d}", box.x, box.y, size=34, color=MUTED, tracking=0.1)
    draw_label(img, STEP_LABELS[idx], box.x + 78, box.y, size=34, color=ACCENT2, tracking=0.22)


def build_steps(data: dict, bg: Image.Image) -> list[Step]:
    steps: list[Step] = []
    box = _content_box()

    # 1 — Hook: concept name (blue) + "explained in 10 seconds" + hook line.
    base = bg.copy()
    draw_wordmark(base)

    def hook_stack(top: int):
        c = layout_text(data["concept"], Box(box.x, top, box.w, int(box.h * 0.40)),
                        weight="black", max_size=124, min_size=64, valign="top",
                        line_spacing=1.08, all_accent=True)
        label_y = c.top + c.height + 70
        hl = layout_text(data["hook_line"], Box(box.x, label_y + 60, box.w, int(box.h * 0.30)),
                         weight="bold", max_size=78, min_size=48, valign="top", line_spacing=1.16)
        return c, label_y, hl, (hl.top + hl.height) - top

    *_, total = hook_stack(box.y)
    top = box.y + max(0, (box.h - total) // 2 - 30)
    concept, label_y, hook_line, _ = hook_stack(top)
    draw_label(base, "EXPLAINED IN 10 SECONDS", box.x, label_y, size=32, color=MUTED,
               tracking=0.22)
    steps.append(Step(base, [concept, hook_line]))

    # 2 & 3 — Mirror and Mechanism.
    for idx, key in ((1, "gotcha"), (2, "mechanism")):
        base = bg.copy()
        draw_wordmark(base)
        text_box = Box(box.x, box.y + 110, box.w, box.h - 140)
        lay = layout_text(data[key], text_box, weight="bold", max_size=84, min_size=46,
                          valign="center", line_spacing=1.2)
        _step_header(base, idx, Box(box.x, lay.top - 70, box.w, 0))
        steps.append(Step(base, [lay]))

    # 4 — Shift: biggest, centered.
    base = bg.copy()
    draw_wordmark(base, align="center")
    lay = layout_text(data["shift"], Box(box.x, box.y + 110, box.w, box.h - 140), weight="black",
                      max_size=100, min_size=52, align="center", valign="center",
                      line_spacing=1.14)
    w = draw_label(Image.new("RGB", (1, 1)), "THE SHIFT", 0, 0, size=34, tracking=0.22)
    draw_label(base, "THE SHIFT", box.cx - w // 2, lay.top - 80, size=34, color=ACCENT2,
               tracking=0.22)
    steps.append(Step(base, [lay]))
    return steps


def full_frame(step: Step) -> Image.Image:
    img = step.base
    for lay in step.layouts:
        img = lay.draw(img)
    return img


# ---------------------------------------------------------------- video
def _durations(data: dict) -> list[float]:
    base = CFG.engine_a.durations
    out = []
    for i, key in enumerate(("hook_line", "gotcha", "mechanism", "shift")):
        n = words(data[key]) + (words(data["concept"]) if i == 0 else 0)
        scale = min(1.45, max(0.8, n / REF_WORDS[i]))
        out.append(base[i] * scale)
    return out


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def render_video(steps: list[Step], durations: list[float], path: Path) -> None:
    a = CFG.engine_a
    fps = a.fps
    fade = a.word_fade_ms / 1000
    xfade_frames = max(1, int(a.crossfade_ms / 1000 * fps))
    W, H = CFG.brand.width, CFG.brand.height
    prev_last: Image.Image | None = None

    with FrameWriter(path, W, H, fps) as fw:
        for step, dur in zip(steps, durations):
            n_frames = int(round(dur * fps))
            counts = [len(l.words) for l in step.layouts]
            total_words = sum(counts)
            # Reveal over ~55% of the segment, but never slower than 0.22s/word.
            window = min(dur * 0.55, total_words * 0.22)
            per = window / max(1, total_words)
            last = None
            for f in range(n_frames):
                t = f / fps
                img = step.base
                k = 0
                for lay, c in zip(step.layouts, counts):
                    alphas, offs = [], []
                    for _ in range(c):
                        p = min(1.0, max(0.0, (t - k * per) / fade))
                        e = _ease_out(p)
                        alphas.append(e)
                        offs.append((1 - e) * 22)
                        k += 1
                    img = lay.draw(img, alphas, offs)
                if prev_last is not None and f < xfade_frames:
                    img = Image.blend(prev_last, img, (f + 1) / (xfade_frames + 1))
                fw.write(img)
                last = img
            prev_last = last


# ---------------------------------------------------------------- produce
def produce(data: dict, debug: bool = False, video: bool = True) -> Path:
    out = run_dir("A", strip_markup(data["concept"]))
    seed = random.randint(0, 10_000_000)
    bg = make_background(seed)
    steps = build_steps(data, bg)
    for step, name in zip(steps, STEP_FILES):
        img = full_frame(step)
        if debug:
            img = draw_safe_zone(img)
        img.save(out / f"{name}.png", optimize=True)
    if video:
        render_video(steps, _durations(data), out / "explainer.mp4")
    save_meta(out, data)
    return out
