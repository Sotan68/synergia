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
from synergia.brand.typography import strip_markup
from synergia.llm.bridge import Cancelled, ask_claude, review
from synergia.output import ENABLED, ENGINE_NAMES
from synergia.video import have_ffmpeg

console = Console()

BANNER = f"""[bold #8FA8FF]{" ".join(CFG.brand.name.upper())}[/bold #8FA8FF]
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
    return sch.next_slot()


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
        Prompt.ask(f"[bold]Concept[/bold] [dim](e.g. {escape(CFG.voice.examples.concept)})[/dim]").strip()
    if not concept:
        return
    data = _script_loop(psychology, concept, demo.PSYCHOLOGY if is_demo else None,
                        f"{ENGINE_NAMES['A']}: {concept}")
    with console.status("[yellow]Rendering frames and video…"):
        out = psychology.produce(data, debug=debug)
    _done(out)


def engine_b(is_demo: bool, debug: bool) -> None:
    hook = demo.LISTICLE["cover_title"] if is_demo else \
        Prompt.ask(f"[bold]Hook[/bold] [dim](e.g. {escape(CFG.voice.examples.hook)})[/dim]").strip()
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


def engine_d(debug: bool) -> None:
    from synergia.engines import brain

    with console.status("[yellow]Generating rounds and rendering the video…"):
        out = brain.produce(debug=debug)
    _done(out)


def _pick_topic(mode: str) -> str:
    """Ask for a topic; Enter asks Claude for 10 fresh ones (avoiding past topics)."""
    from synergia import history
    from synergia.llm.prompts import topics_prompt

    ex = CFG.voice.examples
    example = escape(ex.checklist_topic if mode == "checklist" else ex.pick_topic)
    topic = Prompt.ask(f"[bold]Topic[/bold] [dim](e.g. {example}; Enter = suggest 10)[/dim]",
                       default="", show_default=False).strip()
    if topic:
        return topic

    def check(d: dict) -> list[str]:
        t = d.get("topics")
        if not isinstance(t, list) or len([x for x in t if str(x).strip()]) < 5:
            return ['"topics" must be a list of about 10 short strings']
        d["topics"] = [str(x).strip() for x in t if str(x).strip()][:10]
        return []

    topics = ask_claude(topics_prompt(mode, history.recent("identity.topics")), check,
                        title="Topic ideas")["topics"]
    for i, t in enumerate(topics, 1):
        console.print(f"  [#8FA8FF]{i:>2}[/#8FA8FF] {escape(t)}")
    raw = Prompt.ask("Number, or type your own", default="1").strip()
    return topics[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(topics) else raw


def engine_e(is_demo: bool, debug: bool) -> None:
    from synergia.engines import identity

    console.print("[bold]Format:[/bold]  [#8FA8FF]1[/#8FA8FF] How many apply to you?   "
                  "[#8FA8FF]2[/#8FA8FF] Pick one → reveal")
    raw = Prompt.ask(">", default="1", show_default=False).strip().lower()
    if raw in ("b", "q"):
        return
    mode = "pick" if raw == "2" else "checklist"
    eng = identity.Pick if mode == "pick" else identity.Checklist
    demo_data = (demo.PICK if mode == "pick" else demo.CHECKLIST) if is_demo else None
    topic = strip_markup(demo_data["cover_title"]) if demo_data else _pick_topic(mode)
    if not topic:
        return
    data = _script_loop(eng, topic, demo_data, f"{ENGINE_NAMES['E']}: {topic}")
    data["topic"] = topic
    with console.status("[yellow]Rendering slides and video…"):
        produce = identity.produce_pick if mode == "pick" else identity.produce_checklist
        out = produce(data, debug=debug)
    _done(out)


def setup_wizard() -> bool:
    """First launch in the console: brand, niche (Claude drafts the writing), theme, engines.
    Writes profile.toml. The browser version (python main.py --gui) also lets you edit every
    drafted field and shows theme previews. Returns True if a profile was saved."""
    from synergia import profile
    from synergia.brand import themes

    console.print(Panel("[bold]Set up your Synergia[/bold]\nA few questions; change anything later "
                        "in profile.toml or the browser Settings page.", border_style="#A78BFA",
                        expand=False))
    name = Prompt.ask("[bold]Brand name[/bold] [dim](shown in every slide footer)[/dim]").strip()
    desc = Prompt.ask("[bold]What is your channel about?[/bold] [dim](a sentence or two)[/dim]").strip()
    audience = Prompt.ask("[bold]Who is it for?[/bold] [dim](optional)[/dim]", default="",
                          show_default=False).strip()
    if not name or not desc:
        console.print("[red]A name and a description are needed.[/red]")
        return False
    try:
        draft = ask_claude(profile.draft_prompt(name, desc, audience), profile.validate_draft,
                           "Draft your brand")
    except Cancelled:
        return False
    ea = draft["engine_a"]
    console.print(f"\n[bold]Niche:[/bold] {escape(draft['niche'])}\n[bold]Tone:[/bold] {escape(draft['tone'])}"
                  f"\n[bold]Engine A slides:[/bold] {escape(' / '.join(ea['step_labels']))}"
                  f"\n[bold]Example concepts:[/bold] {escape(', '.join(draft['concept_examples']))}"
                  f"\n[bold]Hashtags (A):[/bold] {escape(' '.join(draft['hashtags']['A']))}")
    console.print("\n[bold]Themes:[/bold]")
    keys = list(themes.THEMES)
    for i, k in enumerate(keys, 1):
        console.print(f"  [#8FA8FF]{i}[/#8FA8FF] {themes.THEMES[k]['label']}: "
                      f"[dim]{escape(themes.THEMES[k]['blurb'])}[/dim]")
    pick = Prompt.ask("Theme", choices=[str(i) for i in range(1, len(keys) + 1)], default="1")
    suggested = "".join(draft["engines"])
    raw = Prompt.ask("[bold]Engines[/bold] [dim](letters, e.g. ABDE)[/dim]", default=suggested)
    engines = [e for e in "ABCDE" if e in raw.upper()] or list(suggested)
    folder = profile.create(profile.from_draft(name, draft, keys[int(pick) - 1], engines, audience))
    console.print(f"[green]Saved profiles/{folder}/profile.toml.[/green] Edit it any time, or use "
                  f"Settings in the browser interface.")
    return True


def _restart() -> None:
    """Start again so every module picks up the (new) active profile."""
    import sys

    env_argv = [a for a in sys.argv]
    if "--profile" in env_argv:
        i = env_argv.index("--profile")
        del env_argv[i:i + 2]
    os.environ.pop("SYNERGIA_PROFILE_NAME", None)
    os.execv(sys.executable, [sys.executable, *env_argv])


def profiles_menu() -> None:
    """Switch to another profile, or set up a new one."""
    from synergia.config import list_profiles, profile_dir, read_profile, set_active

    names = list_profiles()
    console.print("\n[bold]Profiles[/bold]")
    for i, n in enumerate(names, 1):
        label = (read_profile(profile_dir(n) / "profile.toml").get("brand") or {}).get("name") or n
        mark = "[green]●[/green]" if n == CFG.profile_name else " "
        console.print(f" {mark} [#8FA8FF]{i}[/#8FA8FF] {escape(str(label))} [dim]({n})[/dim]")
    console.print("   [#8FA8FF]N[/#8FA8FF] New profile")
    raw = Prompt.ask("Pick one (Enter = back)", default="", show_default=False).strip().lower()
    if raw == "n":
        if setup_wizard():
            _restart()
    elif raw.isdigit() and 1 <= int(raw) <= len(names) and names[int(raw) - 1] != CFG.profile_name:
        set_active(names[int(raw) - 1])
        _restart()


def main(is_demo: bool = False, debug: bool = False) -> None:
    if not CFG.configured:
        if setup_wizard():   # start again so every module picks up the new profile
            _restart()
        return
    console.print(Panel(BANNER, border_style="#8FA8FF", expand=False, padding=(1, 4)))
    if not have_ffmpeg():
        console.print("[red]ffmpeg/ffprobe not found on PATH. Install ffmpeg and retry.[/red]")
        return
    if is_demo:
        console.print("[dim]Demo mode: Engines A/B/E use built-in sample scripts (no Claude round-trip).[/dim]")
    while True:
        engines = "".join(f"[#8FA8FF]\\[{k}][/#8FA8FF] {escape(ENGINE_NAMES[k])}   " for k in ENABLED)
        console.print(f"\n[dim]{escape(CFG.brand.name)}[/dim]  [bold]Choose your Engine:[/bold]  " + engines +
                      "[#8FA8FF]\\[U][/#8FA8FF] Upload to YouTube   "
                      "[#8FA8FF]\\[P][/#8FA8FF] Profiles   "
                      "[dim]\\[Q] Quit[/dim]")
        try:
            raw = Prompt.ask(">", default="", show_default=False)
        except EOFError:
            return
        letters = [ch for ch in raw.lower() if ch in "".join(ENABLED).lower() + "upq"]
        if not letters:
            console.print(f"[dim]Type {', '.join(ENABLED)}, U, P or Q.[/dim]")
            continue
        choice = letters[0]
        if choice == "q":
            return
        try:
            if choice == "a":
                engine_a(is_demo, debug)
            elif choice == "b":
                engine_b(is_demo, debug)
            elif choice == "d":
                engine_d(debug)
            elif choice == "e":
                engine_e(is_demo, debug)
            elif choice == "u":
                upload_menu()
            elif choice == "p":
                profiles_menu()
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
