"""Checks for the Engine C steps the GUI uses (no video, no Whisper). Run: .venv\Scripts\python -m pytest tests"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synergia.engines.podcast import engine  # noqa: E402
from synergia.engines.podcast import highlights as hl  # noqa: E402


def _words(n: int = 120, gap: float = 0.5) -> list[dict]:
    """A fake transcript: sentences of 8 words, one word every `gap` seconds."""
    out = []
    for i in range(n):
        w = f"word{i}" + ("." if i % 8 == 7 else "")
        out.append({"w": w, "s": i * gap, "e": i * gap + gap * 0.8, "p": 0.9})
    return out


def test_pick_numbers_and_all():
    cands = [hl.Candidate(10, 40, title="a"), hl.Candidate(50, 80, title="b"), hl.Candidate(90, 110)]
    words = _words(250)
    assert [c.title for c in engine.pick("1,3", cands, words)] == ["a", ""]
    assert len(engine.pick("all", cands, words)) == 3
    custom = engine.pick("0:20-0:45", cands, words)
    assert len(custom) == 1 and 15 <= custom[0].start <= 25


def test_pick_bad_number():
    try:
        engine.pick("7", [hl.Candidate(0, 30)], _words())
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_candidates_heuristic_and_title():
    tr = {"words": _words(240)}
    cands, label = engine.candidates(tr, None)
    assert label == "offline heuristic" and cands
    assert all(engine.suggested_title(c) == "" for c in cands)   # heuristic titles aren't used on screen
    assert engine.suggested_title(hl.Candidate(0, 30, title="Hook", why="strong opener")) == "Hook"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
