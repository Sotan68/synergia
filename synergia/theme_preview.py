"""Theme preview for the setup wizard: an Engine A cover, an Engine B point and an Engine D cover.

Run as `python -m synergia.theme_preview OUT.png "Concept" "Hook"` with SYNERGIA_PROFILE pointing
at a temporary profile (brand name, logo, theme). It runs in its own process because the slide
modules read their colours and fonts once, when they are imported.

Previews are cached by profile, text and a fingerprint of the slide code, so a design change
(new theme, new blueprint) renders fresh previews instead of reusing old ones.
"""
from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from hashlib import sha1
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
# The code that decides what a slide looks like.
_DESIGN_FILES = [*sorted((PACKAGE / "brand").glob("*.py")),
                 PACKAGE / "engines" / "psychology.py", PACKAGE / "engines" / "listicle.py",
                 PACKAGE / "theme_preview.py"]


@lru_cache(maxsize=1)
def design_fingerprint() -> str:
    h = sha1()
    for f in _DESIGN_FILES:
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def render(out: Path, concept: str, hook: str) -> None:
    from PIL import Image

    from synergia.brand import quiz
    from synergia.brand.animate import Step, full_frame
    from synergia.engines import listicle, psychology

    filler = "A small change you can try **this week**."
    a = psychology.build_steps({"concept": concept, "hook_line": hook, "gotcha": filler,
                                "mechanism": filler, "shift": filler}, seed=7)[0]
    point = {"title": "Start **smaller** than you think", "body": "Two minutes a day beats an hour "
             "you never do. Make it too easy to skip."}
    b = listicle.build_steps({"cover_title": hook, "cover_subtitle": "",
                              "points": [point] * 5}, seed=7, swipe=False)[1]
    base = quiz.background(7, variant=0)
    big, small = quiz.title_sheet(base, "Brain test", "Only **1 in 20** people get them all",
                                  "Keep score as you go", 4, None, 1, 6, big_max=116, big_min=64)
    d = Step(base, [big, small])
    tw, th = 300, 533
    sheet = Image.new("RGB", (3 * tw + 2 * 10, th), (230, 232, 238))
    for i, step in enumerate((a, b, d)):
        sheet.paste(full_frame(step).resize((tw, th), Image.LANCZOS), (i * (tw + 10), 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)


def preview_path(cache_dir: Path, profile_toml: str, concept: str, hook: str) -> Path:
    key = sha1(f"{design_fingerprint()}|{profile_toml}|{concept}|{hook}".encode()).hexdigest()[:16]
    return cache_dir / "theme_previews" / f"{key}.png"


def make(cache_dir: Path, root: Path, profile: dict, concept: str, hook: str) -> Path:
    """Render (or reuse) a preview for this brand name / logo / theme. Blocking: run it in a thread."""
    from synergia.profile import dumps

    text = dumps(profile)
    logo = (profile.get("brand") or {}).get("logo")
    if logo and (root / logo).is_file():           # a new logo file means a new preview
        text += f"\n# logo mtime {(root / logo).stat().st_mtime}"
    out = preview_path(cache_dir, text, concept, hook)
    if out.is_file():
        return out
    prof = out.with_suffix(".toml")
    prof.parent.mkdir(parents=True, exist_ok=True)
    prof.write_text(text, encoding="utf-8")
    env = {**os.environ, "SYNERGIA_PROFILE": str(prof)}
    subprocess.run([sys.executable, "-m", "synergia.theme_preview", str(out), concept, hook],
                   cwd=root, env=env, check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out


if __name__ == "__main__":
    render(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
