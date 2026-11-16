"""Upload page: pick videos, preview what YouTube gets, choose when, upload."""
from __future__ import annotations

from pathlib import Path

from nicegui import run, ui

from synergia.config import CFG
from synergia.gui.components import S, media_url, rel, run_folder, status_badge

NOW, NEXT, AT = "now", "next", "at"


def _not_configured() -> None:
    with ui.card().classes("max-w-2xl gap-2"):
        ui.label("YouTube isn't set up yet").classes("text-lg font-semibold")
        ui.label(f"Follow 'Uploading to YouTube' in README.md. It needs {CFG.youtube.client_secret}.")
        for step in ("Create a Google Cloud project and enable YouTube Data API v3.",
                     "Configure the consent screen as External and add yourself as a test user.",
                     "Create a Desktop app OAuth client and save its JSON as secrets/client_secret.json.",
                     "Reload this page."):
            ui.label(f"• {step}").classes("text-sm opacity-80")


def _preview(folder: Path) -> None:
    from synergia import publish
    from synergia.publish import youtube
    from synergia.video import video_info

    post = publish.load_post(folder)
    sn = youtube.build_body(post, CFG.youtube.privacy)["snippet"]
    info = video_info(post.video)
    with ui.row().classes("w-full gap-4 items-start no-wrap max-md:flex-wrap"):
        ui.video(media_url(post.video)).style("width: 240px; max-width: 100%; border-radius: 12px")
        with ui.column().classes("gap-2 min-w-0 grow"):
            ui.label(sn["title"]).classes("text-lg font-semibold")
            ui.label(sn["description"] or "(no description)").classes("text-sm whitespace-pre-wrap opacity-80")
            ui.label(f"Tags: {', '.join(sn['tags']) or '-'}").classes("text-xs opacity-60")
            ui.label(f"{post.video.name} · {info['width']}x{info['height']} · {info['duration']:.1f}s") \
                .classes("text-xs opacity-60")
            for w in youtube.shorts_warnings(info):
                ui.label(f"Not a Short: {w}").classes("text-sm text-warning")
            prev = publish.read_ledger(folder).get("youtube")
            if prev:
                ui.label(f"Already uploaded on {prev.get('uploaded_at', '?')}: {prev.get('url')}") \
                    .classes("text-sm text-warning")
            ui.label("Title and description come from caption.txt. Edit it in the Library.") \
                .classes("text-xs opacity-40")


def page(run_path: str = "") -> None:
    from synergia import publish
    from synergia.publish import schedule as sch
    from synergia.publish import youtube

    ui.label("Upload to YouTube").classes("text-xl font-semibold")
    if not youtube.is_configured():
        _not_configured()
        return
    runs = publish.recent_runs(limit=30)
    if not runs:
        ui.label("No rendered videos in output/ yet.").classes("opacity-60")
        return

    pre = run_folder(run_path) if run_path else None
    selected: dict[Path, bool] = {d: d == pre for d in runs}
    if pre and pre not in selected:   # older than the list cut-off
        runs.insert(0, pre)
        selected[pre] = True
    focus = {"run": pre or runs[0]}

    with ui.row().classes("w-full gap-6 items-start no-wrap max-lg:flex-wrap"):
        with ui.card().classes("gap-1 w-full lg:w-[440px] shrink-0"):
            ui.label("Recent videos").classes("font-semibold")
            ui.label("Tick the ones to upload. Click a name to preview it.").classes("text-xs opacity-60")

            @ui.refreshable
            def run_list() -> None:
                for d in runs:
                    with ui.row().classes("w-full items-center gap-1 no-wrap"):
                        ui.checkbox(value=selected[d],
                                    on_change=lambda e, d=d: (selected.__setitem__(d, e.value),
                                                              when_box.refresh()))
                        ui.label(d.parent.name[:1]).classes("text-xs opacity-50 w-3")
                        ui.label(d.name.split("_", 2)[-1].replace("-", " ")) \
                            .classes("text-sm grow cursor-pointer truncate "
                                     + ("text-primary" if d == focus["run"] else "")) \
                            .on("click", lambda _, d=d: show(d))
                        status_badge(d)
            run_list()

        with ui.column().classes("grow gap-4 min-w-0"):
            preview_card = ui.card().classes("w-full")

            def show(d: Path) -> None:
                focus["run"] = d
                preview_card.clear()
                with preview_card:
                    try:
                        _preview(d)
                    except Exception as e:  # noqa: BLE001
                        ui.label(f"Can't preview {d.name}: {e}").classes("text-negative")
                run_list.refresh()

            @ui.refreshable
            def when_box() -> None:
                picks = [d for d in runs if selected[d]]
                slot = sch.next_slot()
                opts = {NOW: f"Now ({CFG.youtube.privacy})"}
                if slot:
                    opts[NEXT] = (f"Next free slot{'s, one per video' if len(picks) > 1 else ''} "
                                  f"(from {sch.fmt(slot)})")
                if len(picks) <= 1:
                    opts[AT] = "Pick a date and time"
                with ui.card().classes("w-full gap-2"):
                    ui.label(f"When? · {len(picks)} selected").classes("font-semibold")
                    when = ui.radio(opts, value=NOW).props("inline")
                    with ui.row().classes("gap-2").bind_visibility_from(when, "value", value=AT):
                        day = ui.date_input("Date").props("outlined dense")
                        hour = ui.time_input("Time", value="18:00").props("outlined dense")
                    ui.label("Scheduled videos upload now as private and YouTube makes them public "
                             "at that time, so your PC can be off.").classes("text-xs opacity-50")
                    progress = ui.linear_progress(0, show_value=False).classes("w-full")
                    progress.visible = False
                    status = ui.label().classes("text-sm")
                    results = ui.column().classes("gap-1")

                    async def go() -> None:
                        if not picks:
                            ui.notify("Tick at least one video.", type="warning")
                            return
                        at = None
                        if when.value == AT:
                            try:
                                at = sch.parse_when(f"{day.value} {hour.value}")
                            except ValueError as e:
                                ui.notify(f"Pick a valid future date and time ({e}).", type="warning")
                                return
                        await confirm_and_upload(picks, when.value, at, progress, status, results)

                    ui.button(f"Upload {len(picks) or ''}".strip(), icon="cloud_upload", on_click=go) \
                        .props("size=lg")

            when_box()
            show(focus["run"])

    async def confirm_and_upload(picks, mode, at, progress, status, results) -> None:
        if S.busy:
            ui.notify("Something is already running. Wait for it to finish.", type="warning")
            return
        if mode == NEXT and not sch.next_slot():
            ui.notify("No free slot found (check schedule_slots in config.toml).", type="warning")
            return
        again = [d for d in picks if publish.read_ledger(d).get("youtube")]
        when_txt = {NOW: f"now, {CFG.youtube.privacy}", NEXT: "each at the next free slot",
                    AT: f"public {sch.fmt(at) if at else ''}"}[mode]
        with ui.dialog() as dlg, ui.card().classes("gap-2"):
            ui.label(f"Upload {len(picks)} video{'s' if len(picks) > 1 else ''} ({when_txt})?") \
                .classes("font-semibold")
            for d in picks:
                ui.label(f"• {d.name}").classes("text-sm")
            if again:
                ui.label(f"{len(again)} of them {'is' if len(again) == 1 else 'are'} already on YouTube "
                         "and will be uploaded again.").classes("text-sm text-warning")
            with ui.row().classes("gap-2 pt-2"):
                ui.button("Upload", on_click=lambda: dlg.submit(True))
                ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat color=grey")
        if not await dlg:
            return

        S.busy = True
        progress.visible = True
        state = {"f": 0.0}
        timer = ui.timer(0.3, lambda: progress.set_value(state["f"]))
        results.clear()
        try:
            for i, d in enumerate(picks, 1):
                when = at if mode == AT else (sch.next_slot() if mode == NEXT else None)
                status.set_text(f"Uploading {i}/{len(picks)}: {d.name}"
                                + (f" → public {sch.fmt(when)}" if when else ""))
                state["f"] = 0.0
                try:
                    post = publish.load_post(d)
                    res = await run.io_bound(youtube.upload, post, publish_at=when,
                                             on_progress=lambda f: state.__setitem__("f", f))
                except Exception as e:  # noqa: BLE001 — report and continue with the next pick
                    with results:
                        ui.label(f"✗ {d.name}: {e}").classes("text-sm text-negative")
                    if isinstance(e, youtube.NotConfigured) or youtube.is_limit_error(e):
                        with results:
                            ui.label("Stopped the batch; the rest would fail the same way.") \
                                .classes("text-sm opacity-60")
                        break
                    continue
                with results:
                    with ui.row().classes("gap-2 items-center"):
                        ui.label("✓ Scheduled for " + sch.fmt(when) if res.get("publish_at")
                                 else f"✓ Uploaded ({res['privacy']})").classes("text-sm text-positive")
                        ui.link(res["url"], res["url"], new_tab=True).classes("text-sm")
                    if res.get("schedule_dropped"):
                        ui.label("YouTube ignored the schedule (unaudited API projects can only upload "
                                 "private videos). Set it in YouTube Studio: Visibility → Schedule.") \
                            .classes("text-xs text-warning")
                    elif not when and res["privacy"] != CFG.youtube.privacy:
                        ui.label(f"YouTube set it to {res['privacy']} instead of {CFG.youtube.privacy}. "
                                 "Change it in YouTube Studio.").classes("text-xs text-warning")
            status.set_text("Done.")
        finally:
            S.busy = False
            timer.cancel()
            progress.visible = False
            run_list.refresh()
