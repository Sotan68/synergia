"""Engine A — 10-second explainer (hook + 3 steps): 4 PNG frames + ~11s 9:16 MP4 with letter-by-letter typing.

The step labels, the slide-1 label and the title template come from [engine_a.wording] in the
profile (e.g. "The mirror / The mechanism / The shift" for psychology)."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

from synergia.brand import paper
from synergia.brand.animate import Step, full_frame, render_video, scaled_duration
from synergia.brand.canvas import CENTRE, Box, draw_safe_zone, safe_for
from synergia.brand.typography import font, layout_text, strip_markup
from synergia import history
from synergia.config import CFG
from synergia.llm.bridge import check_text, normalize_common, words
from synergia.llm.prompts import psychology_prompt
from synergia.output import run_dir, save_meta

LIMITS = {"hook_line": 10, "gotcha": 40, "mechanism": 35, "shift": 20}
REF_WORDS = [12, 34, 30, 16]          # word counts the base durations are tuned for
STEP_FILES = ["01_hook", "02_mirror", "03_mechanism", "04_shift"]


def prompt(concept: str) -> str:
    return psychology_prompt(concept)


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    if not str(data.get("concept") or "").strip():
        errors.append('"concept" is missing')
    for k, lim in LIMITS.items():
        check_text(data, k, lim, errors)
    if len(str(data.get("title") or "")) > 100:
        errors.append('"title" must be at most 100 characters')
    if not errors:
        normalize_common(data)
        if not data["title"]:
            data["title"] = CFG.engine_a.wording.title_template.format(
                concept=strip_markup(data["concept"]))
    return errors


def review_fields(_: dict) -> list[tuple[str, str]]:
    return [("Post title", "title"), ("Concept", "concept"), ("1. Hook line", "hook_line"), ("2. Gotcha", "gotcha"),
            ("3. Mechanism", "mechanism"), ("4. Shift", "shift"), ("Caption", "caption")]


# ---------------------------------------------------------------- frame composition
# The "paper" look (synergia.brand.paper): serif headlines, Inter Display text, blue serif italic
# for **highlighted** words, a section header with a hairline rule, page count in the footer.
STEP_NAMES = ["", *CFG.engine_a.wording.step_labels]


def _column(img: Image.Image) -> Box:
    """The text column: the safe zone, or a column centred on screen for centred themes."""
    safe = safe_for(img.height)
    return Box(CENTRE.x, safe.y, CENTRE.w, safe.h) if paper.CENTRED else safe


def _body_box(img: Image.Image) -> Box:
    """Area for the text block under the section header and above the footer."""
    col = _column(img)
    top = col.y + 150
    return Box(col.x, top, col.w, col.bottom - 110 - top)


def _centred(top_area: int, bottom_area: int, height: int, lift: int = 30) -> int:
    """Top y centring a block of `height` between two y's, nudged up a little (optical centre)."""
    return top_area + max(0, (bottom_area - top_area - height) // 2 - lift)


def build_steps(data: dict, seed: int) -> list[Step]:
    from synergia.brand import layouts
    if layouts.active():                    # the theme has its own blueprint
        return layouts.build_a(data, seed, STEP_NAMES)
    steps: list[Step] = []

    # 1 - Hook: concept in large serif, the intro label ("Explained in 10 seconds"), the hook line.
    base = paper.background(seed, variant=0)
    safe = _column(base)
    concept = layout_text(data["concept"], Box(safe.x, 0, safe.w, 470), weight=paper.SERIF,
                          max_size=172, min_size=84, valign="top", line_spacing=0.98,
                          align=paper.ALIGN, **paper.highlight("headline"))
    hook = layout_text(data["hook_line"], Box(safe.x, 0, safe.w, 300), weight=paper.STRONG_W,
                       max_size=70, min_size=48, valign="top", line_spacing=1.18,
                       align=paper.ALIGN, **paper.highlight("text"))
    gap_label, gap_hook = 76, 72
    total = concept.height + gap_label + gap_hook + hook.height
    top = _centred(safe.y, safe.bottom - 110, total)
    concept = concept.moved(dy=top)
    label_y = concept.top + concept.height + gap_label - 20
    hook = hook.moved(dy=concept.top + concept.height + gap_label + gap_hook - 10)
    ImageDraw.Draw(base).text((base.width // 2 if paper.CENTRED else safe.x, label_y),
                              CFG.engine_a.wording.intro_label, font=font(paper.TEXT_W, 36),
                              fill=paper.ACCENT2, anchor="ms" if paper.CENTRED else "ls")
    paper.footer(base, 1, 4)
    steps.append(Step(base, [concept, hook]))

    # 2 & 3 - Mirror and Mechanism: section header, then the paragraph. One font for the whole
    # slide ([fonts] paragraph); highlighted words only change colour.
    for idx, key in ((1, "gotcha"), (2, "mechanism")):
        base = paper.background(seed, variant=idx)
        paper.section_header(base, idx + 1, STEP_NAMES[idx], face=paper.PARA_W, size=36)
        box = _body_box(base)
        lay = layout_text(data[key], Box(box.x, 0, box.w, box.h - 60), weight=paper.PARA_W,
                          max_size=84, min_size=44, valign="top", line_spacing=1.24,
                          align=paper.ALIGN, **paper.highlight("paragraph"))
        lay = lay.moved(dy=_centred(box.y, box.bottom, lay.height))
        paper.footer(base, idx + 1, 4)
        steps.append(Step(base, [lay]))

    # 4 - Shift: a centred serif statement on its own.
    base = paper.background(seed, variant=3)
    safe = safe_for(base.height)
    col = Box(CENTRE.x, 0, CENTRE.w, 760)
    lay = layout_text(data["shift"], col, weight=paper.SERIF, max_size=112, min_size=60,
                      align="center", valign="top", line_spacing=1.04,
                      **paper.highlight("headline"))
    lay = lay.moved(dy=_centred(safe.y, safe.bottom - 110, lay.height))
    paper.footer(base, align="center")
    steps.append(Step(base, [lay]))
    return steps


# ---------------------------------------------------------------- video
def _durations(data: dict) -> list[float]:
    base = CFG.engine_a.durations
    out = []
    for i, key in enumerate(("hook_line", "gotcha", "mechanism", "shift")):
        n = words(data[key]) + (words(data["concept"]) if i == 0 else 0)
        out.append(scaled_duration(base[i], n, REF_WORDS[i]))
    return out


# ---------------------------------------------------------------- produce
def produce(data: dict, debug: bool = False, video: bool = True) -> Path:
    out = run_dir("A", strip_markup(data["concept"]))
    seed = random.randint(0, 10_000_000)
    steps = build_steps(data, seed)
    for step, name in zip(steps, STEP_FILES):
        img = full_frame(step)
        if debug:
            img = draw_safe_zone(img)
        img.save(out / f"{name}.png", optimize=True)
    if video:
        a = CFG.engine_a
        track = render_video(steps, _durations(data), out / "explainer.mp4", a.fps,
                             a.word_fade_ms, a.crossfade_ms,
                             getattr(a, "extra_seconds", 0.0))
        if track:
            data["music"] = track
    history.remember("psychology.concepts", [strip_markup(data["concept"])])
    save_meta(out, data)
    return out
