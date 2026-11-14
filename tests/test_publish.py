"""Checks for post metadata (caption.txt parsing, YouTube limits). No network. Run: .venv\\Scripts\\python -m pytest tests"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synergia.output import caption_text  # noqa: E402
from synergia.publish import hashtags_in, load_post, parse_caption, read_ledger, record  # noqa: E402
from synergia.publish import youtube  # noqa: E402


def test_parse_roundtrip():
    text = caption_text({"title": "Why **losing** hurts", "caption": "Be honest.\n\nLine two.",
                         "credit": "🎙️ Credit: Someone", "hashtags": ["#psychology", "#mindset"]})
    title, desc = parse_caption(text)
    assert title == "Why losing hurts"
    assert desc == "Be honest.\n\nLine two.\n\n🎙️ Credit: Someone\n\n#psychology #mindset"


def test_parse_headerless():
    assert parse_caption("just a caption #x\n") == ("", "just a caption #x")


def test_hashtags():
    assert hashtags_in("hi #a #b_c #a &#39; x#y") == ["a", "b_c"]


def test_load_post_and_ledger(tmp_path):
    run = tmp_path / "2026-11-14_213414_loss-aversion"
    run.mkdir()
    (run / "explainer.mp4").write_bytes(b"")
    post = load_post(run)
    assert post.title == "Loss aversion" and post.video.name == "explainer.mp4"
    record(run, "youtube", {"id": "abc"})
    assert read_ledger(run)["youtube"]["id"] == "abc"


def test_body_limits(tmp_path):
    from synergia.publish import Post
    long_title = "word " * 40
    p = Post(tmp_path, tmp_path / "x.mp4", "<b>" + long_title, "é" * 3000, ["t" * 30] * 40)
    body = youtube.build_body(p, "private")
    sn = body["snippet"]
    assert len(sn["title"]) <= youtube.TITLE_MAX and "<" not in sn["title"]
    assert len(sn["description"].encode("utf-8")) <= youtube.DESCRIPTION_MAX
    assert len(",".join(sn["tags"])) <= youtube.TAGS_MAX
    assert body["status"]["privacyStatus"] == "private"


def test_shorts_warnings():
    assert youtube.shorts_warnings({"width": 1080, "height": 1920, "duration": 59}) == []
    assert len(youtube.shorts_warnings({"width": 1920, "height": 1080, "duration": 200})) == 2


def _ref():
    from datetime import datetime
    return datetime(2026, 11, 14, 20, 0).astimezone()   # Saturday 20:00 local


def test_parse_when():
    from synergia.publish.schedule import parse_when
    ref = _ref()
    assert parse_when("tomorrow 18:00", ref).strftime("%Y-%m-%d %H:%M") == "2026-11-15 18:00"
    assert parse_when("21:30", ref).strftime("%Y-%m-%d %H:%M") == "2026-11-14 21:30"
    assert parse_when("18:00", ref).strftime("%Y-%m-%d %H:%M") == "2026-11-15 18:00"   # passed -> tomorrow
    assert parse_when("fri 9:30", ref).strftime("%Y-%m-%d %H:%M") == "2026-11-20 09:30"
    assert parse_when("sat 18:00", ref).strftime("%Y-%m-%d %H:%M") == "2026-11-21 18:00"
    assert parse_when("2026-12-01 08:05", ref).strftime("%Y-%m-%d %H:%M") == "2026-12-01 08:05"
    assert parse_when("3.12 10:00", ref).strftime("%Y-%m-%d %H:%M") == "2026-12-03 10:00"
    for bad in ("today 10:00", "soon", "2026-01-01 10:00", "blah 10:00"):
        try:
            parse_when(bad, ref)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_next_free_slot():
    from synergia.publish.schedule import next_free_slot, parse_slots
    ref = _ref()
    slots = parse_slots(["18:00", "12:00", "21:00"])
    a = next_free_slot(slots, set(), ref)
    assert a.strftime("%d %H:%M") == "14 21:00"
    b = next_free_slot(slots, {a}, ref)
    assert b.strftime("%d %H:%M") == "15 12:00"
    c = next_free_slot(slots, {a, b}, ref)
    assert c.strftime("%d %H:%M") == "15 18:00"
    # within MIN_LEAD of now is skipped
    from datetime import timedelta
    assert next_free_slot(slots, set(), a - timedelta(minutes=5)) == b


def test_body_publish_at():
    from synergia.publish import Post
    p = Post(Path("."), Path("x.mp4"), "t", "d", [])
    st = youtube.build_body(p, "public", _ref())["status"]
    assert st["privacyStatus"] == "private" and st["publishAt"].endswith("Z")
    assert "publishAt" not in youtube.build_body(p, "public")["status"]


if __name__ == "__main__":
    import inspect
    import tempfile
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            if inspect.signature(fn).parameters:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print("ok", name)
