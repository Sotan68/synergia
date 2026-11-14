"""Interactive console for Synergia."""
from __future__ import annotations

import os
import traceback
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from synergia import demo
from synergia.config import CFG
from synergia.engines import listicle, psychology
from synergia.llm.bridge import Cancelled, ask_claude, review
from synergia.video import have_ffmpeg

console = Console()

BANNER = """[bold #8FA8FF]S Y N E R G I A[/bold #8FA8FF]
[#8B90B8]Zero-cost short-form content engine[/#8B90B8]"""


def _script_loop(engine, seed_text: str, demo_data: dict | None, title: str) -> dict:
    """Get a validated + reviewed script from Claude (or demo data)."""
    while True:
        if demo_data is not None:
            data = dict(demo_data)
            engine.validate(data)
        else:
            data = ask_claude(engine.prompt(seed_text), engine.validate, title=title)
        if review(data, engine.review_fields(data), title="Review script") == "ok":
            return data
        demo_data = None  # regenerate -> go to Claude


def _done(out: Path) -> None:
    files = "\n".join(f"  • {p.name}" for p in sorted(out.iterdir()) if p.is_file())
    console.print(Panel(f"[green]Saved to[/green] {out}\n{files}", border_style="green"))
    if not os.environ.get("SYNERGIA_NO_OPEN"):
        try:
            os.startfile(out)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    _offer_upload(out)


# ---------------------------------------------------------------- YouTube

def _offer_upload(out: Path) -> None:
    """After a render: offer a YouTube upload, but only once YouTube is set up."""
    from synergia import publish
    from synergia.publish import youtube

    if not (CFG.youtube.ask_after_render and youtube.is_configured() and publish.find_video(out)):
        return
    if Confirm.ask(f"Upload to YouTube ({CFG.youtube.privacy})?", default=False):
        upload_youtube(out)


ASK, NEXT_SLOT, BACK = "ask", "next", "back"   # besides None (now) or a datetime


def _next_slot():
    from synergia.publish import schedule as sch
    try:
        return sch.next_free_slot(sch.parse_slots(CFG.youtube.schedule_slots), sch.taken())
    except (ValueError, AttributeError):
        return None


def _ask_when(batch: bool = False):
    """None = publish now, NEXT_SLOT = next free slot(s), BACK, or a datetime (single video only)."""
    from synergia.publish import schedule as sch
    slot = _next_slot()
    opts = ["Enter = now"]
    if slot:
        opts.append(f"n = next free slot{'s, one per video' if batch else ''} ({sch.fmt(slot)})")
    if not batch:
        opts.append("or a time like [bold]tomorrow 18:00[/bold] / [bold]fri 9:30[/bold]")
    opts.append("b = back")
    while True:
        raw = Prompt.ask(f"When? [dim]{' · '.join(opts)}[/dim]", default="", show_default=False).strip()
        if not raw:
            return None
        if raw.lower() in ("b", "back"):
            return BACK
        if raw.lower() in ("n", "next") and slot:
            return NEXT_SLOT
        if batch:
            console.print("[dim]For several videos: Enter, n or b. To pick exact times, upload one at a time.[/dim]")
            continue
        try:
            return sch.parse_when(raw)
        except ValueError as e:
            console.print(f"[yellow]{e}[/yellow]")


def _confirm(question: str, default: str) -> str:
    """y / n / b (back). Enter takes the default."""
    while True:
        raw = Prompt.ask(f"{question} [#8FA8FF]\\[y/n/b][/#8FA8FF] [dim]({default})[/dim]",
                         default=default, show_default=False).strip().lower()
        if raw[:1] in ("y", "n", "b"):
            return raw[:1]
        console.print("[dim]Type y (upload), n (skip) or b (back).[/dim]")


def upload_youtube(folder: Path, when=ASK) -> str:
    """Preview, ask, upload. Returns 'uploaded', 'skipped' or 'back'."""
    from synergia import publish
    from synergia.publish import schedule as sch
    from synergia.publish import youtube
    from synergia.video import video_info

    post = publish.load_post(folder)
    sn = youtube.build_body(post, CFG.youtube.privacy)["snippet"]
    info = video_info(post.video)
    console.print(Panel(
        f"[bold]{escape(sn['title'])}[/bold]\n\n"
        f"{escape(sn['description']) or '[dim](no description)[/dim]'}\n\n"
        f"[dim]Tags:[/dim] {escape(', '.join(sn['tags'])) or '-'}\n"
        f"[dim]File:[/dim] {post.video.name}  ({info['width']}x{info['height']}, {info['duration']:.1f}s)",
        title="YouTube upload", border_style="#8FA8FF"))
    for w in youtube.shorts_warnings(info):
        console.print(f"[yellow]Not a Short:[/yellow] {w}")
    prev = publish.read_ledger(folder).get("youtube")
    if prev:
        console.print(f"[yellow]Already uploaded[/yellow] on {prev.get('uploaded_at', '?')}: {prev.get('url')}")

    if when == ASK:
        when = _ask_when()
    if when == BACK:
        return "back"
    if when == NEXT_SLOT:
        when = _next_slot()
        if when is None:
            console.print("[yellow]No free slot found (check schedule_slots in config.toml).[/yellow]")
            return "skipped"
    if when:
        console.print(f"[dim]Schedule:[/dim] uploads now as private, goes [bold]public {sch.fmt(when)}[/bold]")
    else:
        console.print(f"[dim]Privacy:[/dim] {CFG.youtube.privacy}, now")
    answer = _confirm("Upload it again?" if prev else "Upload this?", "n" if prev else "y")
    if answer != "y":
        return "back" if answer == "b" else "skipped"

    with console.status("[yellow]Uploading to YouTube… 0%") as st:
        res = youtube.upload(post, publish_at=when, on_progress=lambda f: st.update(
            f"[yellow]Uploading to YouTube… {f:.0%}"))
    if res.get("publish_at"):
        console.print(f"[green]✓ Scheduled[/green] for {sch.fmt(when)}: {res['url']}")
    else:
        console.print(f"[green]✓ Uploaded[/green] ({res['privacy']}): {res['url']}")
    if res.get("schedule_dropped"):
        console.print("[yellow]YouTube ignored the schedule[/yellow] [dim](unaudited API projects can only "
                      "upload private videos). Set it in YouTube Studio: Visibility → Schedule.[/dim]")
    elif not when and res["privacy"] != CFG.youtube.privacy:
        console.print(f"[yellow]YouTube set it to {res['privacy']} instead of {CFG.youtube.privacy}.[/yellow] "
                      "[dim]Unaudited API projects can only upload private videos; "
                      "change it in YouTube Studio.[/dim]")
    return "uploaded"


def upload_menu() -> None:
    from synergia import publish
    from synergia.publish import youtube

    if not youtube.is_configured():
        console.print("[yellow]YouTube isn't set up yet.[/yellow] See 'Uploading to YouTube' in README.md "
                      f"(needs {CFG.youtube.client_secret}).")
        return
    from datetime import datetime

    from synergia.publish import schedule as sch

    while True:   # back to this list after each batch; Enter or b leaves
        runs = publish.recent_runs()
        if not runs:
            console.print("[dim]No rendered videos in output/ yet.[/dim]")
            return
        console.print("\n[bold]Recent videos[/bold]  [dim](✓ = already on YouTube)[/dim]")
        for i, d in enumerate(runs, 1):
            yt = publish.read_ledger(d).get("youtube")
            mark, note = ("[green]✓[/green]" if yt else " "), ""
            if yt and yt.get("publish_at"):
                at = datetime.fromisoformat(yt["publish_at"])
                if at > sch.now():
                    note = f"  [#A78BFA]goes live {sch.fmt(at)}[/#A78BFA]"
            console.print(f"  [#8FA8FF]{i:>2}[/#8FA8FF] {mark} [dim]{d.parent.name[:1]}[/dim]  "
                          f"{escape(d.name)}{note}")
        raw = Prompt.ask("Number(s) to upload, e.g. [bold]1[/bold] or [bold]1 3[/bold] "
                         "[dim](Enter or b = back)[/dim]", default="", show_default=False).strip()
        if not raw or raw.lower() in ("b", "back"):
            return
        picks = list(dict.fromkeys(int(t) for t in raw.replace(",", " ").split()
                                   if t.isdigit() and 1 <= int(t) <= len(runs)))
        if not picks:
            console.print(f"[dim]Type numbers from 1 to {len(runs)}, or b to go back.[/dim]")
            continue
        when = _ask_when(batch=True) if len(picks) > 1 else ASK
        if when == BACK:
            continue
        for n in picks:
            try:
                if upload_youtube(runs[n - 1], when) == "back":
                    break
            except youtube.NotConfigured as e:
                console.print(f"[yellow]{e}[/yellow]")
                return
            except Exception as e:  # noqa: BLE001 — report and continue with the next pick
                console.print(f"[red]Upload failed:[/red] {escape(str(e))}")
                if youtube.is_limit_error(e):
                    console.print("[dim]Stopping this batch; the rest would hit the same limit.[/dim]")
                    break

def engine_a(is_demo: bool, debug: bool) -> None:
    concept = demo.PSYCHOLOGY["concept"] if is_demo else \
        Prompt.ask("[bold]Concept[/bold] [dim](e.g. The Spotlight Effect)[/dim]").strip()
    if not concept:
        return
    data = _script_loop(psychology, concept, demo.PSYCHOLOGY if is_demo else None,
                        f"Psychology Explainer: {concept}")
    with console.status("[yellow]Rendering frames and video…"):
        out = psychology.produce(data, debug=debug)
    _done(out)


def engine_b(is_demo: bool, debug: bool) -> None:
    hook = demo.LISTICLE["cover_title"] if is_demo else \
        Prompt.ask("[bold]Hook[/bold] [dim](e.g. 5 things people regret not doing after 25)[/dim]").strip()
    if not hook:
        return
    data = _script_loop(listicle, hook, demo.LISTICLE if is_demo else None, f"Slideshow: {hook}")
    with console.status("[yellow]Rendering slides and video…"):
        out = listicle.produce(data, debug=debug)
    _done(out)


def engine_c(debug: bool) -> None:
    from synergia.engines.podcast import engine  # heavy imports only when needed

    inp = Prompt.ask("[bold]YouTube URL or local .mp4 path[/bold]").strip()
    if not inp:
        return
    _done(engine.run(inp, debug=debug))


def main(is_demo: bool = False, debug: bool = False) -> None:
    console.print(Panel(BANNER, border_style="#8FA8FF", expand=False, padding=(1, 4)))
    if not have_ffmpeg():
        console.print("[red]ffmpeg/ffprobe not found on PATH. Install ffmpeg and retry.[/red]")
        return
    if is_demo:
        console.print("[dim]Demo mode: Engines A/B use built-in sample scripts (no Claude round-trip).[/dim]")
    while True:
        console.print("\n[bold]Choose your Engine:[/bold]  "
                      "[#8FA8FF]\\[A][/#8FA8FF] Psychology Explainer   "
                      "[#8FA8FF]\\[B][/#8FA8FF] Random Fact Slideshow   "
                      "[#8FA8FF]\\[C][/#8FA8FF] Podcast Clipper   "
                      "[#8FA8FF]\\[U][/#8FA8FF] Upload to YouTube   "
                      "[dim]\\[Q] Quit[/dim]")
        try:
            raw = Prompt.ask(">", default="", show_default=False)
        except EOFError:
            return
        letters = [ch for ch in raw.lower() if ch in "abcuq"]
        if not letters:
            console.print("[dim]Type A, B, C, U or Q.[/dim]")
            continue
        choice = letters[0]
        if choice == "q":
            return
        try:
            if choice == "a":
                engine_a(is_demo, debug)
            elif choice == "b":
                engine_b(is_demo, debug)
            elif choice == "u":
                upload_menu()
            else:
                engine_c(debug)
        except Cancelled:
            console.print("[dim]Cancelled.[/dim]")
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Error:[/red] {e}")
            if debug:
                console.print(traceback.format_exc())
