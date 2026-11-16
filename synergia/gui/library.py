"""Library page: every past run, newest first, with a thumbnail and its upload status."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from synergia.config import CFG
from synergia.gui.components import status_badge, media_url, rel, run_folder, run_preview
from synergia.publish import find_video

LIMIT = 60


def all_runs() -> list[Path]:
    root = CFG.output.dir
    runs = [d for d in root.glob("*/*") if d.is_dir() and any(d.iterdir())] if root.is_dir() else []
    return sorted(runs, key=lambda d: d.name, reverse=True)


def _thumb(d: Path) -> None:
    png = next(iter(sorted(d.glob("*.png"))), None)
    if png:
        ui.image(media_url(png)).classes("w-full aspect-[9/16] rounded")
        return
    video = find_video(d)
    if video:   # first frame as a poster
        ui.html(f'<video src="{media_url(video)}#t=1" preload="metadata" muted '
                f'style="width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:6px"></video>')
    else:
        ui.icon("image_not_supported", size="xl").classes("opacity-30")


def page() -> None:
    runs = all_runs()
    if not runs:
        ui.label("Nothing rendered yet. Make something on the Create page.").classes("opacity-60")
        return
    engines = ["All"] + sorted({d.parent.name for d in runs})
    ui.label("Library").classes("text-xl font-semibold")
    flt = ui.toggle(engines, value="All").props("no-caps")

    @ui.refreshable
    def grid() -> None:
        shown = [d for d in runs if flt.value == "All" or d.parent.name == flt.value][:LIMIT]
        with ui.grid().classes("w-full gap-4 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6"):
            for d in shown:
                with ui.card().tight().classes("cursor-pointer hover:scale-[1.02] transition") \
                        .on("click", lambda _, d=d: ui.navigate.to(f"/run?path={quote(rel(d))}")):
                    _thumb(d)
                    with ui.card_section().classes("gap-1 p-2"):
                        ui.label(d.name.split("_", 2)[-1].replace("-", " ")) \
                            .classes("text-sm font-medium leading-tight line-clamp-2")
                        ui.label(f"{d.parent.name[:1]} · {d.name[:10]}").classes("text-xs opacity-50")
                        status_badge(d)
    flt.on_value_change(grid.refresh)
    grid()


def run_page(path: str = "") -> None:
    folder = run_folder(path)
    if folder is None:
        ui.label("That run folder doesn't exist.").classes("opacity-60")
        return
    ui.button("Library", icon="arrow_back", on_click=lambda: ui.navigate.to("/library")).props("flat")
    run_preview(folder)
