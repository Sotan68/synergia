"""Autopilot page: render a week of videos in one go, review them, and queue them for YouTube."""
from __future__ import annotations

import time
from datetime import datetime

from nicegui import run, ui

from synergia import autopilot as ap
from synergia.config import CFG
from synergia.gui.components import S, busy, is_busy, media_url
from synergia.output import ENGINE_NAMES
STATUS_COLORS = {ap.PENDING: "grey", ap.RENDERING: "warning", ap.REVIEW: "primary",
                 ap.APPROVED: "positive", ap.DROPPED: "grey-7", ap.FAILED: "negative",
                 ap.SCHEDULED: "secondary"}
STATUS_TEXT = {ap.PENDING: "waiting", ap.RENDERING: "rendering…", ap.REVIEW: "to review",
               ap.APPROVED: "approved", ap.DROPPED: "dropped", ap.FAILED: "failed",
               ap.SCHEDULED: "scheduled"}


def _slots_per_day() -> int:
    return max(1, len(CFG.youtube.schedule_slots or []))


def _fmt(at: str | datetime) -> str:
    from synergia.publish import schedule as sch
    return sch.fmt(datetime.fromisoformat(at) if isinstance(at, str) else at)


# ================================================================ status strip

def status_strip() -> None:
    from synergia.publish import queue, task
    from synergia.publish import youtube

    @ui.refreshable
    def strip() -> None:
        waiting = sorted((i for i in queue.load() if i.get("status") == queue.QUEUED),
                         key=lambda i: i["publish_at"])
        last = queue.last_status()
        t = task.status()
        with ui.card().classes("w-full gap-2 py-3"):
            with ui.row().classes("w-full items-center gap-x-6 gap-y-1"):
                ui.label("Upload queue").classes("font-semibold")
                ui.label(f"{len(waiting)} waiting" + (f" · next goes live {_fmt(waiting[0]['publish_at'])}"
                                                      if waiting else "")).classes("text-sm")
                ui.label(f"{queue.uploads_today()}/{queue.daily_limit()} uploads used today") \
                    .classes("text-sm opacity-60")
                if t.get("installed"):
                    ui.label(f"Daily uploads: on ({task.upload_time()}"
                             + (f", last ran {t['last_run']}" if t.get("last_run") else "") + ")") \
                        .classes("text-sm text-positive")
                else:
                    ui.label("Daily uploads: off").classes("text-sm text-warning")
            if last:
                msg = f"Last upload run {last.get('ran_at', '')[:16].replace('T', ' ')}: " \
                      f"{len(last.get('uploaded', []))} uploaded"
                if last.get("errors"):
                    msg += f", {len(last['errors'])} failed ({last['errors'][-1]['error'][:120]})"
                if last.get("stopped"):
                    msg += f". Stopped: {last['stopped'][:140]}"
                ui.label(msg).classes("text-xs opacity-60")
            if last.get("needs_sign_in"):
                ui.label("The YouTube sign-in expired, so the daily job can't upload. Sign in again.") \
                    .classes("text-sm text-warning")
            elif youtube.is_configured() and not youtube.can_read_schedule():
                ui.label("Queued videos only skip slots Synergia booked. Sign in again so they also "
                         "skip videos scheduled in YouTube Studio.").classes("text-sm text-warning")
            with ui.row().classes("gap-2"):
                if youtube.is_configured():
                    if not t.get("installed"):
                        ui.button("Install daily uploads", icon="schedule", on_click=install) \
                            .props("size=sm")
                    if waiting:
                        ui.button("Upload due now", icon="cloud_upload", on_click=upload_now) \
                            .props("outline size=sm")
                    if last.get("needs_sign_in") or not youtube.can_read_schedule():
                        ui.button("Sign in again", icon="login", on_click=sign_in).props("size=sm")
                    if t.get("installed"):
                        ui.button("Turn off daily uploads", on_click=uninstall) \
                            .props("flat size=sm color=grey")
                else:
                    ui.label("YouTube isn't set up yet (see the Upload page), so videos can be made "
                             "and reviewed but not queued.").classes("text-sm opacity-70")

    async def install() -> None:
        res = await busy("Creating the scheduled task…", task.install)
        if res:
            ui.notify(f"Daily uploads on: {res}", type="positive")
        strip.refresh()

    async def uninstall() -> None:
        await busy("Removing the scheduled task…", task.remove)
        strip.refresh()

    async def sign_in() -> None:
        if await busy("Signing in to YouTube (a browser tab opens)…", youtube.sign_in) is not None:
            from synergia.publish import schedule
            schedule.forget_remote()
            ui.notify("Signed in.", type="positive")
        strip.refresh()

    async def upload_now() -> None:
        await upload_due_ui()
        strip.refresh()

    strip()
    return strip


async def upload_due_ui(results: ui.element | None = None) -> dict | None:
    """Upload what today's quota allows, with a per-video result line."""
    from synergia.publish import queue

    lines: list[tuple[str, str]] = []

    def on_item(event: str, info: dict) -> None:
        if event == "done":
            lines.append(("positive", f"✓ {info['folder'].split('/')[-1]} → live {_fmt(info['publish_at'])}"
                          + ("  (YouTube ignored the schedule; set it in YouTube Studio)"
                             if info["schedule_dropped"] else "")))
        elif event == "error":
            lines.append(("negative", f"✗ {info['folder'].split('/')[-1]}: {info['error']}"))

    s = await busy("Uploading to YouTube…", queue.upload_due, None, True, None, on_item)
    if s is None:
        return None
    if results is not None:
        with results:
            for color, text in lines:
                ui.label(text).classes(f"text-sm text-{color}")
    msg = f"{len(s['uploaded'])} uploaded, {s['left']} still queued"
    if s["left"] and s["stopped"] == "daily limit reached":
        msg += " (the daily job uploads the rest)"
    ui.notify(msg, type="positive" if not s["errors"] else "warning", multi_line=True)
    return s


# ================================================================ start panel

def start_panel(refresh) -> None:
    from synergia.publish import youtube

    claude_ok = ap.claude_ready() or S.is_demo
    mix = ap.default_mix()
    if not claude_ok:
        for k in ap.NEEDS_CLAUDE:
            mix[k] = 0
    with ui.card().classes("w-full gap-4"):
        ui.label("Make a batch").classes("text-lg font-semibold")
        if S.is_demo:
            ui.label("Demo mode: A, B and E use the built-in sample scripts (no Claude).") \
                .classes("text-sm opacity-60")
        elif not claude_ok:
            ui.label("Claude Code isn't available, so only Podcast clips (offline highlight finder) "
                     "and Brain Tests can be made automatically.").classes("text-sm text-warning")

        inputs: dict[str, ui.number] = {}
        total = ui.label().classes("text-sm opacity-70")

        def update_total() -> None:
            n = sum(int(i.value or 0) for i in inputs.values())
            days = n / _slots_per_day()
            total.set_text(f"= {n} videos · about {days:.0f} day{'s' if round(days) != 1 else ''} "
                           f"at {_slots_per_day()} a day")

        with ui.row().classes("gap-4 items-end"):
            for k in ap.ENGINES:     # only the engines enabled in the profile
                inputs[k] = ui.number(f"{k} · {ENGINE_NAMES[k]}", value=mix[k], min=0, max=30, step=1,
                                      format="%d", on_change=update_total) \
                    .props("outlined dense").classes("w-44")
                if k in ap.NEEDS_CLAUDE and not claude_ok:
                    inputs[k].disable()
        update_total()

        with ui.expansion("Podcast source (Engine C)", icon="podcasts", value=True).classes("w-full"):
            url = ui.input("Episode URL (optional, wins over the watched channels)",
                           placeholder="https://www.youtube.com/watch?v=…") \
                .classes("w-full max-w-2xl").props("outlined dense")
            ui.label("Without a URL, Autopilot takes the newest episode it hasn't clipped yet from one "
                     "of these channels (they take turns).").classes("text-xs opacity-60")
            chans = ap.watched_channels()

            @ui.refreshable
            def chan_list() -> None:
                with ui.row().classes("gap-2 items-center"):
                    if not chans:
                        ui.label("No watched channels yet.").classes("text-sm opacity-50")
                    for c in chans:
                        ui.chip(c, removable=True, on_value_change=lambda _, c=c: remove(c)) \
                            .props("outline")

            def remove(c: str) -> None:
                chans.remove(c)
                ap.save_channels(chans)
                chan_list.refresh()

            def add() -> None:
                c = new.value.strip()
                if c and c not in chans:
                    chans.append(c)
                    ap.save_channels(chans)
                new.value = ""
                chan_list.refresh()

            chan_list()
            with ui.row().classes("gap-2 items-center"):
                new = ui.input("Add a channel", placeholder="@ChrisWillx or a channel URL") \
                    .props("outlined dense").classes("w-72")
                new.on("keydown.enter", add)
                ui.button("Add", on_click=add).props("outline size=sm")

        async def go() -> None:
            if is_busy():
                ui.notify("Something is already running. Wait for it to finish.", type="warning")
                return
            m = {k: int(i.value or 0) for k, i in inputs.items()}
            if not sum(m.values()):
                ui.notify("Choose at least one video.", type="warning")
                return
            try:
                ap.start(sum(m.values()), m, url.value or "", S.is_demo, S.debug)
            except (RuntimeError, ValueError) as e:
                ui.notify(str(e), type="warning")
                return
            refresh()

        with ui.row().classes("gap-3 items-center"):
            ui.button("Start autopilot", icon="rocket_launch", on_click=go).props("size=lg")
            ui.label("Keep this PC on while it renders (roughly 1-2 minutes per video, plus the "
                     "episode transcription). You can close this tab; the console shows progress.") \
                .classes("text-xs opacity-50 max-w-md")
        if not youtube.is_configured():
            ui.label("YouTube isn't set up yet: you can make and review videos, but not queue them.") \
                .classes("text-xs text-warning")


# ================================================================ progress

def progress_panel(refresh) -> None:
    p = ap.PROGRESS
    with ui.card().classes("w-full gap-3"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.spinner(size="lg")
            ui.label("Autopilot is working").classes("text-lg font-semibold")
            ui.space()
            elapsed = ui.label().classes("text-sm opacity-60")
        label = ui.label().classes("text-base")
        bar = ui.linear_progress(0, show_value=False).classes("w-full")
        with ui.expansion("Log", icon="list").classes("w-full"):
            log = ui.label().classes("text-xs whitespace-pre-wrap opacity-70 font-mono")

        def stop() -> None:
            p.cancel = True
            ui.notify("Stopping after the current video…")
        ui.button("Stop after this video", icon="stop", on_click=stop).props("flat color=grey")

        def tick() -> None:
            if not p.running:
                timer.cancel()
                refresh()
                return
            label.set_text(p.label)
            bar.set_value(p.done / p.total if p.total else 0)
            elapsed.set_text(f"{p.done}/{p.total} · {time.monotonic() - p.started:.0f}s")
            log.set_text("\n".join(p.log[-30:]))
        timer = ui.timer(1, tick)
        tick()


# ================================================================ review queue

def _item_card(batch: dict, it: dict, refresh) -> None:
    from synergia.publish import find_video

    folder = ap.folder_of(it)
    video = find_video(folder) if folder else None
    cap = folder / "caption.txt" if folder else None
    st = it["status"]
    with ui.card().classes("w-full gap-2" + (" opacity-50" if st == ap.DROPPED else "")):
        with ui.row().classes("w-full items-center gap-2"):
            ui.label(f"#{it['id']}").classes("text-sm opacity-50")
            ui.label(ENGINE_NAMES[it["engine"]] + (f" · {it['mode']}" if it.get("mode") else "")) \
                .classes("text-xs opacity-60")
            ui.badge(STATUS_TEXT[st], color=STATUS_COLORS[st])
            if st == ap.SCHEDULED and it.get("publish_at"):
                ui.label(f"live {_fmt(it['publish_at'])}").classes("text-xs text-secondary")
        ui.label(it.get("topic") or "").classes("font-medium leading-tight")
        if it.get("error"):
            ui.label(it["error"][:300]).classes("text-xs text-negative")
        if video:
            ui.video(media_url(video)).style("width: 100%; max-width: 260px; border-radius: 10px")
        if cap and cap.is_file() and st in (ap.REVIEW, ap.APPROVED):
            box = ui.textarea("caption.txt", value=cap.read_text(encoding="utf-8")) \
                .classes("w-full text-xs").props("outlined autogrow dense")

            def save() -> None:
                cap.write_text(box.value.rstrip() + "\n", encoding="utf-8")
                ui.notify("Caption saved", type="positive")
            box.on("blur", save)

        async def regen() -> None:
            what = "Replacing the clip" if it["engine"] == "C" else "Making it again"
            if await busy(f"{what}…", ap.regenerate, batch["id"], it["id"], S.debug) is not None:
                refresh()

        def set_status(s: str) -> None:
            ap.set_item(batch["id"], it["id"], status=s)
            refresh()

        with ui.row().classes("gap-1"):
            if st == ap.REVIEW:
                ui.button("Approve", icon="check", on_click=lambda: set_status(ap.APPROVED)).props("size=sm")
            if st == ap.APPROVED:
                ui.button("Unapprove", on_click=lambda: set_status(ap.REVIEW)).props("flat size=sm")
            if st in (ap.REVIEW, ap.APPROVED):
                ui.button("Drop", icon="close", on_click=lambda: set_status(ap.DROPPED)) \
                    .props("flat size=sm color=grey")
            if st == ap.DROPPED:
                ui.button("Restore", on_click=lambda: set_status(ap.REVIEW if folder else ap.FAILED)) \
                    .props("flat size=sm")
            if st in (ap.REVIEW, ap.APPROVED, ap.FAILED):
                if it["engine"] == "C":
                    spare = ap.spares_left(batch)
                    b = ui.button(f"Replace ({spare} left)", icon="swap_horiz", on_click=regen) \
                        .props("flat size=sm")
                    if not spare:
                        b.disable()
                else:
                    ui.button("Retry" if st == ap.FAILED else "Regenerate", icon="refresh",
                              on_click=regen).props("flat size=sm")


def review_panel(batch: dict, refresh, strip) -> None:
    from synergia.publish import queue
    from synergia.publish import youtube

    c = ap.counts(batch)
    approved = [i for i in batch["items"] if i["status"] == ap.APPROVED and ap.folder_of(i)]
    with ui.card().classes("w-full gap-2"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.label(f"Batch {batch['id'].replace('_', ' ')}").classes("text-lg font-semibold")
            ui.label(" · ".join(f"{n} {STATUS_TEXT[s]}" for s, n in c.items())).classes("text-sm opacity-60")
        for n in batch.get("notes", []):
            ui.label(n).classes("text-sm text-warning")
        if batch.get("c"):
            ui.label(f"Podcast clips from “{batch['c']['name']}”").classes("text-sm opacity-70")
        ui.label("Approve the ones you like (you can edit the caption; it saves when you click away), "
                 "then schedule them. Each one gets the next free posting slot.").classes("text-xs opacity-60")
        results = ui.column().classes("gap-1")

        def approve_all() -> None:
            ap.update(batch["id"], lambda b: [i.update(status=ap.APPROVED) for i in b["items"]
                                             if i["status"] == ap.REVIEW])
            refresh()

        async def schedule() -> None:
            if not approved:
                ui.notify("Approve at least one video first.", type="warning")
                return
            try:
                slots = queue.preview_slots(len(approved))
            except ValueError as e:
                ui.notify(str(e), type="warning")
                return
            today_left = max(0, queue.daily_limit() - queue.uploads_today())
            with ui.dialog() as dlg, ui.card().classes("gap-2"):
                ui.label(f"Schedule {len(approved)} video{'s' if len(approved) > 1 else ''}?") \
                    .classes("font-semibold")
                for it, at in zip(approved, slots):
                    ui.label(f"• {_fmt(at)}  {(it.get('topic') or '')[:60]}").classes("text-sm")
                ui.label(f"{min(today_left, len(approved))} upload now (today's quota); "
                         + ("the daily job uploads the rest, each before it goes live."
                            if len(approved) > today_left else "nothing has to wait.")) \
                    .classes("text-xs opacity-60")
                with ui.row().classes("gap-2 pt-2"):
                    ui.button("Schedule", on_click=lambda: dlg.submit(True))
                    ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat color=grey")
            if not await dlg:
                return
            try:
                ap.schedule_approved(batch["id"])
            except ValueError as e:
                ui.notify(str(e), type="negative")
                return
            await upload_due_ui(results)
            strip.refresh()
            refresh()

        def discard() -> None:
            ap.close(batch["id"])
            refresh()

        with ui.row().classes("gap-2"):
            if c.get(ap.REVIEW):
                ui.button(f"Approve all {c[ap.REVIEW]}", icon="done_all", on_click=approve_all).props("outline")
            if youtube.is_configured():
                ui.button(f"Schedule approved ({len(approved)})", icon="event", on_click=schedule)
            ui.button("Close batch", on_click=discard).props("flat color=grey") \
                .tooltip("Hide this batch and start a new one. The videos stay in the Library.")

    with ui.grid().classes("w-full gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"):
        for it in batch["items"]:
            _item_card(batch, it, refresh)


# ================================================================ page

def page() -> None:
    with ui.row().classes("w-full items-baseline gap-3"):
        ui.label("Autopilot").classes("text-xl font-semibold")
        ui.label("A week of videos in one go: render, review, schedule.").classes("text-sm opacity-60")
    strip = status_strip()
    area = ui.column().classes("w-full gap-4")

    def refresh() -> None:
        area.clear()
        with area:
            if ap.running():
                progress_panel(refresh)
                return
            b = ap.current()
            if b:
                review_panel(b, refresh, strip)
            else:
                start_panel(refresh)
    refresh()
