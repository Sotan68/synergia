"""Procedural sound effects (numpy, no assets): tick, ding, pop, whoosh, buzz.

Each effect is a mono float32 array at 44.1 kHz, peak-normalised to ~0.8.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

SR = 44100


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR), dtype=np.float32) / SR


def _norm(a: np.ndarray, peak: float = 0.8) -> np.ndarray:
    fade = min(len(a), int(0.004 * SR))
    a[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)     # no click at the tail
    return (a * (peak / (np.abs(a).max() + 1e-9))).astype(np.float32)


def _lowpass(a: np.ndarray, k: int) -> np.ndarray:
    return np.convolve(a, np.ones(k, dtype=np.float32) / k, mode="same")


def _tick() -> np.ndarray:
    """Clock tick: a short bright woody click."""
    t = _t(0.05)
    rng = np.random.default_rng(1)
    click = rng.standard_normal(len(t)).astype(np.float32) * np.exp(-t / 0.002)
    body = (np.sin(2 * np.pi * 1900 * t) + 0.5 * np.sin(2 * np.pi * 3100 * t)) * np.exp(-t / 0.009)
    return _norm(0.6 * click + body, 0.7)


def _ding() -> np.ndarray:
    """'Correct' chime: two bell notes, a fifth apart."""
    t = _t(1.2)
    out = np.zeros(len(t), dtype=np.float32)
    for f0, start in ((784.0, 0.0), (1174.7, 0.09)):            # G5 then D6
        tt = np.clip(t - start, 0, None)
        on = (t >= start).astype(np.float32)
        for mult, amp, decay in ((1.0, 1.0, 0.55), (2.0, 0.35, 0.25), (3.01, 0.15, 0.12)):
            out += on * amp * np.sin(2 * np.pi * f0 * mult * tt) * np.exp(-tt / decay)
    out *= np.minimum(1.0, t / 0.003)                            # soft attack
    return _norm(out, 0.75)


def _pop() -> np.ndarray:
    """Bubble pop: a quick downward pitch blip."""
    t = _t(0.09)
    freq = 950 * np.exp(-t / 0.03) + 380
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return _norm(np.sin(phase) * np.exp(-t / 0.028) * np.minimum(1.0, t / 0.002), 0.7)


def _whoosh() -> np.ndarray:
    """Air whoosh: noise swelling and sweeping up then away."""
    t = _t(0.45)
    rng = np.random.default_rng(2)
    noise = rng.standard_normal(len(t)).astype(np.float32)
    env = np.sin(np.pi * t / t[-1]) ** 2
    dark = _lowpass(noise, 40)
    bright = _lowpass(noise, 8)
    mix = t / t[-1]
    return _norm((dark * (1 - mix) + bright * mix * 0.6) * env, 0.55)


def _buzz() -> np.ndarray:
    """Time's-up buzzer: a soft low square-ish tone."""
    t = _t(0.38)
    tone = np.tanh(3 * np.sin(2 * np.pi * 155 * t)) + 0.4 * np.tanh(3 * np.sin(2 * np.pi * 233 * t))
    env = np.minimum(1.0, t / 0.01) * np.minimum(1.0, (t[-1] - t) / 0.08)
    return _norm(_lowpass(tone * env, 6), 0.5)


_MAKERS = {"tick": _tick, "ding": _ding, "pop": _pop, "whoosh": _whoosh, "buzz": _buzz}
NAMES = tuple(_MAKERS)


@lru_cache(maxsize=None)
def effect(name: str) -> np.ndarray:
    try:
        return _MAKERS[name]()
    except KeyError:
        raise ValueError(f"unknown sound effect {name!r}; known: {', '.join(NAMES)}") from None
