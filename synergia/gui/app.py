"""Synergia GUI: a local web app (NiceGUI) that runs the same engines as the console."""
from __future__ import annotations

import os

from nicegui import app, ui

from synergia.config import CFG
from synergia.gui import autopilot, create, library, upload
from synergia.gui.components import MEDIA, S
from synergia.video import have_ffmpeg

PORT = 8765
NAV = [("Create", "/", "auto_awesome"), ("Autopilot", "/autopilot", "rocket_launch"),
       ("Library", "/library", "video_library"), ("Upload", "/upload", "cloud_upload")]
FONT_CSS = ""     # set in start()
FFMPEG = True     # set in start()


def _fonts() -> str:
    fonts = CFG.root / "assets" / "fonts"
    if not (fonts / "Inter-Medium.ttf").is_file():
        return ""
    app.add_static_files("/fonts", fonts)
    faces = "".join(f"@font-face{{font-family:Inter;font-weight:{w};src:url('/fonts/Inter-{n}.ttf')}}"
                    for n, w in (("Medium", 400), ("SemiBold", 600), ("Bold", 700), ("Black", 900)))
    return faces + "body{font-family:Inter,system-ui,sans-serif}"


def _frame(active: str) -> None:
    """Theme + header shared by every page."""
    b = CFG.brand
    ui.colors(primary=b.accent, secondary=b.accent2, dark_page=b.background, dark="#12142B")
    ui.add_css(f"body{{background:{b.background};color:{b.text}}}" + FONT_CSS)
    with ui.header().classes("items-center gap-6 px-6 py-3 bg-[#0D0F24] border-b border-[#1E2246]"):
        ui.label("S Y N E R G I A").classes("text-lg font-bold tracking-widest text-primary")
        with ui.row().classes("gap-1"):
            for label, path, icon in NAV:
                ui.button(label, icon=icon, on_click=lambda p=path: ui.navigate.to(p)) \
                    .props(f"flat no-caps {'color=primary' if label == active else 'color=grey-5'}")
        ui.space()
        if S.is_demo:
            ui.badge("demo", color="secondary")
        if S.debug:
            ui.badge("debug", color="warning")


def _no_ffmpeg() -> None:
    ui.label("ffmpeg/ffprobe not found on PATH. Install ffmpeg and restart Synergia.") \
        .classes("text-negative text-lg p-8")


def _register_pages() -> None:
    """Called from start(), so a fresh NiceGUI app (e.g. in tests) gets the pages too."""
    @ui.page("/")
    def _create(engine: str = "A") -> None:
        _frame("Create")
        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
            _no_ffmpeg() if not FFMPEG else create.page(engine)

    @ui.page("/autopilot")
    def _autopilot() -> None:
        _frame("Autopilot")
        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            _no_ffmpeg() if not FFMPEG else autopilot.page()

    @ui.page("/library")
    def _library() -> None:
        _frame("Library")
        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            library.page()

    @ui.page("/run")
    def _run(path: str = "") -> None:
        _frame("Library")
        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
            library.run_page(path)

    @ui.page("/upload")
    def _upload(run: str = "") -> None:
        _frame("Upload")
        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            upload.page(run)


def start(is_demo: bool = False, debug: bool = False, port: int = PORT) -> None:
    global FONT_CSS, FFMPEG
    S.is_demo, S.debug = is_demo, debug
    FFMPEG = have_ffmpeg()
    CFG.output.dir.mkdir(parents=True, exist_ok=True)
    app.add_media_files(MEDIA, CFG.output.dir)
    FONT_CSS = _fonts()
    _register_pages()
    print(f"Synergia GUI on http://localhost:{port}  (Ctrl+C here to stop)")
    ui.run(title="Synergia", dark=True, reload=False, port=port,
           show=not os.environ.get("SYNERGIA_NO_OPEN"), show_welcome_message=False)
