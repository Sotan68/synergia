"""Keyboard-typing sound track, synced to the word-by-word text reveal.

Uses real recorded keystrokes from assets/sounds/keys/*.wav (CC0, see LICENSE.txt there):
each sample is trimmed to its onset and level-matched, then keys are scattered across every
word's reveal slot with random choice, gain and a touch of stereo spread.
"""
from __future__ import annotations

import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from synergia.config import CFG

SR = 44100
KEYS_DIR = CFG.root / "assets" / "sounds" / "keys"


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        ch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path.name}: only 16-bit WAV is supported")
    a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != SR:  # simple linear resample
        a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * SR / sr)), np.arange(len(a)), a)
    return a


@lru_cache(maxsize=1)
def load_keys() -> tuple[np.ndarray, ...]:
    """Keystroke samples, each trimmed to start ~2 ms before its click and RMS-normalised."""
    keys = []
    for f in sorted(KEYS_DIR.glob("*.wav")):
        a = _read_wav(f)
        if not a.size or np.abs(a).max() < 1e-4:
            continue
        onset = int(np.argmax(np.abs(a) > 0.05 * np.abs(a).max()))
        a = a[max(0, onset - int(0.002 * SR)):]
        fade = min(len(a), int(0.02 * SR))                     # avoid a click at the tail
        a[-fade:] *= np.linspace(1, 0, fade)
        rms = np.sqrt((a[: int(0.06 * SR)] ** 2).mean()) + 1e-9
        keys.append(a * (0.12 / rms))
    return tuple(keys)


def typing_track(words: list[tuple[float, str, float]], total: float, path: Path,
                 volume: float = 0.6, seed: int = 0) -> Path | None:
    """Write a stereo WAV of keystrokes; None if no key samples are installed.

    words: (reveal_time_s, word_text, time_until_next_word_s) for every revealed word.
    """
    keys = load_keys()
    if not keys:
        return None
    rng = np.random.default_rng(seed)
    n = int(total * SR) + 1
    mix = np.zeros((n, 2), dtype=np.float32)
    last = -1

    def add(t: float, gain: float) -> None:
        nonlocal last
        i = int(t * SR)
        if i >= n:
            return
        k = rng.integers(len(keys))
        if k == last:                                           # no machine-gun repeats
            k = (k + 1 + rng.integers(len(keys) - 1)) % len(keys) if len(keys) > 1 else k
        last = k
        seg = keys[k][: n - i] * gain
        pan = rng.uniform(-0.15, 0.15)
        mix[i:i + len(seg), 0] += seg * (1 - pan)
        mix[i:i + len(seg), 1] += seg * (1 + pan)

    for t0, text, slot in words:
        letters = sum(c.isalnum() for c in text) or 1
        # Roughly one key per two letters, never faster than ~1 key / 55 ms.
        count = int(max(1, min(np.ceil(letters / 2), slot / 0.055)))
        span = slot * 0.85
        for j in range(count):
            jitter = rng.uniform(-0.008, 0.008) if j else 0.0
            add(max(0.0, t0 + span * j / count + jitter), rng.uniform(0.7, 1.0))

    mix = np.tanh(mix * volume * 1.4) * 0.9                    # level + soft limit
    pcm = (mix * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


# ---------------------------------------------------------------- background music
MUSIC_EXT = {".mp3", ".ogg", ".wav", ".m4a", ".flac"}


def music_tracks() -> list[Path]:
    snd = getattr(CFG, "sound", None)
    d = CFG.root / getattr(snd, "music_dir", "assets/music")
    return sorted(p for p in d.glob("*") if p.suffix.lower() in MUSIC_EXT) if d.is_dir() else []


def build_soundtrack(events: list[tuple[float, str, float]], total: float,
                     out: Path) -> tuple[Path | None, str]:
    """Typing track + (optional) background music, mixed to one WAV.

    Returns (wav path or None if there's nothing to play, music track name or "").
    """
    import random
    import subprocess

    from synergia.video import FFMPEG, _NOWIN

    snd = getattr(CFG, "sound", None)
    typing_on = bool(getattr(snd, "typing", False))
    music_on = bool(getattr(snd, "music", False))
    typing = None
    if typing_on:
        typing = typing_track(events, total, out.with_suffix(".keys.wav"),
                              volume=getattr(snd, "typing_volume", 0.6))
    tracks = music_tracks() if music_on else []
    if not tracks:
        return typing, ""

    track = random.choice(tracks)
    vol = float(getattr(snd, "music_volume", 0.25))
    fade_out = min(1.5, total / 4)
    # Loop the track if it's shorter than the video, normalise loudness, then fade in/out.
    music = (f"[0:a]aresample=44100,aformat=channel_layouts=stereo,"
             f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100,volume={vol:.3f},"
             f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
             f"afade=t=in:d=0.8,afade=t=out:st={max(0.0, total - fade_out):.3f}:d={fade_out:.3f}")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-stream_loop", "-1", "-i", str(track)]
    if typing is not None:
        cmd += ["-i", str(typing)]
        fc = (f"{music}[m];[1:a]aformat=channel_layouts=stereo[k];"
              f"[m][k]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[a]")
    else:
        fc = f"{music},alimiter=limit=0.95[a]"
    cmd += ["-filter_complex", fc, "-map", "[a]", "-t", f"{total:.3f}",
            "-c:a", "pcm_s16le", "-ar", "44100", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NOWIN)
    if typing is not None:
        typing.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"Mixing background music failed: {r.stderr.strip()}")
    return out, track.stem
