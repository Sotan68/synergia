"""Building blocks shared by the GUI pages: Claude round trip, script editor, run preview, busy jobs."""
from __future__ import annotations

import inspect
import os
import time
import traceback
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import pyperclip
from nicegui import run, ui

from synergia.config import CFG
from synergia.llm.bridge import Validator, get_path, parse_reply, set_path
from synergia.llm.prompts import fix_prompt

MEDIA = "/media"   # CFG.output.dir is served here (see app.py)


class Settings:
    is_demo = False
    debug = False
    busy = False   # one render / transcription / upload at a time, across browser tabs


S = Settings()


async def call(fn: Callable | None, *args) -> None:
    """Run a callback that may or may not be async."""
    if fn is None:
        return
    res = fn(*args)
    if inspect.isawaitable(res):
        await res


# ---------------------------------------------------------------- paths / media

def rel(folder: Path) -> str:
    return Path(folder).resolve().relative_to(CFG.output.dir.resolve()).as_posix()


def media_url(path: Path) -> str:
    return f"{MEDIA}/{quote(rel(path))}"


def run_folder(rel_path: str) -> Path | None:
    """output-relative path from a URL -> folder, only if it really is inside output/."""
    root = CFG.output.dir.resolve()
    p = (root / rel_path).resolve()
    return p if p.is_dir() and p.is_relative_to(root) and p != root else None


def engine_label(folder: Path) -> str:
    return folder.parent.name   # "A - Psychology Explainer"


# ---------------------------------------------------------------- slow work

async def busy(label: str, fn: Callable, *args, **kwargs) -> Any:
    """Run fn in a worker thread behind a modal spinner. Returns its result, or None on failure."""
    if S.busy:
        ui.notify("Something is already running. Wait for it to finish.", type="warning")
        return None
    S.busy = True
    started = time.monotonic()
    with ui.dialog().props("persistent") as dlg, ui.card().classes("items-center gap-3 p-8"):
        ui.spinner(size="3em")
        ui.label(label).classes("text-lg")
        elapsed = ui.label("0s").classes("text-sm opacity-60")
        ui.label("Details are printed in the console window.").classes("text-xs opacity-40")
        ui.timer(1, lambda: elapsed.set_text(f"{time.monotonic() - started:.0f}s"))
    dlg.open()
    try:
        return await run.io_bound(fn, *args, **kwargs)
    except Exception as e:  # noqa: BLE001 — show it, keep the app alive
        ui.notify(f"{label.rstrip('…')} failed: {e}", type="negative", multi_line=True, close_button=True,
                  timeout=0)
        if S.debug:
            traceback.print_exc()
        return None
    finally:
        S.busy = False
        dlg.close()
        dlg.delete()


# ---------------------------------------------------------------- Claude round trip

def _copy(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException:
        return False


def claude_step(prompt: str, validator: Validator, title: str,
                on_done: Callable[[dict], Any], on_cancel: Callable | None = None,
                on_skip: Callable | None = None, skip_label: str = "Skip") -> None:
    """GUI version of bridge.ask_claude: copy the prompt, paste Claude's reply, validate, fix if needed."""
    CFG.output.cache_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = CFG.output.cache_dir / "last_prompt.txt"
    state = {"current": prompt}

    def put(text: str) -> None:
        state["current"] = text
        prompt_file.write_text(text, encoding="utf-8")
        if _copy(text):
            ui.notify("Prompt copied to your clipboard", type="positive")
        else:
            ui.notify(f"Clipboard unavailable. Copy it from {prompt_file}", type="warning")
        prompt_view.set_content(f"```\n{text}\n```")

    with ui.card().classes("w-full gap-3"):
        ui.label(f"✦ {title}").classes("text-lg font-semibold text-secondary")
        with ui.column().classes("gap-1 text-sm opacity-80"):
            ui.label("1. The prompt is on your clipboard. Paste it into a Claude chat (claude.ai) and send it.")
            ui.label("2. Copy Claude's whole reply (the copy button under the message).")
            ui.label("3. Press Read clipboard, or paste the reply into the box below and press Check.")
        with ui.expansion("Show prompt", icon="description").classes("w-full"):
            prompt_view = ui.markdown().classes("w-full text-xs max-h-80 overflow-auto")
        reply = ui.textarea("Claude's reply", placeholder="Paste here, or use Read clipboard") \
            .classes("w-full").props("outlined autogrow input-style='max-height: 240px'")
        errors_box = ui.column().classes("w-full")

        async def check(text: str) -> None:
            if not text.strip():
                ui.notify("Nothing to read yet.", type="warning")
                return
            if text.strip() == state["current"].strip():
                ui.notify("The clipboard still holds the prompt. Copy Claude's reply first.", type="warning")
                return
            data, errors = parse_reply(text, validator)
            errors_box.clear()
            if data is not None:
                await call(on_done, data)
                return
            with errors_box, ui.card().classes("w-full bg-red-10 border border-red-8"):
                ui.label("Reply needs a fix").classes("font-semibold text-red-4")
                for e in errors:
                    ui.label(f"• {e}").classes("text-sm")
                ui.label("A correction prompt has been copied. Send it in the same Claude chat, "
                         "then read the new reply.").classes("text-sm opacity-70")
            reply.value = ""
            put(fix_prompt(errors, text))

        async def read_clipboard() -> None:
            try:
                text = pyperclip.paste()
            except pyperclip.PyperclipException:
                ui.notify("Can't read the clipboard. Paste the reply into the box.", type="warning")
                return
            reply.value = text
            await check(text)

        with ui.row().classes("gap-2"):
            ui.button("Read clipboard", icon="content_paste", on_click=read_clipboard)
            ui.button("Check pasted text", icon="check", on_click=lambda: check(reply.value)).props("outline")
            ui.button("Copy prompt again", icon="content_copy",
                      on_click=lambda: put(state["current"])).props("flat")
            if on_skip:
                ui.button(skip_label, icon="skip_next", on_click=on_skip).props("flat")
            if on_cancel:
                ui.button("Cancel", on_click=on_cancel).props("flat color=grey")
    put(prompt)


# ---------------------------------------------------------------- script editor

def script_editor(data: dict, fields: list[tuple[str, str]], on_render: Callable,
                  on_regen: Callable | None, on_cancel: Callable, title: str = "Review script") -> None:
    with ui.card().classes("w-full gap-3"):
        with ui.row().classes("w-full items-baseline justify-between"):
            ui.label(title).classes("text-lg font-semibold text-secondary")
            ui.label("Wrap words in **double asterisks** to highlight them").classes("text-xs opacity-60")
        for label, path in fields:
            ui.textarea(label, value=str(get_path(data, path)),
                        on_change=lambda e, p=path: set_path(data, p, e.value)) \
                .classes("w-full").props("outlined autogrow")
        with ui.row().classes("gap-2"):
            ui.button("Render", icon="play_arrow", on_click=on_render)
            if on_regen:
                ui.button("Regenerate", icon="refresh", on_click=on_regen).props("outline")
            ui.button("Cancel", on_click=on_cancel).props("flat color=grey")


# ---------------------------------------------------------------- run preview

def status_badge(folder: Path) -> None:
    from datetime import datetime

    from synergia.publish import read_ledger
    from synergia.publish import schedule as sch

    yt = read_ledger(folder).get("youtube")
    if not yt:
        return
    at = yt.get("publish_at")
    if at and datetime.fromisoformat(at) > sch.now():
        ui.badge(f"goes live {sch.fmt(datetime.fromisoformat(at))}", color="secondary")
    else:
        ui.badge("✓ on YouTube", color="positive")


def run_preview(folder: Path, on_new: Callable | None = None) -> None:
    """Slides, video, editable caption, and actions for one run folder."""
    from synergia.publish import find_video
    from synergia.publish import youtube

    folder = Path(folder)
    pngs = sorted(p for p in folder.glob("*.png"))
    video = find_video(folder) or next(iter(sorted(folder.glob("*.mp4"))), None)
    cap = folder / "caption.txt"

    with ui.card().classes("w-full gap-4"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.icon("check_circle", color="positive", size="md")
            with ui.column().classes("gap-0"):
                ui.label(folder.name).classes("text-lg font-semibold")
                ui.label(engine_label(folder)).classes("text-xs opacity-60")
            status_badge(folder)
        with ui.row().classes("w-full gap-6 items-start no-wrap max-md:flex-wrap"):
            if video:
                ui.video(media_url(video)).style("width: 320px; max-width: 100%; border-radius: 12px")
            with ui.column().classes("grow gap-3 min-w-0"):
                if pngs:
                    with ui.row().classes("gap-2"):
                        for p in pngs:
                            ui.image(media_url(p)).classes("w-28 rounded cursor-pointer") \
                                .on("click", lambda _, u=media_url(p): ui.navigate.to(u, new_tab=True)) \
                                .tooltip(p.name)
                if cap.is_file():
                    box = ui.textarea("caption.txt (title + description used for uploads)",
                                      value=cap.read_text(encoding="utf-8")) \
                        .classes("w-full").props("outlined autogrow")

                    def save() -> None:
                        cap.write_text(box.value.rstrip() + "\n", encoding="utf-8")
                        ui.notify("caption.txt saved", type="positive")
                    ui.button("Save caption", icon="save", on_click=save).props("outline size=sm")
                with ui.row().classes("gap-2 pt-2"):
                    ui.button("Open folder", icon="folder_open",
                              on_click=lambda: os.startfile(folder)).props("outline")  # type: ignore[attr-defined]
                    if video and youtube.is_configured():
                        ui.button("Upload to YouTube", icon="upload",
                                  on_click=lambda: ui.navigate.to(f"/upload?run={quote(rel(folder))}"))
                    if on_new:
                        ui.button("Make another", icon="add", on_click=on_new).props("flat")


def section(area: ui.element) -> ui.element:
    """Clear an area and return it for `with`. Used to step through a flow."""
    area.clear()
    return area
