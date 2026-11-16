"""Engine C — interactive flow: source -> transcript -> pick highlight -> render."""
from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from synergia.config import CFG
from synergia.engines.podcast import highlights as hl
from synergia.engines.podcast.render import render_clip
from synergia.engines.podcast.source import resolve
from synergia.engines.podcast.transcribe import transcribe
from synergia.llm.bridge import Skipped, ask_claude
from synergia.output import run_dir, save_meta
from synergia.video import video_info

console = Console()


def _show(cands: list[hl.Candidate], source: str) -> None:
    t = Table(title=f"Highlight candidates ({source})", border_style="#8FA8FF", show_lines=True)
    t.add_column("#", style="bold #A78BFA", width=3)
    t.add_column("Range", style="cyan", no_wrap=True)
    t.add_column("Len", justify="right")
    t.add_column("Title / opening")
    t.add_column("Why", style="dim")
    for i, c in enumerate(cands, 1):
        t.add_row(str(i), f"{hl.fmt_ts(c.start)}–{hl.fmt_ts(c.end)}", f"{c.duration:.0f}s",
                  c.title, c.why)
    console.print(t)


def credit_text(credit: dict) -> str:
    """Caption credit block: '<prefix> Channel (@handle)', the video title, and the link."""
    who = credit.get("channel", "").strip()
    handle = credit.get("handle", "").strip()
    if handle.startswith("@") and handle[1:].lower() != who.replace(" ", "").lower():
        who = f"{who} ({handle})" if who else handle
    if not who:
        return ""
    lines = [f"{CFG.engine_c.credit_prefix} {who}"]
    if credit.get("title"):
        lines.append(f'"{credit["title"]}"')
    if credit.get("url"):
        lines.append(credit["url"])
    return "\n".join(lines)


# ---------------------------------------------------------------- steps (no prompts; the GUI uses these)

def load_source(inp: str) -> tuple[Path, str, dict, dict]:
    """URL or local path -> (video file, display name, credit dict, video_info)."""
    src, name, credit = resolve(inp)
    return src, name, credit, video_info(src)


def range_clip(src: Path, info: dict, rng: str) -> tuple[dict, hl.Candidate]:
    """A typed range like '12:30-13:15': transcribe just that part, snap to word edges."""
    s, e = hl.parse_range(rng)
    e = min(e, info["duration"])
    pad_s, pad_e = max(0.0, s - 3), min(info["duration"], e + 3)
    tr = transcribe(src, pad_s, pad_e)
    s, e = hl.snap(s, e, tr["words"], window=1.5)
    return tr, hl.Candidate(s, e)


def full_transcript(src: Path, info: dict) -> dict:
    tr = transcribe(src, total_duration=info["duration"])
    if not tr["words"]:
        raise RuntimeError("No speech was detected in this video.")
    return tr


def candidates(tr: dict, claude_data: dict | None = None) -> tuple[list[hl.Candidate], str]:
    """Highlights from Claude's reply, or from the offline heuristic when claude_data is None."""
    if claude_data is not None:
        cands, label = hl.from_claude(claude_data), "Claude"
    else:
        cands, label = hl.heuristic(tr), "offline heuristic"
    if not cands:
        raise RuntimeError("No highlight candidates found.")
    return cands, label


def pick(choice: str, cands: list[hl.Candidate], words: list[dict]) -> list[hl.Candidate]:
    """'all', '1,3' or 'mm:ss-mm:ss' -> picked candidates, snapped to sentence edges. Raises ValueError."""
    picked = _parse_pick(choice, cands)
    for p in picked:
        p.start, p.end = hl.snap(p.start, p.end, words)
    return picked


def suggested_title(c: hl.Candidate) -> str:
    return c.title if c.why and not c.why.startswith("heuristic") else ""


def render_picked(src: Path, info: dict, name: str, picked: list[hl.Candidate], words: list[dict],
                  title: str | None = None, debug: bool = False, credit: str = "") -> Path:
    """Render one clip (with `title`; None = the suggested one) or several (each with its suggested title)."""
    if len(picked) > 1:
        return _render_batch(src, info, name, picked, words, debug, credit)
    c = picked[0]
    c.end = min(c.end, info["duration"])
    return _render_one(src, info, name, c, suggested_title(c) if title is None else title,
                       words, debug, credit)


# ---------------------------------------------------------------- console flow

def run(inp: str, debug: bool = False) -> Path:
    with console.status("[yellow]Fetching source…"):
        src, name, credit, info = load_source(inp)
    console.print(f"[green]✓[/green] {name}  [dim]{info['width']}x{info['height']} "
                  f"@ {info['fps']:.2f}fps, {hl.fmt_ts(info['duration'])}[/dim]")
    if not credit:
        who = Prompt.ask("Credit [dim](show / channel to credit in the caption, Enter to skip)[/dim]",
                         default="", show_default=False).strip()
        credit = {"channel": who} if who else {}
    credit_str = credit_text(credit)
    if credit_str:
        console.print(f"[dim]Caption credit:[/dim] {credit_str.splitlines()[0]}")

    rng = Prompt.ask("Clip range [dim](e.g. 12:30-13:15)[/dim], or [bold]Enter[/bold] to find highlights",
                     default="", show_default=False).strip()
    if rng:
        tr, chosen = range_clip(src, info, rng)
    else:
        tr = full_transcript(src, info)
        try:
            data = ask_claude(hl.claude_prompt(tr, name), hl.make_validator(info["duration"]),
                              title="Find highlights with Claude", allow_skip=True)
        except Skipped:
            data = None
        cands, label = candidates(tr, data)
        _show(cands, label)
        picked: list[hl.Candidate] = []
        while not picked:
            c = Prompt.ask("Pick [bold]all[/bold], one or more [bold]#[/bold] (e.g. 1,3,5), "
                           "or a custom range mm:ss-mm:ss", default="all").strip().lower()
            try:
                picked = pick(c, cands, tr["words"])
            except ValueError as ex:
                console.print(f"[red]{ex}[/red]")
        if len(picked) > 1:
            return render_picked(src, info, name, picked, tr["words"], debug=debug, credit=credit_str)
        chosen = picked[0]

    chosen.end = min(chosen.end, info["duration"])
    _cap(chosen, tr["words"])
    console.print(f"[green]✓[/green] Clip {hl.fmt_ts(chosen.start)}–{hl.fmt_ts(chosen.end)} "
                  f"({chosen.duration:.1f}s)")
    title = Prompt.ask("On-screen title [dim](Enter keeps, '-' for none)[/dim]",
                       default=suggested_title(chosen) or "-").strip()
    title = "" if title == "-" else title

    return render_picked(src, info, name, [chosen], tr["words"], title, debug, credit_str)


def _cap(c: hl.Candidate, words: list[dict]) -> None:
    """Enforce the < 1 minute rule (hard_max_seconds); trims at a sentence end."""
    before = c.duration
    c.start, c.end = hl.fit_limit(c.start, c.end, words)
    if c.duration < before - 0.01:
        console.print(f"[yellow]Trimmed {before:.1f}s -> {c.duration:.1f}s "
                      f"(clips must stay under {hl.hard_max():.0f}s)[/yellow]")


def _parse_pick(c: str, cands: list[hl.Candidate]) -> list[hl.Candidate]:
    if c in ("", "all", "a"):
        return list(cands)
    if re.fullmatch(r"\d+(\s*[, ]\s*\d+)*", c):
        nums = [int(n) for n in re.split(r"[,\s]+", c) if n]
        bad = [n for n in nums if not 1 <= n <= len(cands)]
        if bad:
            raise ValueError(f"No candidate #{bad[0]} (choose 1-{len(cands)})")
        return [cands[n - 1] for n in dict.fromkeys(nums)]
    s, e = hl.parse_range(c)
    return [hl.Candidate(s, e)]


def _render_one(src: Path, info: dict, name: str, c: hl.Candidate, title: str,
                words: list[dict], debug: bool, credit: str = "") -> Path:
    _cap(c, words)
    out = run_dir("C", title or name)
    render_clip(src, info, c.start, c.end, words, out, title=title, debug=debug)
    claude_title = suggested_title(c)
    save_meta(out, {"source": str(src), "source_title": name, "start": c.start,
                    "end": c.end, "title": title,
                    "post_title": title or claude_title or name,
                    "caption": c.caption,
                    "credit": credit, "hashtags": c.hashtags})
    return out


def _render_batch(src: Path, info: dict, name: str, picked: list[hl.Candidate],
                  words: list[dict], debug: bool, credit: str = "") -> Path:
    """Render several clips in a row; each uses its suggested title (no per-clip prompt)."""
    outs: list[Path] = []
    for i, c in enumerate(picked, 1):
        c.end = min(c.end, info["duration"])
        _cap(c, words)
        title = suggested_title(c)
        console.print(f"\n[bold]Clip {i}/{len(picked)}[/bold]  {hl.fmt_ts(c.start)}–"
                      f"{hl.fmt_ts(c.end)} ({c.duration:.1f}s)  [dim]{title}[/dim]")
        try:
            outs.append(_render_one(src, info, name, c, title, words, debug, credit))
        except Exception as ex:  # noqa: BLE001 — keep going with the other clips
            console.print(f"[red]Clip {i} failed:[/red] {ex}")
    if not outs:
        raise RuntimeError("None of the clips rendered.")
    console.print(f"\n[green]✓[/green] Rendered {len(outs)}/{len(picked)} clips:")
    for o in outs:
        console.print(f"  [dim]{o}[/dim]")
    return outs[0].parent
