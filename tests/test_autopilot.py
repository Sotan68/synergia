"""Autopilot planning, the upload queue and episode picking. No network, no Claude, no rendering.
Run: .venv\\Scripts\\python -m pytest tests"""
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synergia import autopilot as ap  # noqa: E402
from synergia.config import CFG  # noqa: E402
from synergia.publish import queue, read_ledger, record  # noqa: E402
from synergia.publish import schedule as sch  # noqa: E402
from synergia.publish import youtube  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point output/ and cache/ at a temp folder."""
    monkeypatch.setattr(CFG.output, "dir", tmp_path / "output")
    monkeypatch.setattr(CFG.output, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(sch, "youtube_scheduled", lambda refresh=False: None)   # no network
    (tmp_path / "output").mkdir()
    return tmp_path


def test_slots_skip_videos_scheduled_on_youtube(sandbox, monkeypatch):
    first = sch.next_slot()
    remote = {"studio": first}
    monkeypatch.setattr(sch, "youtube_scheduled", lambda refresh=False: remote)
    assert first in sch.taken() and sch.next_slot() > first
    moved = make_run(sandbox, "2026-01-01_000000_moved")   # rescheduled in Studio: YouTube's time wins
    record(moved, "youtube", {"id": "m", "publish_at": "2030-01-01T12:00+02:00"})
    remote["m"] = first + timedelta(days=1)
    assert datetime.fromisoformat("2030-01-01T12:00+02:00") not in sch.taken()
    assert remote["m"] in sch.taken()


def make_run(root: Path, name: str, engine: str = "D - Brain Test") -> Path:
    d = root / "output" / engine / name
    d.mkdir(parents=True)
    (d / "brain_test.mp4").write_bytes(b"")
    (d / "caption.txt").write_text(f"TITLE:\n{name}\n", encoding="utf-8")
    return d


# ---------------------------------------------------------------- planning

def test_scale_mix():
    assert ap.scale_mix({"A": 2, "B": 2, "C": 5, "D": 3, "E": 2}, 14) == {"A": 2, "B": 2, "C": 5, "D": 3, "E": 2}
    assert sum(ap.scale_mix({"A": 2, "B": 2, "C": 5, "D": 3, "E": 2}, 7).values()) == 7
    assert ap.scale_mix({"A": 0}, 5) == {}


def test_plan_follows_mix_and_never_repeats():
    mix = {"A": 2, "B": 2, "C": 5, "D": 3, "E": 2}
    for seed in range(300):
        jobs = ap.plan_jobs(14, mix, random.Random(seed))
        engines = [j["engine"] for j in jobs]
        assert {k: engines.count(k) for k in mix} == mix
        assert all(a != b for a, b in zip(engines, engines[1:]))
        modes = [j["mode"] for j in jobs if j["engine"] == "E"]
        assert sorted(modes) == ["checklist", "pick"]


def test_plan_heavy_engine_still_alternates():
    for seed in range(200):
        engines = [j["engine"] for j in ap.plan_jobs(9, {"C": 5, "D": 4}, random.Random(seed))]
        assert engines == ["C", "D"] * 4 + ["C"]


# ---------------------------------------------------------------- queue

def test_enqueue_skips_booked_and_queued_slots(sandbox):
    booked = make_run(sandbox, "2026-01-01_000000_booked")
    first = sch.next_slot()
    record(booked, "youtube", {"id": "x", "publish_at": first.isoformat(timespec="minutes")})
    a, b = make_run(sandbox, "2026-01-02_000000_a"), make_run(sandbox, "2026-01-03_000000_b")
    added = queue.enqueue([a, b])
    times = [datetime.fromisoformat(i["publish_at"]) for i in added]
    assert len(set(times)) == 2 and first not in times and all(t > first for t in times)
    assert set(times) <= sch.taken()                      # manual uploads now skip these too
    assert queue.enqueue([a]) == []                        # already queued: keeps its slot
    assert queue.entry(a)["publish_at"] == added[0]["publish_at"]
    assert queue.preview_slots(1)[0] > max(times)


def _fake_uploader(calls, fail=None):
    def up(post, when, interactive):
        calls.append((post.folder.name, when, interactive))
        if fail:
            raise fail
        res = {"id": "v", "url": f"https://youtube.com/shorts/{post.folder.name}", "privacy": "private",
               "publish_at": when.isoformat(timespec="minutes")}
        record(post.folder, "youtube", res)
        return res
    return up


def test_upload_due_respects_daily_limit(sandbox):
    runs = [make_run(sandbox, f"2026-01-0{i}_000000_v{i}") for i in range(1, 4)]
    queue.enqueue(runs)
    calls = []
    s = queue.upload_due(limit=2, uploader=_fake_uploader(calls))
    assert len(calls) == 2 and len(s["uploaded"]) == 2 and s["left"] == 1
    assert s["stopped"] == "daily limit reached"
    assert queue.uploads_today() == 2
    # Next "day": the rest goes up, in go-live order.
    s = queue.upload_due(limit=10, uploader=_fake_uploader(calls))
    assert [c[0] for c in calls] == [r.name for r in runs] and s["left"] == 0
    assert json.loads(queue.status_path().read_text(encoding="utf-8"))["left"] == 0


def test_upload_due_stops_on_quota_error(sandbox):
    queue.enqueue([make_run(sandbox, "2026-01-01_000000_a"), make_run(sandbox, "2026-01-02_000000_b")])
    calls = []
    s = queue.upload_due(uploader=_fake_uploader(calls, RuntimeError("Daily YouTube API quota used up")))
    assert len(calls) == 1 and s["stopped"] and s["left"] == 2
    assert queue.load()[0]["attempts"] == 1 and queue.load()[0]["status"] == queue.QUEUED


def test_upload_due_needs_sign_in(sandbox):
    queue.enqueue([make_run(sandbox, "2026-01-01_000000_a")])
    s = queue.upload_due(interactive=False,
                         uploader=_fake_uploader([], youtube.NeedsSignIn("expired")))
    assert s["needs_sign_in"] and s["left"] == 1


def test_upload_due_moves_missed_slot_and_skips_missing(sandbox):
    late, gone = make_run(sandbox, "2026-01-01_000000_late"), make_run(sandbox, "2026-01-02_000000_gone")
    queue.enqueue([late, gone])
    items = queue.load()
    items[0]["publish_at"] = (sch.now() - timedelta(hours=3)).isoformat(timespec="minutes")
    queue.save(items)
    for f in gone.iterdir():
        f.unlink()
    gone.rmdir()
    calls = []
    s = queue.upload_due(uploader=_fake_uploader(calls))
    assert len(calls) == 1 and calls[0][1] > sch.now()
    assert s["errors"][0]["folder"].endswith("gone")
    assert {i["status"] for i in queue.load()} == {queue.UPLOADED, queue.FAILED}


def test_upload_due_skips_videos_uploaded_by_hand(sandbox):
    run = make_run(sandbox, "2026-01-01_000000_a")
    queue.enqueue([run])
    record(run, "youtube", {"id": "manual", "url": "u"})
    calls = []
    queue.upload_due(uploader=_fake_uploader(calls))
    assert calls == [] and queue.load()[0]["status"] == queue.UPLOADED
    assert read_ledger(run)["youtube"]["id"] == "manual"


def test_quota_day_starts_at_pacific_midnight():
    winter = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)      # PST (UTC-8)
    assert queue.quota_day_start(winter) == datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
    early = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)
    assert queue.quota_day_start(early) == datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)       # PDT (UTC-7)
    assert queue.quota_day_start(summer) == datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)


def test_background_sign_in_never_opens_a_browser(tmp_path, monkeypatch):
    secret = tmp_path / "client_secret.json"
    secret.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(youtube, "_paths", lambda: (secret, tmp_path / "no_token.json"))
    with pytest.raises(youtube.NeedsSignIn):
        youtube._credentials(interactive=False)


# ---------------------------------------------------------------- Engine C episode picking

def _lister(eps: dict):
    def lister(ch):
        if ch not in eps:
            raise RuntimeError("no such channel")
        return eps[ch]
    return lister


EP = lambda i, mins=60: {"id": f"id{i}", "url": f"u{i}", "title": f"t{i}", "duration": mins * 60}  # noqa: E731


def test_pasted_url_wins(sandbox):
    ep, why = ap.find_episode("https://www.youtube.com/watch?v=ngvOyccUzzY", ["@a"], _lister({}))
    assert ep["id"] == "ngvOyccUzzY" and not why


def test_episode_skips_short_and_clipped_and_rotates(sandbox):
    from synergia import history
    lister = _lister({"@a": [EP(1, mins=2), EP(2), EP(3)], "@b": [EP(9)]})
    history.remember("podcast.episodes", ["id2"])
    ep, _ = ap.find_episode("", ["@a", "@b"], lister)
    assert ep["id"] == "id3" and ep["watched"] == "@a"
    history.remember("podcast.channels", ["@a"])
    ep, _ = ap.find_episode("", ["@a", "@b"], lister)      # @a went last time -> @b's turn
    assert ep["id"] == "id9"


def test_no_episode_reasons(sandbox):
    assert ap.find_episode("", [], _lister({}))[0] is None
    ep, why = ap.find_episode("", ["@broken"], _lister({}), log=lambda m: None)
    assert ep is None and why
