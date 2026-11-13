"""Engine C final render: speaker-centred 9:16 crop + burned word-highlight subtitles + source audio."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from synergia.config import CFG
from synergia.engines.podcast.speaker import CameraPath, analyze
from synergia.engines.podcast.subtitles import build_ass
from synergia.video import FrameReader, FrameWriter, ffmpeg_filter_path

console = Console()


def _debug_frame(frame: np.ndarray, path: CameraPath, t: float, x0: int) -> np.ndarray:
    k = min(len(path.faces) - 1, int(t * CFG.engine_c.analysis_fps)) if path.faces else -1
    s = path.scale
    img = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    if k >= 0:
        for f in path.faces[k]:
            active = path.active is not None and f.track == path.active[k]
            col = (74, 166, 212) if active else (180, 180, 180)
            cv2.rectangle(img, (int(f.x * s), int(f.y * s)), (int((f.x + f.w) * s), int((f.y + f.h) * s)),
                          col, 6 if active else 2)
            cv2.putText(img, f"#{f.track}", (int(f.x * s), int(f.y * s) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, col, 3)
    cv2.rectangle(img, (x0, 0), (x0 + path.crop_w, path.crop_h - 1), (60, 60, 255), 4)
    h, w = img.shape[:2]
    img = cv2.resize(img, (640, int(h * 640 / w) // 2 * 2))
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def render_clip(src: Path, info: dict, start: float, end: float, words: list[dict], out_dir: Path,
                title: str = "", debug: bool = False) -> Path:
    dur = end - start
    W, H = CFG.brand.width, CFG.brand.height
    fps = info["fps"] if 0 < info["fps"] <= 60 else 30

    path = analyze(src, start, dur, info, words)
    cuts = int(path.cut.sum()) - 1
    console.print(f"[dim]Camera: crop {path.crop_w}x{path.crop_h} from {path.src_w}x{path.src_h}, "
                  f"{max(cuts, 0)} speaker/scene cut(s)[/dim]")

    ass = build_ass(words, start, end, out_dir / "subtitles.ass", title=title)
    fonts = CFG.root / "assets" / "fonts"
    vf = f"ass='{ffmpeg_filter_path(ass)}':fontsdir='{ffmpeg_filter_path(fonts)}'"
    out = out_dir / "clip.mp4"
    audio = (src, start, dur) if info["has_audio"] else None

    dbg = None
    if debug:
        dh = int(path.src_h * 640 / path.src_w) // 2 * 2
        dbg = FrameWriter(out_dir / "debug_tracking.mp4", 640, dh, fps)

    interp = cv2.INTER_AREA if path.crop_h >= H else cv2.INTER_CUBIC
    y0 = max(0, (path.src_h - path.crop_h) // 2)
    n_total = int(dur * fps)
    with FrameWriter(out, W, H, fps, audio=audio, vf=vf) as fw, \
            Progress(TextColumn("[yellow]Rendering clip"), BarColumn(),
                     TextColumn("{task.percentage:>3.0f}%"), TimeRemainingColumn(),
                     console=console) as prog:
        task = prog.add_task("r", total=max(1, n_total))
        for i, frame in enumerate(FrameReader(src, start, dur, path.src_w, path.src_h)):
            t = i / fps
            x0 = path.left(t)
            crop = frame[y0:y0 + path.crop_h, x0:x0 + path.crop_w]
            fw.write(cv2.resize(crop, (W, H), interpolation=interp))
            if dbg is not None:
                dbg.write(_debug_frame(frame, path, t, x0))
            prog.update(task, completed=i + 1)
    if dbg is not None:
        dbg.close()

    seg = [w for w in words if start <= w["s"] < end]
    (out_dir / "transcript_segment.json").write_text(
        json.dumps({"start": start, "end": end, "words": seg}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    return out
