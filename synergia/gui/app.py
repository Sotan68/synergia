"""Synergia GUI: a local web app (NiceGUI) that runs the same engines as the console.

A light, plain interface: white surfaces, one accent colour from the active profile's theme, the
profile's logo and name in the header and a menu to switch between profiles.
"""
from __future__ import annotations

import os

from nicegui import app, ui

from synergia.config import CFG, hex_to_rgb, list_profiles, read_profile, set_active, profile_dir
from synergia.gui import autopilot, create, library, setup, upload
from synergia.gui.components import MEDIA, S, is_busy
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


def _ui_accent() -> str:
    """The profile's accent for buttons and links, unless it's too pale to read on white."""
    for c in (CFG.quiz.accent, CFG.paper.accent):
        r, g, b = hex_to_rgb(c)
        if 0.2126 * r + 0.7152 * g + 0.0722 * b < 170:
            return c
    return "#4F46E5"


CSS = """
body{background:#F6F7F9;color:#1D2130}
.app-header{background:#FFFFFF!important;color:#1D2130;border-bottom:1px solid #E7E9EE}
.q-card{border-radius:14px;box-shadow:0 1px 2px rgba(16,24,40,.05);border:1px solid #ECEEF2}
.q-tab{text-transform:none}
.q-btn{text-transform:none;border-radius:10px;font-weight:600;letter-spacing:0}
.q-field--outlined .q-field__control{border-radius:10px}
.nav-btn{border-radius:10px}
.nav-btn.active{background:color-mix(in srgb,var(--q-primary) 10%,white)}
"""


def _profile_name(folder: str) -> str:
    return str((read_profile(profile_dir(folder) / "profile.toml").get("brand") or {}).get("name") or folder)


def _switch(folder: str) -> None:
    if folder == CFG.profile_name:
        return
    if is_busy():
        ui.notify("Something is rendering or uploading. Switch when it's done.", type="warning")
        return
    set_active(folder)
    setup.restart_app()


def _logo_src() -> str | None:
    """The profile's logo as a small PNG for the header (None if the profile has no logo)."""
    from synergia.brand.elements import logo
    path = CFG.output.shared_cache / "ui" / f"logo-{CFG.profile_name}.png"
    try:
        mark = logo(56)
        if mark is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        mark.save(path)
        return str(path)
    except Exception:  # noqa: BLE001 — a header without a logo is fine
        return None


def _frame(active: str) -> None:
    """Theme + header shared by every page."""
    accent = _ui_accent()
    ui.colors(primary=accent, secondary=accent, accent=accent)
    ui.add_css(CSS + FONT_CSS)
    with ui.header(elevated=False).classes("app-header items-center gap-3 px-5 py-2"):
        src = _logo_src() if CFG.configured else None
        if src:
            ui.image(src).classes("w-9 h-7").props("fit=contain no-spinner")
        ui.label(CFG.brand.name if CFG.configured else "Synergia").classes("text-base font-semibold mr-4")
        if CFG.configured:
            for label, path, icon in NAV:
                ui.button(label, icon=icon, on_click=lambda p=path: ui.navigate.to(p)) \
                    .props(f"flat no-caps dense {'color=primary' if label == active else 'color=grey-8'}") \
                    .classes("nav-btn px-3" + (" active" if label == active else ""))
        ui.space()
        if S.is_demo:
            ui.badge("demo", color="grey-7")
        if S.debug:
            ui.badge("debug", color="orange")
        if CFG.configured:
            with ui.button(icon="account_circle").props("flat round color=grey-8"):
                with ui.menu().classes("min-w-56"):
                    ui.label("Profiles").classes("text-xs opacity-50 px-4 pt-2")
                    for folder in list_profiles():
                        current = folder == CFG.profile_name
                        with ui.menu_item(on_click=lambda f=folder: _switch(f)):
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.icon("check" if current else "", size="18px").classes("text-primary w-5")
                                ui.label(_profile_name(folder)).classes("font-semibold" if current else "")
                    ui.menu_item("+  New profile", on_click=lambda: ui.navigate.to("/setup?new=1"))
                    ui.separator()
                    ui.menu_item("Settings", on_click=lambda: ui.navigate.to("/settings"))


def _no_ffmpeg() -> None:
    ui.label("ffmpeg/ffprobe not found on PATH. Install ffmpeg and restart Synergia.") \
        .classes("text-negative text-lg p-8")


def _needs_setup() -> bool:
    """Before profile.toml exists, every page sends you to the setup wizard."""
    if CFG.configured:
        return False
    ui.navigate.to("/setup")
    return True


def _register_pages() -> None:
    """Called from start(), so a fresh NiceGUI app (e.g. in tests) gets the pages too."""
    @ui.page("/setup")
    def _setup(new: str = "") -> None:
        if CFG.configured and not new:
            ui.navigate.to("/settings")
            return
        _frame("Setup")
        with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):
            setup.page(editing=False)

    @ui.page("/settings")
    def _settings() -> None:
        if _needs_setup():
            return
        _frame("Settings")
        with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):
            setup.page(editing=True)

    @ui.page("/")
    def _create(engine: str = "") -> None:
        if _needs_setup():
            return
        _frame("Create")
        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
            _no_ffmpeg() if not FFMPEG else create.page(engine)

    @ui.page("/autopilot")
    def _autopilot() -> None:
        if _needs_setup():
            return
        _frame("Autopilot")
        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            _no_ffmpeg() if not FFMPEG else autopilot.page()

    @ui.page("/library")
    def _library() -> None:
        if _needs_setup():
            return
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
        if _needs_setup():
            return
        _frame("Upload")
        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            upload.page(run)


def _wait_for_port(port: int, timeout: float = 20.0) -> None:
    import socket
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.4)


def start(is_demo: bool = False, debug: bool = False, port: int = PORT) -> None:
    global FONT_CSS, FFMPEG
    S.is_demo, S.debug = is_demo, debug
    FFMPEG = have_ffmpeg()
    CFG.output.dir.mkdir(parents=True, exist_ok=True)
    app.add_media_files(MEDIA, CFG.output.dir)
    FONT_CSS = _fonts()
    _register_pages()
    if os.environ.pop("SYNERGIA_WAIT_PORT", None):
        _wait_for_port(port)          # restarted after Settings: let the old copy let go first
    where = "" if CFG.configured else "  (first launch: set up your brand)"
    print(f"Synergia GUI on http://localhost:{port}{where}  (Ctrl+C here to stop)")
    ui.run(title=CFG.brand.name if CFG.configured else "Synergia setup", dark=False, reload=False, port=port,
           show=not os.environ.get("SYNERGIA_NO_OPEN"), show_welcome_message=False)
