"""Upload queue: approved videos waiting for their YouTube upload, each with a reserved go-live slot.

YouTube's free API quota allows about 6 uploads a day, so a week of videos can't all go up at once.
Approved videos are queued in <cache_dir>/queue.json with a publish time. upload_due() uploads the
ones next in line, up to what's left of today's quota. Autopilot calls it right after approval, and a
daily Windows scheduled task (`main.py --upload-due`) calls it for the rest.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from synergia.config import CFG
from synergia.publish import find_video, load_post, read_ledger

QUEUED, UPLOADED, FAILED = "queued", "uploaded", "failed"
MAX_ATTEMPTS = 3   # a video that fails this many runs in a row is marked failed (not retried forever)


def _cfg(name: str, default):
    return getattr(getattr(CFG, "autopilot", None), name, default)


def _path() -> Path:
    return CFG.output.cache_dir / "queue.json"


def status_path() -> Path:
    return CFG.output.cache_dir / "upload_status.json"


def load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(items: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")


def _rel(folder: Path) -> str:
    return Path(folder).resolve().relative_to(CFG.output.dir.resolve()).as_posix()


def _abs(rel: str) -> Path:
    return CFG.output.dir / rel


def _when(item: dict) -> datetime:
    return datetime.fromisoformat(item["publish_at"]).astimezone()


def queued_times() -> set[datetime]:
    """Go-live times reserved by queued (not yet uploaded) videos."""
    out = set()
    for it in load():
        if it.get("status") == QUEUED:
            try:
                out.add(_when(it))
            except (KeyError, ValueError):
                pass
    return out


def entry(folder: Path) -> dict | None:
    """The queue entry for a run folder that is still waiting, if any."""
    try:
        rel = _rel(folder)
    except ValueError:
        return None
    return next((it for it in load() if it.get("folder") == rel and it.get("status") == QUEUED), None)


def enqueue(folders: list[Path]) -> list[dict]:
    """Give each folder the next free go-live slot and queue it. Folders already queued keep their slot."""
    from synergia.publish import schedule as sch

    items = load()
    waiting = {it["folder"] for it in items if it.get("status") == QUEUED}
    slots = sch.parse_slots(CFG.youtube.schedule_slots)
    added = []
    for f in folders:
        rel = _rel(f)
        if rel in waiting:
            continue
        when = sch.next_free_slot(slots, sch.taken() | {_when(it) for it in added})
        it = {"folder": rel, "publish_at": when.isoformat(timespec="minutes"), "status": QUEUED,
              "added_at": datetime.now().isoformat(timespec="seconds"), "attempts": 0}
        items.append(it)
        added.append(it)
        save(items)
    return added


def preview_slots(n: int) -> list[datetime]:
    """The go-live times the next n queued videos would get (nothing is saved)."""
    from synergia.publish import schedule as sch
    slots = sch.parse_slots(CFG.youtube.schedule_slots)
    booked = sch.taken()
    out: list[datetime] = []
    for _ in range(n):
        out.append(sch.next_free_slot(slots, booked | set(out)))
    return out


def remove(folder: Path) -> None:
    rel = _rel(folder)
    save([it for it in load() if not (it.get("folder") == rel and it.get("status") == QUEUED)])


# ---------------------------------------------------------------- daily quota

def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _pacific_offset(utc: datetime) -> timedelta:
    """US Pacific time offset (DST: 2nd Sunday of March 2:00 to 1st Sunday of November 2:00)."""
    y = utc.year
    start = datetime.combine(_nth_sunday(y, 3, 2), datetime.min.time(), timezone.utc) + timedelta(hours=10)
    end = datetime.combine(_nth_sunday(y, 11, 1), datetime.min.time(), timezone.utc) + timedelta(hours=9)
    return timedelta(hours=-7 if start <= utc < end else -8)


def quota_day_start(ref: datetime | None = None) -> datetime:
    """When today's YouTube API quota started: the last midnight in US Pacific time."""
    utc = (ref or datetime.now().astimezone()).astimezone(timezone.utc)
    off = _pacific_offset(utc)
    local = (utc + off).replace(hour=0, minute=0, second=0, microsecond=0)
    return (local - off).replace(tzinfo=timezone.utc)


def uploads_today(ref: datetime | None = None) -> int:
    """Uploads (any run folder) since the quota last reset, from every posted.json."""
    start = quota_day_start(ref)
    root = CFG.output.dir
    n = 0
    for ledger in root.glob("*/*/posted.json") if root.is_dir() else []:
        at = read_ledger(ledger.parent).get("youtube", {}).get("uploaded_at")
        try:
            if at and datetime.fromisoformat(at).astimezone() >= start:
                n += 1
        except ValueError:
            pass
    return n


def daily_limit() -> int:
    return int(_cfg("daily_upload_limit", 6))


# ---------------------------------------------------------------- uploading

def _default_uploader(post, publish_at, interactive):
    from synergia.publish import youtube
    return youtube.upload(post, publish_at=publish_at, interactive=interactive)


def upload_due(limit: int | None = None, interactive: bool = True,
               uploader: Callable | None = None,
               on_item: Callable[[str, dict], None] | None = None,
               ref: datetime | None = None) -> dict:
    """Upload queued videos in go-live order, up to what's left of today's quota.

    on_item(event, info) is called with "start", "done" or "error" for progress display.
    Returns (and saves to upload_status.json) a summary:
    {ran_at, uploaded: [...], errors: [...], left, needs_sign_in, stopped}.
    """
    from synergia.publish import schedule as sch
    from synergia.publish import youtube

    uploader = uploader or _default_uploader
    now = ref or sch.now()
    left = (daily_limit() if limit is None else limit) - uploads_today(now)
    summary: dict = {"ran_at": now.isoformat(timespec="seconds"), "uploaded": [], "errors": [],
                     "needs_sign_in": False, "stopped": ""}
    items = load()
    for it in sorted((i for i in items if i.get("status") == QUEUED), key=_when):
        folder = _abs(it["folder"])
        if not folder.is_dir() or not find_video(folder):
            it.update(status=FAILED, error="the run folder or its video no longer exists")
            summary["errors"].append({"folder": it["folder"], "error": it["error"]})
            save(items)
            continue
        prev = read_ledger(folder).get("youtube")
        if prev:   # uploaded by hand meanwhile
            it.update(status=UPLOADED, url=prev.get("url"), note="already on YouTube")
            save(items)
            continue
        if left <= 0:
            summary["stopped"] = "daily limit reached"
            break
        when = _when(it)
        if when < now + sch.MIN_LEAD:   # PC was off or the job ran late: take the next free slot
            others = {_when(o) for o in items if o is not it and o.get("status") == QUEUED}
            when = sch.next_free_slot(sch.parse_slots(CFG.youtube.schedule_slots),
                                      sch.taken(include_queue=False) | others, now)
            it["publish_at"] = when.isoformat(timespec="minutes")
            save(items)
        if on_item:
            on_item("start", {"folder": it["folder"], "publish_at": when})
        try:
            res = uploader(load_post(folder), when, interactive)
        except youtube.NeedsSignIn as e:
            summary.update(needs_sign_in=True, stopped=str(e))
            break
        except Exception as e:  # noqa: BLE001 — record, then continue or stop
            it["attempts"] = int(it.get("attempts", 0)) + 1
            it["error"] = str(e)
            if it["attempts"] >= MAX_ATTEMPTS:
                it["status"] = FAILED
            save(items)
            summary["errors"].append({"folder": it["folder"], "error": str(e)})
            if on_item:
                on_item("error", {"folder": it["folder"], "error": str(e)})
            if isinstance(e, youtube.NotConfigured) or youtube.is_limit_error(e):
                summary["stopped"] = str(e)
                break
            continue
        it.update(status=UPLOADED, url=res.get("url"), error="")
        if res.get("schedule_dropped"):
            it["note"] = "YouTube ignored the schedule; set it in YouTube Studio"
        save(items)
        left -= 1
        done = {"folder": it["folder"], "url": res.get("url"), "publish_at": it["publish_at"],
                "schedule_dropped": bool(res.get("schedule_dropped"))}
        summary["uploaded"].append(done)
        if on_item:
            on_item("done", done)
    summary["left"] = sum(1 for i in load() if i.get("status") == QUEUED)
    p = status_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    return summary


def last_status() -> dict:
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
