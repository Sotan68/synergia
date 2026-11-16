"""Create page: one tab per engine, each a short step-by-step flow."""
from __future__ import annotations

from nicegui import ui

from synergia import demo
from synergia.brand.typography import strip_markup
from synergia.gui.components import S, busy, claude_step, run_preview, script_editor, section

ENGINES = [("A", "Psychology Explainer"), ("B", "Random Fact Slideshow"), ("C", "Podcast Clipper"),
           ("D", "Brain Test"), ("E", "Which One Are You")]


def _heading(text: str, sub: str = "") -> None:
    ui.label(text).classes("text-xl font-semibold")
    if sub:
        ui.label(sub).classes("text-sm opacity-60 -mt-2")


# ---------------------------------------------------------------- shared script flow (A, B, E)

def script_flow(area, engine, topic: str, demo_data: dict | None, title: str, produce,
                restart, before_render=None) -> None:
    """Claude (or demo data) -> editable script -> render -> preview."""

    def ask() -> None:
        with section(area):
            claude_step(engine.prompt(topic), engine.validate, title, on_done=edit, on_cancel=restart)

    def edit(data: dict) -> None:
        async def render() -> None:
            if before_render:
                before_render(data)
            out = await busy("Rendering slides and video…", produce, data, debug=S.debug)
            if out:
                with section(area):
                    run_preview(out, on_new=restart)

        with section(area):
            script_editor(data, engine.review_fields(data), on_render=render, on_regen=ask,
                          on_cancel=restart)

    if demo_data is not None:
        data = dict(demo_data)
        engine.validate(data)
        edit(data)
    else:
        ask()


# ---------------------------------------------------------------- A / B

def _seed_flow(area, letter: str, engine, label: str, example: str, demo_data: dict, demo_key: str,
               title_prefix: str) -> None:
    def start() -> None:
        with section(area):
            name = dict(ENGINES)[letter]
            _heading(f"Engine {letter} · {name}")
            if S.is_demo:
                ui.label("Demo mode: uses the built-in sample script.").classes("text-sm opacity-60")
            seed = ui.input(label, placeholder=example, value=demo_data[demo_key] if S.is_demo else "") \
                .classes("w-full max-w-xl").props("outlined autofocus")

            def go() -> None:
                text = strip_markup(seed.value.strip())
                if not text:
                    ui.notify(f"Type a {label.lower()} first.", type="warning")
                    return
                script_flow(area, engine, text, demo_data if S.is_demo else None,
                            f"{title_prefix}: {text}", engine.produce, start)
            seed.on("keydown.enter", go)
            ui.button("Write the script", icon="auto_awesome", on_click=go)
    start()


def engine_a(area) -> None:
    from synergia.engines import psychology
    _seed_flow(area, "A", psychology, "Concept", "The Spotlight Effect", demo.PSYCHOLOGY, "concept",
               "Psychology Explainer")


def engine_b(area) -> None:
    from synergia.engines import listicle
    _seed_flow(area, "B", listicle, "Hook", "5 things people regret not doing after 25", demo.LISTICLE,
               "cover_title", "Slideshow")


# ---------------------------------------------------------------- D

def engine_d(area) -> None:
    def start() -> None:
        with section(area):
            _heading("Engine D · Brain Test",
                     "3-4 random mini-game rounds, each harder than the last. No Claude needed.")

            async def go() -> None:
                from synergia.engines import brain
                out = await busy("Generating rounds and rendering the video…", brain.produce, debug=S.debug)
                if out:
                    with section(area):
                        run_preview(out, on_new=start)
            ui.button("Generate a Brain Test", icon="psychology", on_click=go)
    start()


# ---------------------------------------------------------------- E

def engine_e(area) -> None:
    from synergia.engines import identity

    def start() -> None:
        with section(area):
            _heading("Engine E · Which One Are You")
            mode = ui.toggle({"checklist": "How many apply to you?", "pick": "Pick one → reveal"},
                             value="checklist")
            topic = ui.input("Topic").classes("w-full max-w-xl").props("outlined")
            suggestions = ui.column().classes("w-full")

            def update_hint() -> None:
                topic.props["placeholder"] = ("signs you're a high-functioning overthinker"
                                              if mode.value == "checklist"
                                              else "pick a door to reveal your hidden strength")
                topic.update()
            mode.on_value_change(update_hint)
            update_hint()

            def go(text: str | None = None) -> None:
                m = mode.value
                eng = identity.Pick if m == "pick" else identity.Checklist
                produce = identity.produce_pick if m == "pick" else identity.produce_checklist
                demo_data = (demo.PICK if m == "pick" else demo.CHECKLIST) if S.is_demo else None
                t = strip_markup(demo_data["cover_title"]) if demo_data else (text or topic.value).strip()
                if not t:
                    ui.notify("Type a topic, or press Suggest 10.", type="warning")
                    return
                script_flow(area, eng, t, demo_data, f"Which One Are You: {t}", produce, start,
                            before_render=lambda d: d.__setitem__("topic", t))

            def suggest() -> None:
                from synergia import history
                from synergia.llm.prompts import topics_prompt

                def check(d: dict) -> list[str]:
                    t = d.get("topics")
                    if not isinstance(t, list) or len([x for x in t if str(x).strip()]) < 5:
                        return ['"topics" must be a list of about 10 short strings']
                    d["topics"] = [str(x).strip() for x in t if str(x).strip()][:10]
                    return []

                def show(d: dict) -> None:
                    suggestions.clear()
                    with suggestions:
                        ui.label("Pick a topic").classes("font-semibold")
                        for t in d["topics"]:
                            ui.button(t, on_click=lambda _, t=t: go(t)) \
                                .props("outline no-caps align=left").classes("w-full max-w-xl")

                suggestions.clear()
                with suggestions:
                    claude_step(topics_prompt(mode.value, history.recent("identity.topics")), check,
                                "Topic ideas", on_done=show, on_cancel=suggestions.clear)

            topic.on("keydown.enter", lambda: go())
            with ui.row().classes("gap-2"):
                ui.button("Write the script", icon="auto_awesome", on_click=lambda: go())
                if not S.is_demo:
                    ui.button("Suggest 10", icon="lightbulb", on_click=suggest).props("outline")
            if S.is_demo:
                ui.label("Demo mode: uses the built-in sample script for the chosen format.") \
                    .classes("text-sm opacity-60")
    start()


# ---------------------------------------------------------------- C

def engine_c(area) -> None:
    def start() -> None:
        with section(area):
            _heading("Engine C · Podcast Clipper",
                     "A 9:16 clip under 1 minute, speaker centred, word-highlighted subtitles.")
            src_in = ui.input("YouTube URL or local .mp4 path").classes("w-full max-w-2xl") \
                .props("outlined autofocus")

            async def load() -> None:
                from synergia.engines.podcast import engine
                inp = src_in.value.strip().strip('"')
                if not inp:
                    ui.notify("Paste a URL or a file path first.", type="warning")
                    return
                res = await busy("Fetching the video…", engine.load_source, inp)
                if res:
                    choose(*res)
            src_in.on("keydown.enter", load)
            ui.button("Load", icon="download", on_click=load)

    def choose(src, name, credit, info) -> None:
        from synergia.engines.podcast import engine
        from synergia.engines.podcast import highlights as hl

        with section(area):
            _heading(name, f"{info['width']}x{info['height']} @ {info['fps']:.2f}fps · "
                           f"{hl.fmt_ts(info['duration'])}")
            if credit:
                ui.label(f"Caption credit: {engine.credit_text(credit).splitlines()[0]}") \
                    .classes("text-sm opacity-70")
                who = None
            else:
                who = ui.input("Credit (show / channel to credit in the caption, optional)") \
                    .classes("w-full max-w-xl").props("outlined")

            def credit_str() -> str:
                c = credit or ({"channel": who.value.strip()} if who and who.value.strip() else {})
                return engine.credit_text(c)

            with ui.row().classes("w-full gap-6 items-start"):
                with ui.card().classes("gap-2"):
                    ui.label("I know the part I want").classes("font-semibold")
                    rng = ui.input("Clip range", placeholder="12:30-13:15").props("outlined")

                    async def by_range() -> None:
                        try:
                            hl.parse_range(rng.value)
                        except ValueError as e:
                            ui.notify(str(e), type="warning")
                            return
                        res = await busy("Transcribing that part…", engine.range_clip, src, info, rng.value)
                        if res:
                            tr, cand = res
                            finish(src, info, name, [cand], tr, credit_str())
                    ui.button("Use this range", on_click=by_range)
                with ui.card().classes("gap-2"):
                    ui.label("Find the best moments").classes("font-semibold")
                    ui.label("Transcribes the whole episode, then Claude suggests 5 clips.") \
                        .classes("text-sm opacity-60")

                    async def find() -> None:
                        tr = await busy("Transcribing the whole episode (cached next time)…",
                                        engine.full_transcript, src, info)
                        if tr:
                            highlights(src, info, name, tr, credit_str())
                    ui.button("Find highlights", icon="travel_explore", on_click=find)
            ui.button("Back", on_click=start).props("flat color=grey")

    def highlights(src, info, name, tr, credit: str) -> None:
        from synergia.engines.podcast import engine
        from synergia.engines.podcast import highlights as hl

        def show(data: dict | None) -> None:
            cands, label = engine.candidates(tr, data)
            pick_table(src, info, name, tr, cands, label, credit)

        with section(area):
            claude_step(hl.claude_prompt(tr, name), hl.make_validator(info["duration"]),
                        "Find highlights with Claude", on_done=show, on_cancel=start,
                        on_skip=lambda: show(None), skip_label="Skip (offline heuristic)")

    def pick_table(src, info, name, tr, cands, label: str, credit: str) -> None:
        from synergia.engines.podcast import engine
        from synergia.engines.podcast import highlights as hl

        with section(area):
            _heading(f"Highlight candidates ({label})", "Tick one or more, or type a custom range.")
            rows = [{"id": i, "range": f"{hl.fmt_ts(c.start)}–{hl.fmt_ts(c.end)}",
                     "len": f"{c.duration:.0f}s", "title": c.title, "why": c.why}
                    for i, c in enumerate(cands, 1)]
            cols = [{"name": "id", "label": "#", "field": "id"},
                    {"name": "range", "label": "Range", "field": "range"},
                    {"name": "len", "label": "Len", "field": "len"},
                    {"name": "title", "label": "Title / opening", "field": "title", "align": "left",
                     "style": "white-space: normal"},
                    {"name": "why", "label": "Why", "field": "why", "align": "left",
                     "style": "white-space: normal; opacity: .6"}]
            table = ui.table(rows=rows, columns=cols, selection="multiple").classes("w-full")
            custom = ui.input("…or a custom range", placeholder="mm:ss-mm:ss").props("outlined")

            def go() -> None:
                choice = custom.value.strip() or ",".join(str(r["id"]) for r in table.selected)
                if not choice:
                    ui.notify("Tick at least one clip.", type="warning")
                    return
                try:
                    picked = engine.pick(choice, cands, tr["words"])
                except ValueError as e:
                    ui.notify(str(e), type="warning")
                    return
                finish(src, info, name, picked, tr, credit)
            with ui.row().classes("gap-2"):
                ui.button("Continue", icon="arrow_forward", on_click=go)
                ui.button("Start over", on_click=start).props("flat color=grey")

    def finish(src, info, name, picked, tr, credit: str) -> None:
        from synergia.engines.podcast import engine
        from synergia.engines.podcast import highlights as hl

        with section(area):
            if len(picked) == 1:
                c = picked[0]
                _heading("Clip", f"{hl.fmt_ts(c.start)}–{hl.fmt_ts(c.end)} ({c.duration:.1f}s; "
                                 f"trimmed at a sentence end if over {hl.hard_max():.0f}s)")
                title = ui.input("On-screen title (empty = none)", value=engine.suggested_title(c)) \
                    .classes("w-full max-w-xl").props("outlined")
            else:
                title = None
                _heading(f"{len(picked)} clips", "Each uses its suggested title.")
                for c in picked:
                    ui.label(f"{hl.fmt_ts(c.start)}–{hl.fmt_ts(c.end)}  {engine.suggested_title(c)}") \
                        .classes("text-sm")

            async def render() -> None:
                out = await busy(f"Rendering {len(picked)} clip{'s' if len(picked) > 1 else ''}…",
                                 engine.render_picked, src, info, name, picked, tr["words"],
                                 title.value.strip() if title else None, S.debug, credit)
                if not out:
                    return
                with section(area):
                    if len(picked) > 1:   # out is the engine folder; show the newest clips
                        runs = sorted((d for d in out.iterdir() if d.is_dir()), key=lambda d: d.name,
                                      reverse=True)[:len(picked)]
                        for d in runs:
                            run_preview(d)
                        ui.button("Make another", icon="add", on_click=start).props("flat")
                    else:
                        run_preview(out, on_new=start)
            with ui.row().classes("gap-2"):
                ui.button("Render", icon="play_arrow", on_click=render)
                ui.button("Start over", on_click=start).props("flat color=grey")
    start()


FLOWS = {"A": engine_a, "B": engine_b, "C": engine_c, "D": engine_d, "E": engine_e}


def page(engine: str = "A") -> None:
    engine = engine.upper() if engine.upper() in FLOWS else "A"
    with ui.tabs(value=engine).classes("w-full") as tabs:
        for letter, name in ENGINES:
            ui.tab(letter, label=f"{letter} · {name}").props("no-caps")
    with ui.tab_panels(tabs, value=engine).classes("w-full bg-transparent"):
        for letter, _ in ENGINES:
            with ui.tab_panel(letter):
                FLOWS[letter](ui.column().classes("w-full gap-4"))
