"""Quick checks for the clipboard bridge and parsers. Run: .venv\\Scripts\\python -m pytest tests (or python tests\\test_bridge.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synergia import demo  # noqa: E402
from synergia.brand.typography import parse_markup  # noqa: E402
from synergia.engines import listicle, psychology  # noqa: E402
from synergia.engines.podcast import highlights as hl  # noqa: E402
from synergia.llm.bridge import extract_json  # noqa: E402


def test_extract_fenced():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```\nEnjoy') == {"a": 1}


def test_extract_unfenced_trailing_comma():
    assert extract_json('Here: {"a": [1, 2,], "b": "x",} done') == {"a": [1, 2], "b": "x"}


def test_extract_invalid():
    try:
        extract_json("no json here")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_validators():
    assert psychology.validate(dict(demo.PSYCHOLOGY)) == []
    assert listicle.validate(dict(demo.LISTICLE)) == []
    bad = dict(demo.LISTICLE, points=demo.LISTICLE["points"][:3])
    assert listicle.validate(bad)
    assert psychology.validate({"concept": "x"})


def test_markup_glue():
    words = parse_markup("about **how they look**. Done")
    assert words[-2] == [("look", True), (".", False)]


def test_timestamps():
    assert hl.parse_ts("1:02:03") == 3723
    assert hl.parse_ts("02:05") == 125
    assert hl.parse_range("12:30-13:15") == (750, 795)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
