"""Run folders and post metadata."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from synergia.config import CFG


def slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"\*\*", "", text.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len].rstrip("-") or "post"


ENGINE_NAMES = {"A": "Psychology Explainer", "B": "Random Fact Slideshow", "C": "Podcast Clipper"}


def run_dir(engine: str, title: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder = f"{engine} - {ENGINE_NAMES[engine]}" if engine in ENGINE_NAMES else engine
    d = CFG.output.dir / folder / f"{stamp}_{slugify(title)}"   # output/A - Psychology Explainer/...
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_meta(folder: Path, data: dict) -> None:
    (folder / "script.json").write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
    caption = re.sub(r"\*\*", "", data.get("caption", "")).strip()
    credit = str(data.get("credit") or "").strip()
    tags = " ".join(data.get("hashtags", []))
    parts = [x for x in (caption, credit, tags) if x]
    (folder / "caption.txt").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
