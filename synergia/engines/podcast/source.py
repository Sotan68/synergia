"""Resolve Engine C input: YouTube (or any yt-dlp supported) URL -> local mp4, or validate a local file."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from synergia.config import CFG
from synergia.video import video_info


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


def _credit(info: dict) -> dict:
    """Who to credit for a downloaded video (channel name, @handle, video title, link)."""
    return {
        "channel": info.get("channel") or info.get("uploader") or "",
        "handle": info.get("uploader_id") or "",
        "title": info.get("title") or "",
        "url": info.get("webpage_url") or info.get("original_url") or "",
        "platform": info.get("extractor_key") or "",
    }


def download(url: str) -> tuple[Path, str, dict]:
    import yt_dlp

    out_dir = CFG.output.shared_cache / "downloads"     # shared by all profiles
    out_dir.mkdir(parents=True, exist_ok=True)
    h = CFG.engine_c.max_download_height
    opts = {
        "format": (f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/"
                   f"b[height<={h}]/b"),
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": False,
    }
    ff = shutil.which("ffmpeg")
    if ff:
        opts["ffmpeg_location"] = str(Path(ff).parent)
    # YouTube needs a JS runtime for signature challenges; use whatever is installed.
    runtimes = {rt: {} for rt in ("deno", "node", "bun") if shutil.which(rt)}
    if runtimes:
        opts["js_runtimes"] = runtimes
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        target = out_dir / f"{info['id']}.mp4"
        if not target.exists():
            ydl.download([url])
        if not target.exists():  # merged into another container
            cands = sorted(out_dir.glob(f"{info['id']}.*"))
            cands = [c for c in cands if c.suffix.lower() in (".mp4", ".mkv", ".webm")]
            if not cands:
                raise RuntimeError("Download finished but no video file was found.")
            target = cands[0]
    return target, info.get("title") or target.stem, _credit(info)


def channel_url(channel: str) -> str:
    """'@ChrisWillx', 'youtube.com/@ChrisWillx' or a full channel URL -> its Videos tab."""
    c = channel.strip().rstrip("/")
    if c.startswith("@"):
        return f"https://www.youtube.com/{c}/videos"
    if not is_url(c):
        c = "https://" + c
    if "youtube.com/" in c and not re.search(r"/(videos|streams|playlist)\b", c):
        c += "/videos"
    return c


def latest_episodes(channel: str, limit: int = 10) -> list[dict]:
    """Newest uploads of a channel, newest first, without downloading:
    [{'id', 'url', 'title', 'duration' (seconds, 0 if unknown), 'channel'}]."""
    import yt_dlp

    opts = {"extract_flat": "in_playlist", "playlistend": limit, "quiet": True,
            "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url(channel), download=False) or {}
    out = []
    for e in info.get("entries") or []:
        if not e or not e.get("id"):
            continue
        out.append({"id": e["id"], "url": e.get("url") or f"https://www.youtube.com/watch?v={e['id']}",
                    "title": e.get("title") or "", "duration": float(e.get("duration") or 0),
                    "channel": info.get("channel") or info.get("uploader") or channel})
    return out


def video_id(url: str) -> str:
    """YouTube video id from a URL (or the URL itself when there's none), used to remember clipped episodes."""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/)([\w-]{11})", url)
    return m.group(1) if m else url.strip()


def resolve(inp: str) -> tuple[Path, str, dict]:
    """-> (local video path, display name, credit info; empty credit for local files)."""
    inp = inp.strip().strip('"').strip("'")
    if is_url(inp):
        return download(inp)
    p = Path(inp).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    video_info(p)  # raises if not a valid video
    return p.resolve(), p.stem, {}
