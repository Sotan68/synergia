"""Dynamic word-by-word highlighted subtitles as an ASS file (burned in by ffmpeg/libass)."""
from __future__ import annotations

import re
from pathlib import Path

from synergia.config import CFG, hex_to_rgb


def ass_color(hex_color: str, alpha: int = 0) -> str:
    r, g, b = hex_to_rgb(hex_color)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(word: str) -> str:
    w = word.replace("\\", "").replace("{", "(").replace("}", ")")
    w = re.sub(r"[,;:]+$", "", w)   # trailing commas look noisy in captions
    return w.upper()


def group_words(words: list[dict], max_words: int) -> list[list[dict]]:
    groups: list[list[dict]] = []
    cur: list[dict] = []
    # Keep each group on one line: ~0.62*font-size px per uppercase char within ~810px.
    max_chars = max(8, int(810 / (CFG.engine_c.subtitle_font_size * 0.62)))
    for i, w in enumerate(words):
        if cur:
            gap = w["s"] - cur[-1]["e"]
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if len(cur) >= max_words or gap > 0.6 or chars > max_chars \
                    or re.search(r"[.!?,;:]$", cur[-1]["w"]):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[dict], clip_start: float, clip_end: float, out: Path,
              title: str = "") -> Path:
    """words: absolute-time words; output times are relative to clip_start."""
    ec = CFG.engine_c
    b = CFG.brand
    W, H = b.width, b.height
    text_c = ass_color(b.text)
    acc_c = ass_color(b.accent)
    title_box = ass_color(b.accent2, alpha=0x30)   # purple, slightly see-through
    black = "&H00000000"
    shadow = "&H64000000"
    fs = ec.subtitle_font_size

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Inter,{fs},{text_c},{acc_c},{black},{shadow},-1,0,0,0,100,100,0,0,1,6,3,5,120,150,0,1
Style: Title,Inter,54,{text_c},{acc_c},{title_box},&H00000000,-1,0,0,0,100,100,1,0,3,20,0,8,110,150,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    clip_words = [w for w in words if w["e"] > clip_start and w["s"] < clip_end]
    groups = group_words(clip_words, ec.words_per_group)
    y = ec.subtitle_y
    pos = f"\\an5\\pos({W // 2},{y})"
    for gi, g in enumerate(groups):
        g_end = g[-1]["e"]
        if gi + 1 < len(groups) and groups[gi + 1][0]["s"] - g_end < 0.35:
            g_end = groups[gi + 1][0]["s"]          # avoid flicker between close groups
        for wi, w in enumerate(g):
            s = w["s"] if wi else min(w["s"], g[0]["s"])
            e = g[wi + 1]["s"] if wi + 1 < len(g) else g_end
            if e <= s:
                continue
            parts = []
            for j, x in enumerate(g):
                t = _clean(x["w"])
                if j == wi:
                    parts.append(f"{{\\c{acc_c}\\fscx108\\fscy108}}{t}{{\\c{text_c}\\fscx100\\fscy100}}")
                else:
                    parts.append(t)
            pop = "\\t(0,80,\\fscx104\\fscy104)\\t(80,160,\\fscx100\\fscy100)" if wi == 0 else ""
            text = f"{{{pos}{pop}}}" + " ".join(parts)
            events.append(f"Dialogue: 0,{_ts(s - clip_start)},{_ts(e - clip_start)},Sub,,0,0,0,,{text}")

    if title:
        t = title.replace("{", "(").replace("}", ")").replace("**", "")
        top = getattr(ec, "title_y", CFG.safe_zone.top + 20) + 20   # + box padding
        clip_len = clip_end - clip_start
        hold = getattr(ec, "title_seconds", 3.5)
        t_end = min(hold, clip_len) if hold > 0 else clip_len
        fade = "\\fad(250,400)" if hold > 0 else "\\fad(250,0)"
        events.append(f"Dialogue: 1,{_ts(0)},{_ts(t_end)},Title,,0,0,0,,"
                      f"{{\\an8\\pos({W // 2},{top}){fade}}}{t}")

    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return out
