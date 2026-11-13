"""Interactive console for Synergia."""
from __future__ import annotations

import os
import traceback
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from synergia import demo
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
    if os.environ.get("SYNERGIA_NO_OPEN"):
        return
    try:
        os.startfile(out)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


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
                      "[dim]\\[Q] Quit[/dim]")
        try:
            raw = Prompt.ask(">", default="", show_default=False)
        except EOFError:
            return
        letters = [ch for ch in raw.lower() if ch in "abcq"]
        if not letters:
            console.print("[dim]Type A, B, C or Q.[/dim]")
            continue
        choice = letters[0]
        if choice == "q":
            return
        try:
            if choice == "a":
                engine_a(is_demo, debug)
            elif choice == "b":
                engine_b(is_demo, debug)
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
