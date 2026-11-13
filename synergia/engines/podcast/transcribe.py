"""Local transcription with faster-whisper (word timestamps), CUDA with automatic CPU fallback, cached."""
from __future__ import annotations

import hashlib
import json
import os
import site
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from synergia.config import CFG
from synergia.video import extract_audio

console = Console()
_dll_setup_done = False


def _setup_cuda_dlls() -> None:
    """Make pip-installed cuBLAS/cuDNN DLLs visible to CTranslate2 on Windows."""
    global _dll_setup_done
    if _dll_setup_done or sys.platform != "win32":
        return
    _dll_setup_done = True
    roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    for root in roots:
        nv = Path(root) / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _file_key(path: Path, start: float | None, end: float | None, model: str) -> str:
    st = path.stat()
    h = hashlib.sha1()
    h.update(f"{path.name}|{st.st_size}|{int(st.st_mtime)}|{start}|{end}|{model}".encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def _load_model(prefer_gpu: bool = True):
    from faster_whisper import WhisperModel

    ec = CFG.engine_c
    if prefer_gpu:
        _setup_cuda_dlls()
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                return WhisperModel(ec.whisper_model_gpu, device="cuda", compute_type="float16"), \
                    ec.whisper_model_gpu, "cuda"
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]GPU unavailable ({e}); using CPU.[/yellow]")
    return WhisperModel(ec.whisper_model_cpu, device="cpu", compute_type="int8"), \
        ec.whisper_model_cpu, "cpu"


def _load_wav(wav: Path):
    """16 kHz mono PCM WAV -> float32 array (avoids faster-whisper's PyAV decoder)."""
    import wave

    import numpy as np
    with wave.open(str(wav), "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, np.int16).astype(np.float32) / 32768.0


def _run(model, wav: Path, total: float, label: str) -> dict:
    segments, info = model.transcribe(
        _load_wav(wav), language=CFG.engine_c.language or None, word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 400}, beam_size=5,
        condition_on_previous_text=False)
    words, segs = [], []
    with Progress(TextColumn(f"[yellow]{label}"), BarColumn(), TextColumn("{task.percentage:>3.0f}%"),
                  TimeRemainingColumn(), console=console) as prog:
        task = prog.add_task("t", total=max(total, 1))
        for s in segments:
            segs.append({"s": round(s.start, 3), "e": round(s.end, 3), "text": s.text.strip()})
            for w in s.words or []:
                t = w.word.strip()
                if t:
                    words.append({"w": t, "s": round(w.start, 3), "e": round(w.end, 3),
                                  "p": round(w.probability, 3)})
            prog.update(task, completed=min(s.end, total))
        prog.update(task, completed=total)
    return {"words": words, "segments": segs, "language": info.language, "duration": total}


def transcribe(video: Path, start: float | None = None, end: float | None = None,
               total_duration: float | None = None) -> dict:
    """Transcribe the whole file or [start, end). Times are always absolute (source timeline)."""
    cache = CFG.output.cache_dir / "transcripts"
    cache.mkdir(parents=True, exist_ok=True)
    tag = f"{CFG.engine_c.whisper_model_gpu}/{CFG.engine_c.whisper_model_cpu}"
    key = _file_key(video, start, end, tag)
    cached = cache / f"{key}.json"
    if cached.exists():
        console.print("[dim]Using cached transcript.[/dim]")
        return json.loads(cached.read_text(encoding="utf-8"))

    wav = cache / f"{key}.wav"
    dur = (end - start) if (start is not None and end is not None) else None
    with console.status("[yellow]Extracting audio…"):
        extract_audio(video, wav, start, dur)
    total = dur or total_duration or 0

    with console.status("[yellow]Loading Whisper model…"):
        model, name, device = _load_model(True)
    console.print(f"[dim]Whisper: {name} on {device}[/dim]")
    try:
        result = _run(model, wav, total, f"Transcribing ({device})")
    except Exception as e:  # noqa: BLE001  (missing CUDA libs surface lazily)
        msg = str(e).lower()
        if device != "cuda" or not any(k in msg for k in ("cuda", "cublas", "cudnn", "dll", "gpu")):
            raise
        console.print(f"[yellow]GPU transcription failed ({e}); retrying on CPU.[/yellow]")
        model, name, device = _load_model(False)
        result = _run(model, wav, total, "Transcribing (cpu)")

    off = start or 0.0
    if off:
        for w in result["words"]:
            w["s"] = round(w["s"] + off, 3)
            w["e"] = round(w["e"] + off, 3)
        for s in result["segments"]:
            s["s"] = round(s["s"] + off, 3)
            s["e"] = round(s["e"] + off, 3)
    result["model"] = name
    cached.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    try:
        wav.unlink()
    except OSError:
        pass
    return result
