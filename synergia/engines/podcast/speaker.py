"""Active-speaker detection and 9:16 camera path.

Pipeline (offline, two-pass):
  1. Sample the segment at ~10 fps (640px wide) and detect faces with YuNet.
  2. Link detections into tracks; measure mouth-region motion per track (landmark-aligned patches).
  3. Weight motion by "someone is speaking" (from word timestamps), smooth, pick the most active track.
  4. Remove speaker segments shorter than `switch_hold_seconds` (min-duration filter = hysteresis
     without lag), so speaker changes become clean hard cuts.
  5. Within a shot the camera eases with a dead zone; on speaker change or scene cut it hard-cuts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn

from synergia.config import CFG
from synergia.video import FrameReader

console = Console()
MODEL = CFG.root / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
ANALYSIS_W = 640


@dataclass
class Face:
    x: float
    y: float
    w: float
    h: float
    lm: np.ndarray       # 5x2 landmarks (re, le, nose, rmouth, lmouth) in analysis px
    score: float
    track: int = -1

    @property
    def cx(self) -> float:
        return self.x + self.w / 2


@dataclass
class Track:
    id: int
    last: Face
    last_t: int
    prev_patch: np.ndarray | None = None
    hits: int = 0


@dataclass
class CameraPath:
    times: np.ndarray        # sample times (s, relative to clip start)
    cx: np.ndarray           # crop centre x in SOURCE pixels per sample
    cut: np.ndarray          # bool: hard cut at this sample
    crop_w: int
    crop_h: int
    src_w: int
    src_h: int
    faces: list[list[Face]] = field(default_factory=list)   # for debug overlay
    active: np.ndarray | None = None
    scale: float = 1.0       # analysis px -> source px

    def at(self, t: float) -> float:
        """Crop centre at time t (s): linear interpolation within a shot, step across cuts."""
        i = int(np.searchsorted(self.times, t, side="right") - 1)
        if i < 0:
            return float(self.cx[0])
        if i >= len(self.times) - 1:
            return float(self.cx[-1])
        if self.cut[i + 1]:
            return float(self.cx[i])
        t0, t1 = self.times[i], self.times[i + 1]
        a = (t - t0) / (t1 - t0) if t1 > t0 else 0
        return float(self.cx[i] * (1 - a) + self.cx[i + 1] * a)

    def left(self, t: float) -> int:
        x = int(round(self.at(t) - self.crop_w / 2))
        return max(0, min(self.src_w - self.crop_w, x))


def _detector(w: int, h: int):
    if not MODEL.exists():
        return None
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), score_threshold=0.75,
                                    nms_threshold=0.3, top_k=20)
    return det


def _mouth_patch(gray: np.ndarray, f: Face) -> np.ndarray | None:
    rm, lm = f.lm[3], f.lm[4]
    mx, my = (rm + lm) / 2
    mw = max(np.linalg.norm(lm - rm), f.w * 0.3)
    pw, ph = mw * 1.6, f.h * 0.42
    x0, y0 = int(mx - pw / 2), int(my - ph * 0.45)
    x1, y1 = int(mx + pw / 2), int(my + ph * 0.55)
    H, W = gray.shape
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H or x1 - x0 < 6 or y1 - y0 < 6:
        return None
    p = cv2.resize(gray[y0:y1, x0:x1], (48, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    p -= p.mean()
    p /= p.std() + 1e-3
    return p


def analyze(src: Path, start: float, dur: float, info: dict, words: list[dict]) -> CameraPath:
    ec = CFG.engine_c
    sw, sh = info["width"], info["height"]
    crop_h = sh
    crop_w = int(round(sh * 9 / 16)) // 2 * 2
    if crop_w > sw:                       # source narrower than 9:16 -> crop height instead
        crop_w = sw // 2 * 2
        crop_h = int(round(sw * 16 / 9)) // 2 * 2
    aw = ANALYSIS_W if sw > ANALYSIS_W else sw // 2 * 2
    ah = int(round(sh * aw / sw)) // 2 * 2
    scale = sw / aw
    fps = ec.analysis_fps

    base = CameraPath(np.array([0.0, dur]), np.array([sw / 2, sw / 2]), np.array([False, False]),
                      crop_w, crop_h, sw, sh, scale=scale)
    if crop_w >= sw * 0.98:
        return base                       # already vertical: static
    det = _detector(aw, ah)
    if det is None:
        console.print("[yellow]Face model missing (run setup_assets.py) — using centre crop.[/yellow]")
        return base

    speech = np.zeros(int(dur * fps) + 2)
    for w in words:
        a, b = int((w["s"] - start) * fps), int((w["e"] - start) * fps) + 1
        speech[max(0, a):max(0, min(len(speech), b))] = 1.0

    tracks: list[Track] = []
    next_id = 0
    samples: list[list[Face]] = []
    activity: list[dict[int, float]] = []
    scene_cut: list[bool] = []
    prev_small = None
    total = int(dur * fps)

    with Progress(TextColumn("[yellow]Tracking speakers"), BarColumn(),
                  TextColumn("{task.percentage:>3.0f}%"), console=console) as prog:
        task = prog.add_task("a", total=max(1, total))
        for k, frame in enumerate(FrameReader(src, start, dur, aw, ah, fps=fps)):
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            small = cv2.resize(gray, (64, 36)).astype(np.float32)
            cut = prev_small is not None and float(np.mean(np.abs(small - prev_small))) > 28
            prev_small = small
            scene_cut.append(cut)
            if cut:
                for tr in tracks:
                    tr.prev_patch = None

            _, dets = det.detect(bgr)
            faces = []
            if dets is not None:
                for d in dets:
                    x, y, w, h = d[:4]
                    if w < aw * 0.035:
                        continue                      # tiny background faces
                    faces.append(Face(x, y, w, h, d[4:14].reshape(5, 2), float(d[14])))

            # Greedy association by centre distance.
            used = set()
            for f in sorted(faces, key=lambda f: -f.w):
                best, bd = None, 1e9
                for tr in tracks:
                    if tr.id in used or k - tr.last_t > fps * 3:
                        continue
                    dd = abs(f.cx - tr.last.cx) + abs((f.y + f.h / 2) - (tr.last.y + tr.last.h / 2))
                    if dd < max(f.w, tr.last.w) * 0.9 and dd < bd:
                        best, bd = tr, dd
                if best is None:
                    best = Track(next_id, f, k)
                    next_id += 1
                    tracks.append(best)
                used.add(best.id)
                f.track = best.id
                best.last, best.last_t = f, k
                best.hits += 1

            act = {}
            for f in faces:
                tr = next(t for t in tracks if t.id == f.track)
                patch = _mouth_patch(gray, f)
                if patch is not None and tr.prev_patch is not None:
                    act[f.track] = float(np.mean(np.abs(patch - tr.prev_patch)))
                else:
                    act[f.track] = 0.0
                tr.prev_patch = patch
            samples.append(faces)
            activity.append(act)
            prog.update(task, completed=k + 1)

    n = len(samples)
    if n == 0:
        return base
    # Ignore flicker tracks.
    valid = {t.id for t in tracks if t.hits >= max(3, n * 0.04)}
    if not valid:
        return base
    ids = sorted(valid)
    col = {tid: i for i, tid in enumerate(ids)}
    A = np.zeros((n, len(ids)), np.float32)
    present = np.zeros((n, len(ids)), bool)
    for k in range(n):
        for tid, v in activity[k].items():
            if tid in col:
                A[k, col[tid]] = v * (0.35 + 0.65 * speech[min(k, len(speech) - 1)])
                present[k, col[tid]] = True
    # Smooth activity (~0.7 s window).
    win = max(1, int(fps * 0.7))
    kern = np.ones(win) / win
    S = np.stack([np.convolve(A[:, j], kern, mode="same") for j in range(len(ids))], 1)
    S[~present] = -1

    raw = np.where(present.any(1), S.argmax(1), -1)
    # Fill gaps (no face) with previous label.
    for k in range(1, n):
        if raw[k] == -1:
            raw[k] = raw[k - 1]
    if raw[0] == -1:
        nz = raw[raw >= 0]
        raw[raw == -1] = nz[0] if len(nz) else 0

    labels = _min_duration_filter(raw, int(ec.switch_hold_seconds * fps), scene_cut)

    # Last known centre per track (analysis px).
    centers = np.full((n, len(ids)), np.nan)
    for k in range(n):
        for f in samples[k]:
            if f.track in col:
                centers[k, col[f.track]] = f.cx
    for j in range(len(ids)):                       # forward/back fill
        c = centers[:, j]
        idx = np.where(~np.isnan(c))[0]
        if len(idx):
            centers[:, j] = np.interp(np.arange(n), idx, c[idx])

    crop_w_a = crop_w / scale
    target = np.empty(n)
    for k in range(n):
        vis = [f.cx for f in samples[k] if f.track in col]
        if len(vis) >= 2 and (max(vis) - min(vis)) < crop_w_a * 0.6:
            target[k] = (max(vis) + min(vis)) / 2   # everyone fits: frame the group
        else:
            target[k] = centers[k, labels[k]]

    cam = np.empty(n)
    cuts = np.zeros(n, bool)
    dead = crop_w_a * 0.07
    cam[0] = target[0]
    cuts[0] = True
    for k in range(1, n):
        if labels[k] != labels[k - 1] or scene_cut[k]:
            cam[k] = target[k]
            cuts[k] = True
        else:
            diff = target[k] - cam[k - 1]
            cam[k] = cam[k - 1] + (diff - np.sign(diff) * dead) * 0.18 if abs(diff) > dead \
                else cam[k - 1]

    return CameraPath(np.arange(n) / fps, cam * scale, cuts, crop_w, crop_h, sw, sh,
                      faces=samples, active=np.array([ids[l] for l in labels]), scale=scale)


def _min_duration_filter(labels: np.ndarray, min_len: int, scene_cut: list[bool]) -> np.ndarray:
    """Merge label runs shorter than min_len into a neighbour (the longer one)."""
    lab = labels.copy()
    if min_len <= 1:
        return lab
    while True:
        runs = []
        s = 0
        for k in range(1, len(lab) + 1):
            if k == len(lab) or lab[k] != lab[s]:
                runs.append((s, k))
                s = k
        if len(runs) <= 1:
            return lab
        short = [(e - s, i) for i, (s, e) in enumerate(runs) if e - s < min_len]
        if not short:
            return lab
        _, i = min(short)
        s, e = runs[i]
        prev_len = runs[i - 1][1] - runs[i - 1][0] if i > 0 else -1
        next_len = runs[i + 1][1] - runs[i + 1][0] if i < len(runs) - 1 else -1
        src = runs[i - 1] if prev_len >= next_len else runs[i + 1]
        lab[s:e] = lab[src[0]]
