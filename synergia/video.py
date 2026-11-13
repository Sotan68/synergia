"""ffmpeg helpers: raw-frame pipe writer with NVENC/x264 auto-detection, probing."""
from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
_NOWIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@lru_cache(maxsize=1)
def video_encoder() -> list[str]:
    """Return encoder args; NVENC if it actually works on this machine, else libx264."""
    try:
        r = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=black:s=256x256:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30, creationflags=_NOWIN)
        if r.returncode == 0:
            return ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr",
                    "-cq", "19", "-b:v", "0", "-profile:v", "high"]
    except Exception:  # noqa: BLE001
        pass
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high"]


def ffmpeg_filter_path(p: Path | str) -> str:
    """Escape a Windows path for use inside an ffmpeg filter argument (e.g. ass=...)."""
    s = str(Path(p).resolve()).replace("\\", "/")
    s = s.replace(":", r"\:").replace("'", r"\'")
    return s


class FrameWriter:
    """Pipe RGB frames into ffmpeg.

    audio: None -> silent stereo track; (path, start, duration) -> take audio from source.
    vf: optional extra video filter (e.g. ass subtitles).
    """

    def __init__(self, out: Path, width: int, height: int, fps: float,
                 audio: tuple[Path, float, float] | None = None, vf: str | None = None):
        self.size = (width, height)
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-r", f"{fps}", "-i", "-"]
        if audio is None:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        else:
            src, start, dur = audio
            cmd += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        if vf:
            cmd += ["-vf", vf]
        cmd += video_encoder()
        cmd += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                "-movflags", "+faststart", "-shortest", str(out)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=_NOWIN)

    def write(self, frame: Image.Image | np.ndarray) -> None:
        if isinstance(frame, Image.Image):
            frame = np.asarray(frame.convert("RGB"))
        assert frame.shape[1] == self.size[0] and frame.shape[0] == self.size[1], frame.shape
        try:
            self.proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
        except (BrokenPipeError, OSError) as e:
            err = self.proc.stderr.read().decode(errors="ignore")
            raise RuntimeError(f"ffmpeg failed: {err.strip() or e}") from e

    def close(self) -> None:
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode(errors="ignore")
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err.strip()}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


class FrameReader:
    """Read frames (RGB uint8 arrays) of [start, start+dur) via ffmpeg — frame-accurate, any codec.

    width/height: output size (None keeps source size); fps: resample rate (None keeps source).
    """

    def __init__(self, src: Path | str, start: float, dur: float, width: int, height: int,
                 fps: float | None = None):
        self.w, self.h = width, height
        vf = [f"scale={width}:{height}:flags=area"]
        if fps:
            vf.insert(0, f"fps={fps}")
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
               "-t", f"{dur:.3f}", "-i", str(src), "-an", "-vf", ",".join(vf),
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=_NOWIN, bufsize=width * height * 3 * 4)
        self.frame_bytes = width * height * 3

    def __iter__(self):
        try:
            while True:
                buf = self.proc.stdout.read(self.frame_bytes)
                if len(buf) < self.frame_bytes:
                    break
                yield np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
        finally:
            self.close()

    def close(self) -> None:
        try:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


def extract_audio(src: Path | str, out: Path, start: float | None = None,
                  dur: float | None = None, rate: int = 16000) -> Path:
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(src), "-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NOWIN)
    if r.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {r.stderr.strip()}")
    return out


def probe(path: Path | str) -> dict:
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", str(path)], capture_output=True, text=True,
                       creationflags=_NOWIN)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {r.stderr.strip()}")
    return json.loads(r.stdout)


def video_info(path: Path | str) -> dict:
    """width, height, fps, duration, has_audio"""
    info = probe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise RuntimeError(f"No video stream in {path}")
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270):
        w, h = h, w
    return {
        "width": w, "height": h, "fps": fps or 30.0,
        "duration": float(info["format"].get("duration", v.get("duration", 0)) or 0),
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
    }
