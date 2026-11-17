"""Publish times: parse what the user types and find the next free posting slot.

Times are local (the PC's timezone) and timezone-aware; YouTube receives them in UTC.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from pathlib import Path

from synergia.config import CFG
from synergia.publish import read_ledger

MIN_LEAD = timedelta(minutes=15)   # a slot closer than this is skipped (upload + processing time)
SEARCH_DAYS = 120
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def now() -> datetime:
    return datetime.now().astimezone()


def _local(d: date, t: time) -> datetime:
    return datetime.combine(d, t).astimezone()   # naive local -> aware local (DST-correct)


def parse_slots(slots: Iterable[str]) -> list[time]:
    out = []
    for s in slots:
        h, m = (int(x) for x in str(s).strip().split(":"))
        out.append(time(h, m))
    return sorted(set(out))


def parse_when(text: str, ref: datetime | None = None) -> datetime:
    """'2026-11-15 18:00', '15.11 18:00', 'today 18:00', 'tomorrow 9:30', 'fri 18:00', '18:00'.

    A bare time means today, or tomorrow if that time has already passed. Raises ValueError.
    """
    ref = ref or now()
    s = text.strip().lower()
    m = re.fullmatch(r"(.*?)\s*(\d{1,2})[:.](\d{2})", s)
    if not m:
        raise ValueError(f"no time in '{text}' (use HH:MM, e.g. 'tomorrow 18:00')")
    day, t = m.group(1).strip(), time(int(m.group(2)), int(m.group(3)))
    today = ref.date()
    if day in ("", "today"):
        when = _local(today, t)
        if not day and when <= ref:
            when = _local(today + timedelta(days=1), t)
    elif day in ("tomorrow", "tmr", "tmrw"):
        when = _local(today + timedelta(days=1), t)
    elif day[:3] in WEEKDAYS:
        ahead = (WEEKDAYS.index(day[:3]) - today.weekday()) % 7
        when = _local(today + timedelta(days=ahead), t)
        if when <= ref:
            when += timedelta(days=7)
    elif dm := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", day):
        when = _local(date(*map(int, dm.groups())), t)
    elif dm := re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?", day):
        d, mo, y = dm.groups()
        when = _local(date(int(y or today.year), int(mo), int(d)), t)
        if not y and when <= ref:
            when = _local(date(today.year + 1, int(mo), int(d)), t)
    else:
        raise ValueError(f"didn't understand the day in '{text}'")
    if when <= ref:
        raise ValueError(f"{fmt(when)} is in the past")
    return when


REMOTE_TTL = 300   # seconds to reuse the channel's schedule before asking YouTube again
_remote: dict = {"at": 0.0, "times": None}


def youtube_scheduled(refresh: bool = False) -> dict[str, datetime] | None:
    """{video id: go-live time} of videos scheduled on the channel itself, including ones scheduled
    in YouTube Studio or from another PC. None if the sign-in can't read the channel or YouTube
    can't be reached (then only Synergia's own records count)."""
    import time as _t
    from synergia.publish import youtube
    if not youtube.can_read_schedule():
        return None
    if refresh or _remote["times"] is None or _t.monotonic() - _remote["at"] > REMOTE_TTL:
        try:
            _remote["times"] = youtube.scheduled()
        except Exception:  # noqa: BLE001 — offline, sign-in expired, quota: fall back to local records
            return _remote["times"]
        _remote["at"] = _t.monotonic()
    return _remote["times"]


def forget_remote() -> None:
    """Ask YouTube again next time (after an upload changed the schedule)."""
    _remote["at"] = float("-inf")


def taken(platform: str = "youtube", include_queue: bool = True) -> set[datetime]:
    """Publish times already booked: earlier uploads (every posted.json), videos waiting in the
    autopilot upload queue, and whatever is scheduled on the YouTube channel itself."""
    root: Path = CFG.output.dir
    out = set()
    remote = youtube_scheduled() if platform == "youtube" else None
    if include_queue and platform == "youtube":
        from synergia.publish import queue
        out |= queue.queued_times()
    for ledger in root.glob("*/*/posted.json") if root.is_dir() else []:
        entry = read_ledger(ledger.parent).get(platform, {})
        at = entry.get("publish_at")
        if at and not (remote is not None and entry.get("id") in remote):   # YouTube's time wins
            try:
                out.add(datetime.fromisoformat(at).astimezone())
            except ValueError:
                pass
    if remote:
        out |= set(remote.values())
    return out


def next_free_slot(slots: list[time], booked: set[datetime], ref: datetime | None = None) -> datetime:
    if not slots:
        raise ValueError("no schedule_slots in [youtube] in config.toml")
    ref = ref or now()
    booked_min = {b.replace(second=0, microsecond=0) for b in booked}
    for i in range(SEARCH_DAYS):
        day = ref.date() + timedelta(days=i)
        for t in slots:
            cand = _local(day, t)
            if cand >= ref + MIN_LEAD and cand not in booked_min:
                return cand
    raise ValueError(f"no free slot in the next {SEARCH_DAYS} days")


def fmt(when: datetime) -> str:
    """Sat 15 Nov 18:00"""
    return f"{when:%a} {when.day} {when:%b %H:%M}"


def next_slot() -> datetime | None:
    """Next free slot from schedule_slots in config.toml, or None if there is none (or it's misconfigured)."""
    try:
        return next_free_slot(parse_slots(CFG.youtube.schedule_slots), taken())
    except (ValueError, AttributeError):
        return None
