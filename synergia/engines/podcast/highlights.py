"""Find clip-worthy moments: Claude suggestions via the clipboard bridge, or an offline heuristic."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from synergia.config import CFG
from synergia.llm.prompts import highlights_prompt


@dataclass
class Candidate:
    start: float
    end: float
    title: str = ""
    why: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


# ---------------------------------------------------------------- time helpers
def fmt_ts(t: float) -> str:
    t = max(0, int(round(t)))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_ts(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    parts = s.split(":")
    if not 2 <= len(parts) <= 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        raise ValueError(f"Bad timestamp: {s!r}")
    val = 0.0
    for p in parts:
        val = val * 60 + float(p)
    return val


def parse_range(s: str) -> tuple[float, float]:
    a, b = re.split(r"\s*(?:-|–|to)\s*", s.strip(), maxsplit=1)
    start, end = parse_ts(a), parse_ts(b)
    if end <= start:
        raise ValueError("End must be after start")
    return start, end


# ---------------------------------------------------------------- sentences
@dataclass
class Sentence:
    start: float
    end: float
    text: str
    i0: int  # first word index
    i1: int  # last word index (inclusive)


def sentences(words: list[dict]) -> list[Sentence]:
    out: list[Sentence] = []
    i0 = 0
    for i, w in enumerate(words):
        last = i == len(words) - 1
        gap = (words[i + 1]["s"] - w["e"]) if not last else 0
        if last or re.search(r"[.!?]['\"]?$", w["w"]) or gap > 1.2:
            text = " ".join(x["w"] for x in words[i0:i + 1])
            out.append(Sentence(words[i0]["s"], w["e"], text, i0, i))
            i0 = i + 1
    return out


# ---------------------------------------------------------------- Claude path
def compact_transcript(tr: dict, max_chars: int = 400_000) -> str:
    lines = [f"[{fmt_ts(s['s'])}] {s['text']}" for s in tr["segments"]]
    text = "\n".join(lines)
    return text[:max_chars]


def claude_prompt(tr: dict, title: str) -> str:
    ec = CFG.engine_c
    return highlights_prompt(compact_transcript(tr), ec.min_clip_seconds, ec.max_clip_seconds, title)


def make_validator(duration: float):
    ec = CFG.engine_c

    def validate(data: dict) -> list[str]:
        errors = []
        clips = data.get("clips")
        if not isinstance(clips, list) or not clips:
            return ['"clips" must be a non-empty list']
        for n, c in enumerate(clips, 1):
            try:
                s, e = parse_ts(c.get("start")), parse_ts(c.get("end"))
            except (ValueError, AttributeError) as ex:
                errors.append(f"clip {n}: {ex}")
                continue
            if e <= s:
                errors.append(f"clip {n}: end is before start")
            elif duration and s > duration + 1:
                errors.append(f"clip {n}: start {c.get('start')} is beyond the video length "
                              f"({fmt_ts(duration)})")
            elif (e - s) > hard_max() + 4:
                errors.append(f"clip {n}: {e - s:.0f}s is too long; every clip must be under "
                              f"1 minute (aim for {ec.min_clip_seconds}-{ec.max_clip_seconds}s)")
        return errors

    return validate


def from_claude(data: dict) -> list[Candidate]:
    out = []
    for c in data["clips"]:
        tags = c.get("hashtags") or []
        if isinstance(tags, str):
            tags = tags.split()
        out.append(Candidate(parse_ts(c["start"]), parse_ts(c["end"]), str(c.get("title", "")),
                             str(c.get("why", "")), str(c.get("caption", "")),
                             ["#" + str(t).lstrip("#") for t in tags]))
    return out


# ---------------------------------------------------------------- offline heuristic
HOOK_PATTERNS = [
    r"\bmost people\b", r"\bnobody\b", r"\bno one\b", r"\bnever\b", r"\balways\b",
    r"\bthe truth\b", r"\bthe secret\b", r"\bthe problem\b", r"\bthe biggest\b", r"\bthe reason\b",
    r"\bmistake\b", r"\bregret\b", r"\bi realized\b", r"\bhere'?s the thing\b", r"\bwhat if\b",
    r"\bwhy do\b", r"\bhow do\b", r"\bif you\b", r"\byou need\b", r"\byou have to\b",
    r"\bthe moment\b", r"\bi learned\b", r"\bchanged my life\b", r"\bstop\b",
]
TOPIC_WORDS = [
    "brain", "psycholog", "fear", "anxiety", "love", "relationship", "happiness", "happy", "success",
    "fail", "confidence", "habit", "discipline", "money", "purpose", "meaning", "lonely", "trauma",
    "dopamine", "emotion", "ego", "identity", "therapy", "parents", "childhood", "death", "life",
]


def _score_window(sents: list[Sentence], words: list[dict]) -> float:
    first = sents[0].text.lower()
    full = " ".join(s.text for s in sents).lower()
    dur = sents[-1].end - sents[0].start
    score = 0.0
    score += 2.0 * sum(bool(re.search(p, first)) for p in HOOK_PATTERNS)
    score += 1.5 if first.rstrip().endswith("?") else 0
    score += 0.4 * sum(bool(re.search(p, full)) for p in HOOK_PATTERNS)
    score += 0.35 * sum(full.count(t) for t in TOPIC_WORDS)
    score += 0.6 * len(re.findall(r"\b\d+\b", full))
    you = len(re.findall(r"\byou\b|\byour\b", full))
    score += 0.15 * you
    n_words = sents[-1].i1 - sents[0].i0 + 1
    wps = n_words / max(dur, 1)
    score += 1.0 * min(wps, 3.5)               # energetic, dense speech
    conf = sum(w["p"] for w in words[sents[0].i0:sents[-1].i1 + 1]) / max(1, n_words)
    score *= 0.6 + 0.4 * conf
    # Penalise starting on a connector (mid-thought).
    if re.match(r"^(and|but|so|because|or|which|that|then)\b", first):
        score -= 3
    return score


def heuristic(tr: dict, k: int = 5) -> list[Candidate]:
    ec = CFG.engine_c
    words = tr["words"]
    if not words:
        return []
    sents = sentences(words)
    target_min, target_max = ec.min_clip_seconds, ec.max_clip_seconds
    cands: list[Candidate] = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            dur = sents[j].end - sents[i].start
            if dur > target_max:
                break
            if dur >= max(target_min, 25):
                sc = _score_window(sents[i:j + 1], words)
                sc -= abs(dur - 40) / 20           # prefer ~40s
                cands.append(Candidate(sents[i].start, sents[j].end,
                                       title=sents[i].text[:60], score=sc,
                                       why="heuristic score %.1f" % sc))
    cands.sort(key=lambda c: c.score, reverse=True)
    picked: list[Candidate] = []
    for c in cands:
        if all(c.end <= p.start or c.start >= p.end for p in picked):
            picked.append(c)
        if len(picked) >= k:
            break
    return picked


# ---------------------------------------------------------------- snapping
def snap(start: float, end: float, words: list[dict], window: float = 3.0) -> tuple[float, float]:
    """Move boundaries to nearby sentence edges and word edges; add small padding."""
    if not words:
        return start, end
    sents = sentences(words)
    starts = [s.start for s in sents]
    ends = [s.end for s in sents]
    near_s = [t for t in starts if abs(t - start) <= window]
    near_e = [t for t in ends if abs(t - end) <= window]
    s = min(near_s, key=lambda t: abs(t - start)) if near_s else start
    e = min(near_e, key=lambda t: abs(t - end)) if near_e else end
    # Ensure we don't cut a word in half.
    for w in words:
        if w["s"] < s < w["e"]:
            s = w["s"]
        if w["s"] < e < w["e"]:
            e = w["e"]
    return max(0.0, s - 0.12), e + 0.35


# ---------------------------------------------------------------- length cap
def hard_max() -> float:
    return float(getattr(CFG.engine_c, "hard_max_seconds", 59))


def fit_limit(start: float, end: float, words: list[dict],
              limit: float | None = None) -> tuple[float, float]:
    """Keep a clip strictly under `limit` seconds (default hard_max_seconds, < 1 minute).

    Trims the end back to the last sentence that finishes in time; failing that, the last whole
    word; failing that, a hard cut. Includes the 0.35s tail padding that snap() adds.
    """
    limit = limit or hard_max()
    if end - start <= limit:
        return start, end
    latest = start + limit - 0.35
    in_clip = [w for w in words if w["s"] >= start - 0.2 and w["e"] <= latest]
    sent_ends = [s.end for s in sentences(in_clip)] if in_clip else []
    # Prefer a sentence end, as long as it keeps at least ~60% of the allowed length.
    good = [t for t in sent_ends if t - start >= limit * 0.6 and t <= latest]
    if good:
        return start, min(good[-1] + 0.35, start + limit)
    if in_clip:
        return start, min(in_clip[-1]["e"] + 0.35, start + limit)
    return start, start + limit
