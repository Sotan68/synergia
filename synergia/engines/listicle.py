"""Engine B — Random Fact / Life-Advice Slideshow: cover + 5 points as 9:16 PNGs + an MP4."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

from synergia.brand import paper
from synergia.brand.animate import Step, full_frame, render_video, scaled_duration
from synergia.brand.canvas import Box, draw_safe_zone, safe_for
from synergia.brand.typography import font, layout_text, strip_markup
from synergia import history
from synergia.config import CFG
from synergia.llm.bridge import check_text, normalize_common, words
from synergia.llm.prompts import listicle_prompt
from synergia.output import run_dir, save_meta

LIMITS = {"cover_title": 12, "cover_subtitle": 6, "title": 8, "body": 22}


def prompt(hook: str) -> str:
    return listicle_prompt(hook)


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    check_text(data, "cover_title", LIMITS["cover_title"], errors)
    pts = data.get("points")
    if not isinstance(pts, list) or len(pts) != 5:
        errors.append('"points" must be a list of exactly 5 items')
    else:
        for i, p in enumerate(pts, 1):
            if not isinstance(p, dict):
                errors.append(f"point {i} must be an object with title/body")
                continue
            e: list[str] = []
            check_text(p, "title", LIMITS["title"], e)
            check_text(p, "body", LIMITS["body"], e)
            errors += [f"point {i}: {x}" for x in e]
    if len(str(data.get("title") or "")) > 100:
        errors.append('"title" must be at most 100 characters')
    if not errors:
        normalize_common(data)
        data["cover_subtitle"] = str(data.get("cover_subtitle") or "").strip()
        if not data["title"]:
            data["title"] = strip_markup(data["cover_title"])
    return errors


def review_fields(data: dict) -> list[tuple[str, str]]:
    f = [("Post title", "title"), ("Cover title", "cover_title"),
         ("Cover subtitle", "cover_subtitle")]
    for i in range(5):
        f += [(f"#{i + 1} title", f"points.{i}.title"), (f"#{i + 1} body", f"points.{i}.body")]
    f.append(("Caption", "caption"))
    return f


# ---------------------------------------------------------------- slides
# The "paper" look (synergia.brand.paper): serif headlines with blue italic highlights, a large
# purple serif numeral per point, Inter Display body text, page count in the footer.
N_SLIDES = 6


def _centred(top_area: int, bottom_area: int, height: int, lift: int = 40) -> int:
    return top_area + max(0, (bottom_area - top_area - height) // 2 - lift)


def _cover(data: dict, bg: Image.Image, swipe: bool = True) -> Step:
    """Cover: big serif title (+ subtitle) typed out; footer and swipe cue are static."""
    base = bg
    safe = safe_for(base.height)
    tall = base.height == CFG.brand.height
    title = layout_text(data["cover_title"], Box(safe.x, 0, safe.w, int(safe.h * 0.58)),
                        weight=paper.SERIF, max_size=160 if tall else 128, min_size=70,
                        valign="top", line_spacing=1.0, color=paper.INK,
                        accent_color=paper.ACCENT, accent_weight=paper.SERIF_I)
    layouts = [title]
    sub = None
    if data.get("cover_subtitle"):
        sub = layout_text(data["cover_subtitle"], Box(safe.x, 0, safe.w, int(safe.h * 0.16)),
                          weight=paper.TEXT_W, max_size=46, min_size=34, valign="top",
                          color=paper.SOFT, accent_color=paper.ACCENT,
                          accent_weight=paper.SERIF_I, accent_scale=paper.SERIF_IN_SANS)
    gap = 56
    total = title.height + (gap + sub.height if sub else 0)
    title = title.moved(dy=_centred(safe.y, safe.bottom - 110, total))
    layouts[0] = title
    if sub:
        layouts.append(sub.moved(dy=title.top + title.height + gap))
    paper.footer(base)
    if swipe:  # carousel only; a video plays on by itself
        paper.swipe_pill(base)
    return Step(base, layouts)


GAP_NUM, GAP_BODY = 64, 40


def _point_parts(p: dict, height: int):
    """(numeral size, numeral cap height, title, body, block height) with the text at y = 0."""
    safe = safe_for(height)
    tall = height == CFG.brand.height
    num_size = 330 if tall else 240
    num_h = int(num_size * 0.72)            # cap height of the numeral
    title = layout_text(p["title"], Box(safe.x, 0, safe.w, int(safe.h * 0.30)), weight=paper.SERIF,
                        max_size=100 if tall else 84, min_size=56, valign="top",
                        line_spacing=1.04, color=paper.INK, accent_color=paper.ACCENT,
                        accent_weight=paper.SERIF_I)
    body = layout_text(p["body"], Box(safe.x, 0, safe.w, int(safe.h * 0.28)), weight=paper.TEXT_W,
                       max_size=50, min_size=34, valign="top", line_spacing=1.36,
                       color=paper.SOFT, accent_color=paper.ACCENT,
                       accent_weight=paper.SERIF_I, accent_scale=paper.SERIF_IN_SANS)
    return num_size, num_h, title, body, num_h + GAP_NUM + title.height + GAP_BODY + body.height


def _point(i: int, p: dict, bg: Image.Image, top: int) -> Step:
    """Point slide: big purple serif numeral is static; title then body are typed out.

    `top` is shared by all point slides, so the numeral sits at the same height on each."""
    base = bg
    safe = safe_for(base.height)
    num_size, num_h, title, body, _ = _point_parts(p, base.height)
    ImageDraw.Draw(base).text((safe.x - 6, top + num_h), f"{i:02d}",
                              font=font(paper.SERIF_I, num_size), fill=paper.ACCENT2, anchor="ls")
    title = title.moved(dy=top + num_h + GAP_NUM)
    body = body.moved(dy=title.top + title.height + GAP_BODY)
    paper.footer(base, i + 1, N_SLIDES)
    return Step(base, [title, body])


def build_steps(data: dict, seed: int, height: int | None = None,
                swipe: bool = True) -> list[Step]:
    h = height or CFG.brand.height
    safe = safe_for(h)
    tallest = max(_point_parts(p, h)[-1] for p in data["points"])
    top = _centred(safe.y, safe.bottom - 110, tallest, lift=20)
    steps = []
    for idx in range(N_SLIDES):
        bg = paper.background(seed, CFG.brand.width, h, variant=idx)
        steps.append(_cover(data, bg, swipe) if idx == 0
                     else _point(idx, data["points"][idx - 1], bg, top))
    return steps


# ---------------------------------------------------------------- output
def render(data: dict, out: Path, seed: int | None = None, debug: bool = False,
           height: int | None = None, prefix: str = "") -> list[Path]:
    """Carousel PNGs (cover + 5 points)."""
    seed = seed if seed is not None else random.randint(0, 10_000_000)
    paths = []
    for idx, step in enumerate(build_steps(data, seed, height)):
        img = full_frame(step)
        if debug:
            img = draw_safe_zone(img)
        name = f"{prefix}{idx + 1:02d}_{'cover' if idx == 0 else f'point{idx}'}.png"
        path = out / name
        img.save(path, optimize=True)
        paths.append(path)
    return paths


def _durations(data: dict) -> list[float]:
    b = CFG.engine_b
    cover_words = words(data["cover_title"]) + words(data.get("cover_subtitle", ""))
    out = [scaled_duration(b.cover_seconds, cover_words, 10)]
    for p in data["points"]:
        out.append(scaled_duration(b.point_seconds, words(p["title"]) + words(p["body"]), 24))
    return out


def render_slideshow_video(data: dict, out: Path, seed: int) -> Path:
    """9:16 MP4 of the same slides: letter-by-letter typing per slide, crossfade between slides.

    Also records the background-music track (if any) in data["music"].
    """
    b = CFG.engine_b
    path = out / "slideshow.mp4"
    track = render_video(build_steps(data, seed, swipe=False), _durations(data), path, b.fps,
                         b.word_fade_ms, b.crossfade_ms)
    if track:
        data["music"] = track
    return path


def produce(data: dict, debug: bool = False) -> Path:
    out = run_dir("B", data["cover_title"])
    seed = random.randint(0, 10_000_000)
    render(data, out, seed, debug)
    if getattr(CFG.engine_b, "video", True):
        render_slideshow_video(data, out, seed)
    if CFG.engine_b.also_export_4x5:
        sub = out / "4x5"
        sub.mkdir(exist_ok=True)
        render(data, sub, seed, debug, height=1350)
    history.remember("listicle.hooks", [strip_markup(data["cover_title"])])
    save_meta(out, data)
    return out
