"""Shared video animation for Engines A and B: word-by-word reveal per slide + crossfades."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from synergia.brand.typography import TextLayout
from synergia.video import FrameWriter


@dataclass
class Step:
    base: Image.Image            # background + static elements
    layouts: list[TextLayout]    # text revealed word by word, in order


def full_frame(step: Step) -> Image.Image:
    img = step.base
    for lay in step.layouts:
        img = lay.draw(img)
    return img


def scaled_duration(base: float, n_words: int, ref_words: int) -> float:
    """Stretch/shrink a base duration by word count (0.8x .. 1.45x)."""
    return base * min(1.45, max(0.8, n_words / ref_words))


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def render_video(steps: list[Step], durations: list[float], path: Path, fps: int = 30,
                 word_fade_ms: int = 120, crossfade_ms: int = 250) -> None:
    fade = word_fade_ms / 1000
    xfade_frames = max(1, int(crossfade_ms / 1000 * fps))
    W, H = steps[0].base.size
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
