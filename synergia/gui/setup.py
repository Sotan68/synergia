"""Setup wizard (first launch / new profile) and Settings page: brand, niche, review, theme, engines.

Saving writes the profile (a new one under profiles/<name>/, or the active one for Settings) and
restarts the app, because the slide modules read their colours and fonts once at import time.
"""
from __future__ import annotations

import asyncio
import io
import shutil
import uuid

from nicegui import run, ui
from PIL import Image

from synergia import profile
from synergia.brand import themes
from synergia.config import CFG, PROFILES, ROOT
from pathlib import Path
from synergia.gui.components import claude_step
from synergia.output import ALL_ENGINES, ENGINE_NAMES

ENGINE_BLURBS = {
    "A": "10-second explainer of one concept (hook + 3 slides)",
    "B": "Carousel / slideshow: a hook and 5 points",
    "C": "Clips from long podcast episodes, with subtitles",
    "D": "Brain test mini-games (no writing needed)",
    "E": "\"How many apply to you?\" checklists and \"Pick one\" reveals",
}


def _lines(text: str) -> list[str]:
    return [x.strip() for x in text.replace(",", "\n").splitlines() if x.strip()]


def _tags(text: str) -> list[str]:
    return ["#" + t.lstrip("#") for t in text.replace(",", " ").split() if t.strip("#")]


def page(editing: bool = False) -> None:
    prof = profile.load() if editing else {}
    st = {
        "name": CFG.brand.name if editing else "",
        "audience": getattr(CFG.voice, "audience", "") if editing else "",
        "description": "",
        # the logo file: an absolute path while editing, so it can come from anywhere
        "logo": str(CFG.brand.logo) if editing and CFG.brand.logo else "",
        "draft": profile.draft_from_config(CFG) if editing else None,
        "theme": getattr(CFG.theme, "preset", themes.DEFAULT) if editing else themes.DEFAULT,
        "engines": list(CFG.engines.enabled) if editing else list(ALL_ENGINES),
    }

    first = not CFG.configured
    ui.label("Settings" if editing else "Set up your Synergia" if first else "New profile") \
        .classes("text-2xl font-semibold")
    ui.label("Your brand, your niche and your look. Everything Synergia makes follows these."
             if editing else
             "A few questions and your content engine is ready. You can change all of this later "
             "in Settings.").classes("opacity-70 -mt-2")

    # header-nav: click any step's title to jump to it
    with ui.stepper().props("vertical animated header-nav").classes("w-full bg-transparent") as stepper:
        # ------------------------------------------------------------ 1. brand
        with ui.step("Brand", icon="badge"):
            name = ui.input("Brand name", value=st["name"],
                            placeholder="e.g. FitDad Daily").props("outlined").classes("w-96")
            ui.label("Shown in every slide footer, next to your logo.").classes("text-xs opacity-60")
            logo_img = ui.image().classes("w-24 h-24 object-contain bg-grey-2 rounded")
            logo_img.set_visibility(bool(st["logo"]))
            if st["logo"]:
                logo_img.set_source(st["logo"])

            async def on_upload(e) -> None:
                data = await e.file.read()
                try:
                    im = Image.open(io.BytesIO(data)).convert("RGBA")
                except Exception:  # noqa: BLE001
                    ui.notify("That file isn't an image Synergia can read.", type="negative")
                    return
                up = CFG.output.shared_cache / "uploads"
                up.mkdir(parents=True, exist_ok=True)
                path = up / f"logo-{uuid.uuid4().hex[:8]}.png"
                im.save(path)
                st["logo"] = str(path)
                logo_img.set_source(str(path))
                logo_img.set_visibility(True)
                ui.notify("Logo saved", type="positive")

            ui.upload(label="Logo (optional, PNG with a transparent background works best)",
                      on_upload=on_upload, auto_upload=True, max_files=1) \
                .props('accept=".png,.jpg,.jpeg,.webp" flat bordered color="grey-2" text-color="grey-9"')                 .classes("w-96")

            def clear_logo() -> None:
                st["logo"] = ""
                logo_img.set_visibility(False)
            ui.button("Use the drawn mark instead", on_click=clear_logo).props("flat dense no-caps")

            def next1() -> None:
                if not name.value.strip():
                    ui.notify("Give your brand a name first.", type="warning")
                    return
                st["name"] = name.value.strip()
                stepper.next()
            with ui.stepper_navigation():
                ui.button("Next", on_click=next1)

        # ------------------------------------------------------------ 2. niche
        with ui.step("Your niche", icon="travel_explore"):
            ui.label("Describe what you want to post about, like you'd tell a friend. Claude "
                     "autocompletes the voice, topics, hashtags and Engine A wording from it; you "
                     "review everything next.").classes("text-sm opacity-70")
            desc = ui.textarea("What is your channel about?",
                               placeholder="e.g. Quick home workouts and food tips for busy dads "
                                           "who want to get fit without a gym") \
                .props("outlined autogrow").classes("w-full max-w-2xl")
            aud = ui.input("Who is it for? (optional)", value=st["audience"],
                           placeholder="e.g. dads in their 30s and 40s") \
                .props("outlined").classes("w-full max-w-2xl")
            draft_box = ui.column().classes("w-full")

            async def got_draft(data: dict) -> None:
                st["draft"] = data
                st["engines"] = list(data.get("engines") or st["engines"])
                draft_box.clear()
                build_review()
                stepper.next()
                prefetch()

            def ask() -> None:
                if not desc.value.strip():
                    ui.notify("Describe your niche first.", type="warning")
                    return
                st["description"], st["audience"] = desc.value.strip(), aud.value.strip()
                draft_box.clear()
                with draft_box:
                    claude_step(profile.draft_prompt(st["name"] or name.value, st["description"],
                                                     st["audience"]),
                                profile.validate_draft, "Autocomplete your brand", on_done=got_draft,
                                on_cancel=draft_box.clear)

            def skip() -> None:
                st["audience"] = aud.value.strip()
                if st["draft"] is None:
                    st["draft"] = profile.draft_from_config(CFG)
                build_review()
                stepper.next()
                prefetch()

            with ui.stepper_navigation():
                ui.button("Autocomplete with Claude", icon="auto_awesome", on_click=ask)
                ui.button("Keep current" if editing else "Fill it in myself", on_click=skip) \
                    .props("flat")

        # ------------------------------------------------------------ 3. review
        with ui.step("Review the writing", icon="edit_note"):
            review_box = ui.column().classes("w-full max-w-3xl gap-2")
            fields: dict[str, ui.element] = {}

            def build_review() -> None:
                d = st["draft"]
                review_box.clear()
                fields.clear()
                if d is None:
                    with review_box:
                        ui.label("Fill in 'Your niche' first (or choose to fill it in yourself).") \
                            .classes("text-sm opacity-70")
                    return
                ea, ex, tags = d["engine_a"], d["examples"], d["hashtags"]
                with review_box:
                    def inp(key: str, label: str, value: str, hint: str = "", area: bool = False):
                        el = (ui.textarea if area else ui.input)(label, value=value) \
                            .props("outlined dense" + (" autogrow" if area else "")).classes("w-full")
                        if hint:
                            el.props(f'hint="{hint}"')
                        fields[key] = el

                    ui.label("Voice").classes("text-lg font-semibold mt-2")
                    inp("niche", "Niche", d["niche"], 'Ends the sentence "a short-form brand about …"')
                    inp("tone", "Tone of voice", d["tone"])
                    inp("topic_scope", "Subjects you cover (comma separated)", ", ".join(d["topic_scope"]))
                    inp("niche_short", "Niche in 3-5 words (podcast clip finder)", d["niche_short"])
                    inp("clip_payoff", "What a great podcast clip delivers", d["clip_payoff"])

                    ui.label("Engine A: explainer").classes("text-lg font-semibold mt-4")
                    inp("concept_kind", "What Engine A explains", d["concept_kind"])
                    inp("concept_examples", "Example concepts (one per line)",
                        "\n".join(d["concept_examples"]), area=True)
                    inp("a_kind", "One word for the niche", ea["kind"],
                        '"Write a 10-second <word> explainer"')
                    with ui.row().classes("w-full gap-2 no-wrap"):
                        for i in range(3):
                            fields[f"label{i}"] = ui.input(f"Slide {i + 2} label",
                                                           value=ea["step_labels"][i]) \
                                .props("outlined dense").classes("flex-1")
                    inp("gotcha", "What slide 2 does", ea["gotcha"])
                    inp("mechanism", "What slide 3 does", ea["mechanism"])
                    inp("shift", "What slide 4 does", ea["shift"])

                    ui.label("Engine B: carousels").classes("text-lg font-semibold mt-4")
                    inp("carousel_kind", "Kind of carousel", d["carousel_kind"],
                        '"hooks for 5-point <kind> carousels"')
                    inp("hook_examples", "Example hooks (one per line)",
                        "\n".join(d["hook_examples"]), area=True)

                    ui.label("Engine E: which one are you").classes("text-lg font-semibold mt-4")
                    inp("checklist_cover", "Checklist title example", ex["checklist_cover"])
                    inp("pick_cover", "Pick-one title example", ex["pick_cover"])
                    inp("checklist_topic", "Checklist topic example", ex["checklist_topic"])
                    inp("pick_topic", "Pick-one topic example", ex["pick_topic"])

                    ui.label("Hashtags (first one is always suggested)").classes("text-lg font-semibold mt-4")
                    for k, label in (("A", "Engine A"), ("B", "Engine B"), ("C", "Engine C"),
                                     ("E_checklist", "Engine E checklists"), ("E_pick", "Engine E pick one")):
                        inp(f"tags_{k}", label, " ".join(tags[k]))
                    inp("keywords", "Podcast keywords for the offline clip finder (comma separated)",
                        ", ".join(d["keywords"]), area=True)

            def collect() -> bool:
                if not fields:
                    ui.notify("Fill in 'Your niche' first.", type="warning")
                    return False
                f = {k: (v.value or "").strip() for k, v in fields.items()}
                d = {
                    "niche": f["niche"], "niche_short": f["niche_short"],
                    "clip_payoff": f["clip_payoff"], "tone": f["tone"],
                    "topic_scope": _lines(f["topic_scope"]), "concept_kind": f["concept_kind"],
                    "concept_examples": _lines(f["concept_examples"].replace(",", "\n")),
                    "carousel_kind": f["carousel_kind"], "hook_examples": [
                        x.strip() for x in f["hook_examples"].splitlines() if x.strip()],
                    "examples": {k: f[k] for k in ("checklist_cover", "pick_cover",
                                                   "checklist_topic", "pick_topic")},
                    "engine_a": {"kind": f["a_kind"], "step_labels": [f[f"label{i}"] for i in range(3)],
                                 "gotcha": f["gotcha"], "mechanism": f["mechanism"], "shift": f["shift"]},
                    "hashtags": {k: _tags(f[f"tags_{k}"]) for k in ("A", "B", "C", "E_checklist", "E_pick")},
                    "keywords": _lines(f["keywords"]),
                    "engines": st["engines"],
                }
                errors = profile.validate_draft(d)
                if errors:
                    ui.notify("Fix these first: " + "; ".join(errors[:4]), type="warning",
                              multi_line=True, timeout=8000)
                    return False
                st["draft"] = d
                return True

            if st["draft"] is not None:
                build_review()

            async def next3() -> None:
                if collect():
                    stepper.next()
                    prefetch()
            with ui.stepper_navigation():
                ui.button("Next", on_click=next3)

        # ------------------------------------------------------------ 4. theme
        with ui.step("Theme", icon="palette"):
            ui.label("Pick the look of your slides. Each preview uses your brand name.") \
                .classes("text-sm opacity-70")
            grid = ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full")
            cards: dict[str, ui.card] = {}
            images: dict[str, ui.image] = {}

            def select(key: str) -> None:
                st["theme"] = key
                for k, c in cards.items():
                    c.classes(replace="cursor-pointer border-2 " +
                              ("border-primary" if k == key else "border-transparent"))

            with grid:
                for key, t in themes.THEMES.items():
                    with ui.card().on("click", lambda k=key: select(k)) as card:
                        images[key] = ui.image().classes("w-full rounded")
                        with ui.row().classes("items-center gap-2"):
                            for col in (t["paper"]["accent"], t["paper"]["accent2"], t["paper"]["ink"]):
                                ui.element("div").classes("w-4 h-4 rounded-full") \
                                    .style(f"background:{col}")
                            ui.label(t["label"]).classes("font-semibold")
                        ui.label(t["blurb"]).classes("text-xs opacity-60")
                    cards[key] = card
            select(st["theme"])

            async def load_previews() -> None:
                """All six previews render at the same time (each in its own process); a card
                shows its preview as soon as it's ready. Skipped if nothing changed."""
                from synergia import theme_preview

                concept = ((st["draft"] or {}).get("concept_examples") or ["Your concept"])[0]
                hook = f"Why **{concept.split()[-1].lower()}** matters more than you think"
                key_now = (st["name"], st["logo"], concept)
                if st.get("previews_for") == key_now:
                    return
                st["previews_for"] = key_now

                async def one(key: str) -> None:
                    prof_min = {"brand": {"name": st["name"] or "My Brand",
                                          **({"logo": st["logo"]} if st["logo"] else {})},
                                "theme": {"preset": key}}
                    try:
                        path = await run.io_bound(theme_preview.make, CFG.output.shared_cache, ROOT,
                                                  prof_min, concept, hook)
                    except Exception as e:  # noqa: BLE001
                        ui.notify(f"Preview for {key} failed: {e}", type="warning")
                        return
                    images[key].set_source(str(path))

                await asyncio.gather(*(one(k) for k in themes.THEMES))

            def prefetch() -> None:
                ui.timer(0.1, load_previews, once=True)

            # also when someone jumps to the Theme step by clicking its title
            stepper.on_value_change(lambda e: prefetch() if e.value == "Theme" else None)

            with ui.stepper_navigation():
                ui.button("Next", on_click=stepper.next)

        # ------------------------------------------------------------ 5. engines + save
        with ui.step("Engines", icon="tune"):
            ui.label("Which formats do you want? You can turn them back on later.") \
                .classes("text-sm opacity-70")
            boxes = {}
            for k in ALL_ENGINES:
                boxes[k] = ui.checkbox(f"{k} · {ENGINE_NAMES[k]}: {ENGINE_BLURBS[k]}",
                                       value=k in st["engines"])
            ui.label("YouTube: connect your channel any time on the Upload page.") \
                .classes("text-sm opacity-60 mt-2")

            async def save() -> None:
                st["name"] = name.value.strip() or st["name"]
                if not st["name"]:
                    ui.notify("Give your brand a name first.", type="warning")
                    stepper.set_value("Brand")
                    return
                if st["draft"] is None or not collect():
                    stepper.set_value("Review the writing" if st["draft"] else "Your niche")
                    return
                engines = [k for k in ALL_ENGINES if boxes[k].value]
                if not engines:
                    ui.notify("Pick at least one engine.", type="warning")
                    return
                names = (prof.get("engines") or {}).get("names") if editing else None
                new = profile.from_draft(st["name"], st["draft"], st["theme"], engines,
                                         st["audience"], "logo.png" if st["logo"] else "", names)
                if editing:
                    old_niche = (prof.get("voice") or {}).get("niche")
                    merged = {k: v for k, v in prof.items()}
                    if old_niche != new["voice"]["niche"]:
                        (merged.get("engine_a") or {}).pop("example", None)   # belonged to the old niche
                    if not st["logo"]:
                        (merged.get("brand") or {}).pop("logo", None)
                    from synergia.config import merge
                    new = merge(merged, new)
                    home = CFG.profile_file.parent
                    profile.save(new)
                else:
                    home = PROFILES / profile.create(new)
                if st["logo"]:          # the profile keeps its own copy of the logo
                    src = Path(st["logo"])
                    if src.resolve() != (home / "logo.png").resolve():
                        shutil.copyfile(src, home / "logo.png")
                restart_app()

            with ui.stepper_navigation():
                ui.button("Save and restart" if editing else "Finish setup", icon="check", on_click=save)

    if st["draft"] is not None:      # Settings: the writing exists, so the previews can start now
        prefetch()


def restart_app() -> None:
    """Start a fresh copy of the app (same arguments) and stop this one; the page reloads itself."""
    import os
    import subprocess
    import sys

    from nicegui import app

    ui.notify("Saved. Restarting Synergia with your settings…", type="positive", timeout=0)
    ui.run_javascript("""
        setTimeout(function poll() {
            fetch('/', {cache: 'no-store'}).then(r => { if (r.ok) location.href = '/'; else setTimeout(poll, 700); })
                                           .catch(() => setTimeout(poll, 700));
        }, 2500);""")
    env = {k: v for k, v in os.environ.items() if k != "SYNERGIA_PROFILE_NAME"}
    env.update(SYNERGIA_NO_OPEN="1", SYNERGIA_WAIT_PORT="1")
    argv = list(sys.argv)
    if "--profile" in argv:            # the new copy opens the active profile, not a pinned one
        i = argv.index("--profile")
        del argv[i:i + 2]
    subprocess.Popen([sys.executable, *argv], cwd=ROOT, env=env)
    ui.timer(0.8, app.shutdown, once=True)
