"""Shared helpers for publishing a rendered run folder to a platform.

A run folder (output/<engine>/<date>_<slug>/) holds the video, caption.txt and script.json.
Uploads are recorded in posted.json in that folder so the same video isn't posted twice.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from synergia.config import CFG

# The video each engine renders, in lookup order.
VIDEO_NAMES = ("explainer.mp4", "slideshow.mp4", "clip.mp4", "brain_test.mp4", "identity.mp4")
LEDGER = "posted.json"


@dataclass
class Post:
    folder: Path
    video: Path
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)   # without the leading '#'


def find_video(folder: Path) -> Path | None:
    for name in VIDEO_NAMES:
        if (folder / name).is_file():
            return folder / name
    return None


def parse_caption(text: str) -> tuple[str, str]:
    """caption.txt -> (title, description). Reads the TITLE:/DESCRIPTION: blocks from output.caption_text."""
    parts = re.split(r"^(TITLE|DESCRIPTION):[ \t]*\r?\n", text, flags=re.M)
    blocks = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if not blocks:  # hand-written caption without headers: whole text is the description
        return "", text.strip()
    return blocks.get("TITLE", ""), blocks.get("DESCRIPTION", "")


def hashtags_in(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"(?<![\w&])#(\w+)", text)))


def load_post(folder: Path) -> Post:
    """Build a Post from a run folder. caption.txt wins, so hand edits to it are respected."""
    folder = Path(folder)
    video = find_video(folder)
    if video is None:
        raise FileNotFoundError(f"No video ({', '.join(VIDEO_NAMES)}) in {folder}")
    cap = folder / "caption.txt"
    title, desc = parse_caption(cap.read_text(encoding="utf-8")) if cap.is_file() else ("", "")
    if not title:  # fall back to the folder slug: 2026-11-14_213414_loss-aversion -> Loss aversion
        slug = folder.name.split("_", 2)[-1]
        title = slug.replace("-", " ").capitalize()
    return Post(folder, video, title, desc, hashtags_in(desc))


def read_ledger(folder: Path) -> dict:
    p = Path(folder) / LEDGER
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(folder: Path, platform: str, entry: dict) -> None:
    data = read_ledger(folder)
    data[platform] = {**entry, "uploaded_at": datetime.now().isoformat(timespec="seconds")}
    (Path(folder) / LEDGER).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                      encoding="utf-8")


def recent_runs(limit: int = 15) -> list[Path]:
    """Newest run folders (across all engines) that contain a postable video."""
    root = CFG.output.dir
    runs = [d for d in root.glob("*/*") if d.is_dir() and find_video(d)] if root.is_dir() else []
    return sorted(runs, key=lambda d: d.name, reverse=True)[:limit]
