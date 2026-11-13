"""Engine B — Random Fact / Life-Advice Slideshow: cover + 5 points as 9:16 PNGs."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

from synergia.brand.backgrounds import make_background
from synergia.brand.canvas import Box, draw_safe_zone, safe_for
from synergia.brand.elements import draw_wordmark, footer_baseline
from synergia.brand.typography import (ACCENT, ACCENT2, MUTED, TEXT, draw_gradient_text, draw_label,
                                     font, layout_text)
from synergia.config import CFG
from synergia.llm.bridge import check_text, normalize_common
from synergia.llm.prompts import listicle_prompt
from synergia.output import run_dir, save_meta

BODY = tuple(int(c * 0.86) for c in TEXT)
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
    if not errors:
        normalize_common(data)
        data["cover_subtitle"] = str(data.get("cover_subtitle") or "").strip()
    return errors


def review_fields(data: dict) -> list[tuple[str, str]]:
    f = [("Cover title", "cover_title"), ("Cover subtitle", "cover_subtitle")]
    for i in range(5):
        f += [(f"#{i + 1} title", f"points.{i}.title"), (f"#{i + 1} body", f"points.{i}.body")]
    f.append(("Caption", "caption"))
    return f


# ---------------------------------------------------------------- rendering
def _cover(data: dict, bg: Image.Image) -> Image.Image:
    img = bg.copy()
    h = img.height
    safe = safe_for(h)
    draw_wordmark(img)
    title_box = Box(safe.x, safe.y + int(safe.h * 0.14), safe.w, int(safe.h * 0.52))
    title = layout_text(data["cover_title"], title_box, weight="black", max_size=118, min_size=56,
                        valign="bottom", line_spacing=1.1)
    img = title.draw(img)
    # Purple rule under title.
    y = title.top + title.height + 50
    ImageDraw.Draw(img).rectangle([safe.x, y, safe.x + 110, y + 7], fill=ACCENT2)
    if data.get("cover_subtitle"):
        sub_box = Box(safe.x, y + 50, safe.w, int(safe.h * 0.16))
        sub = layout_text(data["cover_subtitle"], sub_box, weight="medium", max_size=54,
                          min_size=36, valign="top", color=MUTED)
        img = sub.draw(img)
    label = "SWIPE  →"
    f = font("semibold", 30)
    width = sum(f.getlength(c) for c in label) + 30 * 0.25 * (len(label) - 1)
    draw_label(img, label, int(safe.right - width), footer_baseline(img), size=30, color=MUTED,
               tracking=0.25)
    return img


def _point(i: int, p: dict, bg: Image.Image) -> Image.Image:
    img = bg.copy()
    safe = safe_for(img.height)
    draw_wordmark(img)
    content = Box(safe.x, safe.y + 120, safe.w, safe.h - 220)

    num_size = 210 if img.height == CFG.brand.height else 150
    gap1, gap2 = 50, 44

    def stack(top: int):
        nf = font("black", num_size)
        num_h = int(num_size * 0.75)
        tbox = Box(content.x, top + num_h + gap1, content.w, int(content.h * 0.36))
        title = layout_text(p["title"], tbox, weight="bold", max_size=92, min_size=50, valign="top",
                            line_spacing=1.12)
        bbox = Box(content.x, title.top + title.height + gap2, content.w,
                   int(content.h * 0.30))
        body = layout_text(p["body"], bbox, weight="medium", max_size=52, min_size=34,
                           valign="top", color=BODY, line_spacing=1.32)
        total = (body.top + body.height) - top
        return nf, num_h, title, body, total

    _, _, _, _, total = stack(content.y)
    top = content.y + max(0, (content.h - total) // 2 - 40)
    nf, num_h, title, body, _ = stack(top)

    draw_gradient_text(img, (content.x - 6, top + num_h), f"{i:02d}", nf, ACCENT, ACCENT2)
    img = title.draw(img)
    img = body.draw(img)
    return img


def render(data: dict, out: Path, seed: int | None = None, debug: bool = False,
           height: int | None = None, prefix: str = "") -> list[Path]:
    seed = seed if seed is not None else random.randint(0, 10_000_000)
    h = height or CFG.brand.height
    paths = []
    for idx in range(6):
        bg = make_background(seed, CFG.brand.width, h, variant=idx)
        img = _cover(data, bg) if idx == 0 else _point(idx, data["points"][idx - 1], bg)
        if debug:
            img = draw_safe_zone(img)
        name = f"{prefix}{idx + 1:02d}_{'cover' if idx == 0 else f'point{idx}'}.png"
        path = out / name
        img.save(path, optimize=True)
        paths.append(path)
    return paths


def produce(data: dict, debug: bool = False) -> Path:
    out = run_dir("B", data["cover_title"])
    seed = random.randint(0, 10_000_000)
    render(data, out, seed, debug)
    if CFG.engine_b.also_export_4x5:
        sub = out / "4x5"
        sub.mkdir(exist_ok=True)
        render(data, sub, seed, debug, height=1350)
    save_meta(out, data)
    return out
