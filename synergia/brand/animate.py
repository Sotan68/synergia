"""Shared video animation for Engines A and B: letter-by-letter typing, crossfades, typing + music.

One typing plan per slide drives both the picture and the sound: every letter (and every space)
gets a time, the letter fades/settles in from that moment and a keystroke is placed on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from synergia.brand.sound import build_soundtrack
from synergia.brand.typography import TextLayout
from synergia.video import FrameWriter


@dataclass
class Step:
    base: Image.Image            # background + static elements
    layouts: list[TextLayout]    # text typed letter by letter, in order


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


# Typing pauses in seconds (sound and letters stop together), after these trailing characters.
_PAUSE_AFTER = {".": 0.22, "!": 0.22, "?": 0.22, ":": 0.16, ";": 0.14, ",": 0.10,
                "—": 0.10, "–": 0.10}
_PAUSE_LAYOUT = 0.30             # between two text blocks on the same slide
_PAUSE_SHARE = 0.35              # pauses never take more than this share of the typing window


@dataclass
class _Plan:
    times: list[list[list[float]]]     # [layout][word][char] -> seconds from slide start
    keys: list[tuple[float, float]]    # (seconds from slide start, gain) per typed letter/space


def _plan_step(step: Step, dur: float, lead: float, rng: np.random.Generator) -> _Plan:
    """Human-ish typing schedule: one keystroke per letter and per space, real pauses after
    punctuation and between text blocks, slight random variation in every interval."""
    seq: list[tuple[float, float, tuple[int, int, int] | None, float]] = []
    # (keystroke units before, pause seconds before, char index or None for space, gain)
    n_words = 0
    for li, lay in enumerate(step.layouts):
        for wi, w in enumerate(lay.words):
            n_words += 1
            units, pause = (0.0, 0.0) if not seq else (1.0, 0.0)
            if seq and wi == 0:
                pause = _PAUSE_LAYOUT
            elif seq:
                seq.append((1.0, _PAUSE_AFTER.get(lay.words[wi - 1].text[-1:], 0.0), None,
                            rng.uniform(0.8, 1.0)))               # spacebar
            for ci in range(len(w.text)):
                seq.append((units if ci == 0 else 1.0, pause if ci == 0 else 0.0,
                            (li, wi, ci), rng.uniform(0.65, 1.0)))
    if not seq:
        return _Plan([[] for _ in step.layouts], [])

    units = np.array([u for u, *_ in seq]) * rng.uniform(0.7, 1.3, len(seq))
    pauses = np.array([p for _, p, *_ in seq])
    # ~0.22 s per word, using at most ~65% of the slide's (pre-hold) duration.
    window = min(dur * 0.65, n_words * 0.22)
    if pauses.sum() > window * _PAUSE_SHARE:
        pauses *= window * _PAUSE_SHARE / pauses.sum()
    per_unit = (window - pauses.sum()) / max(units.sum(), 1e-9)
    t = lead + np.cumsum(units * per_unit + pauses)

    times = [[[0.0] * len(w.text) for w in lay.words] for lay in step.layouts]
    keys = []
    for ti, (_, _, idx, gain) in zip(t, seq):
        if idx is not None:
            li, wi, ci = idx
            times[li][wi][ci] = float(ti)
        keys.append((float(ti), gain))
    return _Plan(times, keys)


def render_video(steps: list[Step], durations: list[float], path: Path, fps: int = 30,
                 word_fade_ms: int = 120, crossfade_ms: int = 250, hold: float = 0.0) -> str:
    """Render the animated video; returns the background-music track used ("" if none).

    word_fade_ms: how long each letter takes to fade/settle in.
    hold: extra seconds each slide stays on screen after its normal duration
    (does not change the typing timing)."""
    fade = word_fade_ms / 1000
    xfade_frames = max(1, int(crossfade_ms / 1000 * fps))
    W, H = steps[0].base.size
    lead = min(0.15, crossfade_ms / 2000)        # start typing as the crossfade settles

    rng = np.random.default_rng()
    plans, keys, t_step = [], [], 0.0
    # Keys sound half a frame after the letter's time: a letter shows on the first frame at or
    # after its time (0..1 frame later), so this keeps audio within +-half a frame of the picture.
    sync = 0.5 / fps
    for step, dur in zip(steps, durations):
        plan = _plan_step(step, dur, lead, rng)
        plans.append(plan)
        keys += [(t_step + k + sync, g) for k, g in plan.keys]
        t_step += int(round((dur + hold) * fps)) / fps
    total = t_step

    wav, track = build_soundtrack(keys, total, path.with_suffix(".audio.wav"))
    audio = (wav, 0.0, total) if wav is not None else None   # None -> silent track

    try:
        _render_frames(steps, durations, plans, path, fps, fade, xfade_frames, W, H, audio,
                       hold)
    finally:
        if wav is not None:
            wav.unlink(missing_ok=True)
    return track


def _render_frames(steps, durations, plans, path, fps, fade, xfade_frames, W, H, audio,
                   hold: float = 0.0) -> None:
    prev_last: Image.Image | None = None
    with FrameWriter(path, W, H, fps, audio=audio) as fw:
        for step, dur, plan in zip(steps, durations, plans):
            n_frames = int(round((dur + hold) * fps))
            end = max((c for lay in plan.times for w in lay for c in w), default=0.0) + fade
            done: Image.Image | None = None
            last = None
            for f in range(n_frames):
                t = f / fps
                if t >= end:
                    done = done or full_frame(step)
                    img = done
                else:
                    img = step.base
                    for lay, ltimes in zip(step.layouts, plan.times):
                        alphas = [[_ease_out(min(1.0, max(0.0, (t - ct) / fade))) for ct in w]
                                  for w in ltimes]
                        img = lay.draw_typed(img, alphas)
                if prev_last is not None and f < xfade_frames:
                    img = Image.blend(prev_last, img, (f + 1) / (xfade_frames + 1))
                fw.write(img)
                last = img
            prev_last = last
