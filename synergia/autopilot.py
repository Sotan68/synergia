"""Autopilot: render a whole week of videos in one go, then review them and queue them for YouTube.

A batch is planned from a mix of engines (e.g. C5 A2 B2 D3 E2 for 14 videos), interleaved so the
same engine never runs twice in a row. It then runs in a background thread:
  1. Engine C: find one podcast episode (a pasted URL, or the newest unclipped episode of a
     watched channel), transcribe it, and let Claude pick the moments (+2 spares for Replace).
  2. Ask Claude once per engine type for fresh topics (skipping ones used before).
  3. Write each script with Claude and render each video, one item at a time.
Every step is saved to <cache_dir>/autopilot/<batch id>.json, so a reload or crash loses nothing.
The GUI (gui/autopilot.py) shows progress and the review queue. Approved videos go to the upload
queue (publish/queue.py).
"""
from __future__ import annotations

import json
import random
import shutil
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from synergia import demo, history
from synergia.brand.typography import strip_markup
from synergia.config import CFG

ENGINES = ("A", "B", "C", "D", "E")
NEEDS_CLAUDE = ("A", "B", "E")
DEFAULT_MIX = {"A": 2, "B": 2, "C": 5, "D": 3, "E": 2}
SPARE_CLIPS = 2

PENDING, RENDERING, REVIEW, APPROVED, DROPPED, FAILED, SCHEDULED = (
    "pending", "rendering", "review", "approved", "dropped", "failed", "scheduled")
OPEN_STATES = (PENDING, RENDERING, REVIEW, APPROVED, FAILED)

_lock = threading.RLock()


def _cfg(name: str, default):
    return getattr(getattr(CFG, "autopilot", None), name, default)


def default_count() -> int:
    return int(_cfg("count", 14))


def default_mix() -> dict[str, int]:
    m = _cfg("mix", None)
    m = vars(m) if m is not None and not isinstance(m, dict) else (m or DEFAULT_MIX)
    return {k: int(m.get(k, 0)) for k in ENGINES}


# ================================================================ planning

def scale_mix(mix: dict[str, int], count: int) -> dict[str, int]:
    """Scale engine weights to exactly `count` videos (largest remainder)."""
    mix = {k: max(0, int(v)) for k, v in mix.items() if int(v) > 0}
    total = sum(mix.values())
    if not total or count <= 0:
        return {}
    if total == count:
        return dict(mix)
    raw = {k: v * count / total for k, v in mix.items()}
    out = {k: int(r) for k, r in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:count - sum(out.values())]:
        out[k] += 1
    return {k: v for k, v in out.items() if v}


def plan_jobs(count: int, mix: dict[str, int], rng: random.Random | None = None) -> list[dict]:
    """Interleaved job list: [{'engine': 'C'}, {'engine': 'E', 'mode': 'pick'}, ...].

    Each engine's videos are spaced evenly across the batch (with a little jitter), then
    neighbours are swapped so the same engine never appears twice in a row unless nothing else is
    left. E alternates between the checklist and pick-one formats.
    """
    rng = rng or random.Random()
    counts_ = scale_mix(mix, count)
    total = sum(counts_.values())
    # Ideal (evenly spaced, slightly jittered) positions of each engine's videos.
    ideal = {eng: [(i + rng.uniform(0.25, 0.75)) * total / k for i in range(k)]
             for eng, k in counts_.items()}
    order: list[str] = []
    prev = None
    while any(ideal.values()):
        left = sum(len(q) for q in ideal.values())
        # An engine holding more than half the remaining slots must go now, or repeats become unavoidable.
        forced = [e for e, q in ideal.items() if q and e != prev and 2 * len(q) > left]
        options = forced or [e for e, q in ideal.items() if q and e != prev] or [e for e, q in ideal.items() if q]
        eng = min(options, key=lambda e: ideal[e][0])
        ideal[eng].pop(0)
        order.append(eng)
        prev = eng
    e_modes = ["checklist", "pick"]
    rng.shuffle(e_modes)
    jobs, n_e = [], 0
    for eng in order:
        job = {"engine": eng}
        if eng == "E":
            job["mode"] = e_modes[n_e % 2]
            n_e += 1
        jobs.append(job)
    return jobs


# ================================================================ batch storage

def _dir() -> Path:
    d = CFG.output.cache_dir / "autopilot"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file(batch_id: str) -> Path:
    return _dir() / f"{batch_id}.json"


def load(batch_id: str) -> dict:
    with _lock:
        return json.loads(_file(batch_id).read_text(encoding="utf-8"))


def _save(batch: dict) -> None:
    with _lock:
        _file(batch["id"]).write_text(json.dumps(batch, indent=1, ensure_ascii=False), encoding="utf-8")


def update(batch_id: str, fn: Callable[[dict], None]) -> dict:
    """Load, change and save a batch atomically (the render thread and the GUI both write)."""
    with _lock:
        b = load(batch_id)
        fn(b)
        _save(b)
        return b


def item(batch: dict, item_id: int) -> dict:
    return next(i for i in batch["items"] if i["id"] == item_id)


def set_item(batch_id: str, item_id: int, **fields) -> dict:
    return update(batch_id, lambda b: item(b, item_id).update(fields))


def current() -> dict | None:
    """The newest batch that still has something to review or schedule."""
    for p in sorted(_dir().glob("*.json"), reverse=True):
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if b.get("closed"):
            continue
        if any(i["status"] in OPEN_STATES for i in b.get("items", [])):
            return b
    return None


def close(batch_id: str) -> None:
    update(batch_id, lambda b: b.__setitem__("closed", True))


def counts(batch: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in batch["items"]:
        out[i["status"]] = out.get(i["status"], 0) + 1
    return out


# ================================================================ progress (shared with the GUI)

class Progress:
    def __init__(self) -> None:
        self.running = False
        self.batch_id = ""
        self.label = ""
        self.done = 0
        self.total = 0
        self.log: list[str] = []
        self.cancel = False
        self.started = 0.0

    def say(self, msg: str) -> None:
        self.label = msg
        self.log.append(f"{datetime.now():%H:%M:%S}  {msg}")
        del self.log[:-80]
        print(f"[autopilot] {msg}")


PROGRESS = Progress()


def running() -> bool:
    return PROGRESS.running


# ================================================================ Claude

class ClaudeDown(RuntimeError):
    """Claude can't be used for the rest of this batch (not set up, or the usage limit was hit)."""


def claude_ready() -> bool:
    from synergia.llm import claude_code
    return claude_code.available()


def _ask(prompt: str, validator, state: dict) -> dict:
    """Ask Claude through Claude Code; never falls back to the clipboard."""
    from synergia.llm import claude_code
    if state.get("claude_down"):
        raise ClaudeDown(state["claude_down"])
    if not claude_code.available():
        state["claude_down"] = ("Claude Code isn't available (set [claude] mode = \"code\" and install "
                                "Claude Code), so this needs a manual run on the Create page.")
        raise ClaudeDown(state["claude_down"])
    try:
        return claude_code.ask_auto(prompt, validator)
    except claude_code.ClaudeCodeError as e:
        msg = str(e)
        if "limit" in msg.lower() or "signed in" in msg.lower() or "isn't installed" in msg:
            state["claude_down"] = msg
        raise


def _topics_check(n: int):
    def check(d: dict) -> list[str]:
        t = d.get("topics")
        clean = [strip_markup(str(x)).strip() for x in t] if isinstance(t, list) else []
        clean = [x for x in clean if x]
        if len(clean) < n:
            return [f'"topics" must be a list of at least {n} short strings']
        d["topics"] = clean
        return []
    return check


def _topics(kind: str, n: int, state: dict, is_demo: bool) -> list[str]:
    """n fresh topics: kind is 'A', 'B', 'E:checklist' or 'E:pick'."""
    from synergia.llm.prompts import ideas_prompt, topics_prompt

    if is_demo:
        sample = {"A": demo.PSYCHOLOGY["concept"], "B": strip_markup(demo.LISTICLE["cover_title"]),
                  "E:checklist": strip_markup(demo.CHECKLIST["cover_title"]),
                  "E:pick": strip_markup(demo.PICK["cover_title"])}[kind]
        return [sample] * n
    if kind == "A":
        prompt = ideas_prompt("concepts", n, history.recent("psychology.concepts"))
    elif kind == "B":
        prompt = ideas_prompt("hooks", n, history.recent("listicle.hooks"))
    else:
        prompt = topics_prompt(kind.split(":")[1], history.recent("identity.topics"))
    got = _ask(prompt, _topics_check(min(n, 5)), state)["topics"]
    # Never reuse a topic inside one batch either.
    seen, out = set(), []
    for t in got:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    while len(out) < n:   # Claude gave too few: reuse the list rather than fail
        out.append(out[len(out) % max(1, len(seen))])
    return out[:n]


# ================================================================ Engine C: episode + clips

def watched_channels() -> list[str]:
    p = CFG.output.cache_dir / "autopilot_settings.json"
    try:
        chans = json.loads(p.read_text(encoding="utf-8")).get("channels")
        if isinstance(chans, list):
            return [str(c).strip() for c in chans if str(c).strip()]
    except (OSError, ValueError):
        pass
    return [str(c).strip() for c in _cfg("channels", []) if str(c).strip()]


def save_channels(channels: list[str]) -> None:
    p = CFG.output.cache_dir / "autopilot_settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"channels": [c.strip() for c in channels if c.strip()]}, indent=1,
                            ensure_ascii=False), encoding="utf-8")


def find_episode(url: str, channels: list[str], lister: Callable | None = None,
                 log: Callable[[str], None] = print) -> tuple[dict | None, str]:
    """-> (episode {'url', 'title', 'channel', 'id'}, reason if none).

    A pasted URL always wins. Otherwise the channels are tried least-recently-used first, and each
    one's newest upload that is long enough and hasn't been clipped yet is taken.
    """
    from synergia.engines.podcast.source import latest_episodes, video_id

    if url.strip():
        return {"url": url.strip(), "id": video_id(url), "title": "", "channel": ""}, ""
    if not channels:
        return None, "no episode URL was given and there are no watched channels"
    lister = lister or latest_episodes
    used = set(history.recent("podcast.episodes"))
    recent_ch = history.recent("podcast.channels")
    order = sorted(channels, key=lambda c: (c in recent_ch, -recent_ch.index(c) if c in recent_ch else 0))
    min_s = float(_cfg("min_episode_minutes", 20)) * 60
    for ch in order:
        try:
            eps = lister(ch)
        except Exception as e:  # noqa: BLE001 — try the next channel
            log(f"Couldn't list {ch}: {e}")
            continue
        for ep in eps:
            if ep["id"] in used or (ep.get("duration") and ep["duration"] < min_s):
                continue
            return {**ep, "watched": ch}, ""
    return None, "every watched channel's recent episodes have already been clipped (or are too short)"


def _non_overlapping(cands: list) -> list:
    out = []
    for c in cands:
        if all(c.end <= p.start or c.start >= p.end for p in out):
            out.append(c)
    return out


_c_cache: dict[str, tuple] = {}   # episode url -> (src, name, credit dict, info, transcript)


def _c_context(url: str, say: Callable[[str], None]) -> tuple:
    if url not in _c_cache:
        from synergia.engines.podcast import engine
        say("Engine C: fetching the episode…")
        src, name, credit, info = engine.load_source(url)
        say(f"Engine C: transcribing “{name}” (cached next time)…")
        tr = engine.full_transcript(src, info)
        _c_cache[url] = (src, name, credit, info, tr)
    return _c_cache[url]


def _prepare_c(batch_id: str, episode: dict, n: int, state: dict, is_demo: bool) -> None:
    """Transcribe the episode and store n + spares snapped clip candidates in the batch."""
    from synergia.engines.podcast import engine
    from synergia.engines.podcast import highlights as hl

    src, name, credit, info, tr = _c_context(episode["url"], PROGRESS.say)
    want = n + SPARE_CLIPS
    data = None
    if not is_demo:
        PROGRESS.say(f"Engine C: Claude is picking the best {want} moments…")
        try:
            data = _ask(hl.claude_prompt(tr, name, want), hl.make_validator(info["duration"]), state)
        except Exception as e:  # noqa: BLE001 — the offline heuristic still works
            PROGRESS.say(f"Engine C: Claude couldn't pick ({e}); using the offline heuristic.")
    cands = _non_overlapping(hl.from_claude(data)) if data else []
    if len(cands) < want:   # top up with heuristic picks that don't overlap Claude's
        cands = _non_overlapping(cands + hl.heuristic(tr, k=want + 5))[:want]
    if not cands:
        raise RuntimeError("No clip candidates were found in this episode.")
    for c in cands:
        c.start, c.end = hl.snap(c.start, c.end, tr["words"])
        c.end = min(c.end, info["duration"])
    credit_str = engine.credit_text(credit)

    def put(b: dict) -> None:
        b["c"] = {"url": episode["url"], "name": name, "credit": credit_str,
                  "cands": [asdict(c) for c in cands], "next": 0}
    update(batch_id, put)
    history.remember("podcast.episodes", [episode.get("id") or episode["url"]])
    if episode.get("watched"):
        history.remember("podcast.channels", [episode["watched"]])


def _next_c_candidate(batch_id: str):
    """Hand out the next unused candidate (or None when they're all used)."""
    from synergia.engines.podcast import highlights as hl
    got: dict = {}

    def take(b: dict) -> None:
        c = b.get("c") or {}
        if c.get("next", 0) < len(c.get("cands", [])):
            got["cand"] = hl.Candidate(**c["cands"][c["next"]])
            got["index"] = c["next"]
            c["next"] += 1
    update(batch_id, take)
    return got.get("cand"), got.get("index")


def _render_c(batch_id: str, debug: bool) -> tuple[Path, str]:
    from synergia.engines.podcast import engine
    b = load(batch_id)
    c = b.get("c")
    if not c:
        raise RuntimeError("The episode for Engine C isn't ready.")
    cand, idx = _next_c_candidate(batch_id)
    if cand is None:
        raise RuntimeError("No spare clips left from this episode.")
    src, name, _credit, info, tr = _c_context(c["url"], PROGRESS.say)
    out = engine.render_picked(src, info, name, [cand], tr["words"], None, debug, c["credit"])
    return out, cand.title or f"clip {idx + 1}"


# ================================================================ one item

def _script_engine(job: dict):
    from synergia.engines import identity, listicle, psychology
    if job["engine"] == "A":
        return psychology, psychology.produce
    if job["engine"] == "B":
        return listicle, listicle.produce
    if job.get("mode") == "pick":
        return identity.Pick, identity.produce_pick
    return identity.Checklist, identity.produce_checklist


def _demo_script(job: dict) -> dict:
    if job["engine"] == "A":
        return json.loads(json.dumps(demo.PSYCHOLOGY))
    if job["engine"] == "B":
        return json.loads(json.dumps(demo.LISTICLE))
    return json.loads(json.dumps(demo.PICK if job.get("mode") == "pick" else demo.CHECKLIST))


def render_item(batch_id: str, it: dict, state: dict, is_demo: bool, debug: bool) -> Path:
    """Write (if needed) and render one item. Returns its run folder."""
    eng = it["engine"]
    if eng == "D":
        from synergia.engines import brain
        return brain.produce(debug=debug)
    if eng == "C":
        out, title = _render_c(batch_id, debug)
        set_item(batch_id, it["id"], topic=title)
        return out
    module, produce = _script_engine(it)
    if is_demo:
        data = _demo_script(it)
        module.validate(data)
    else:
        data = _ask(module.prompt(it["topic"]), module.validate, state)
    if eng == "E":
        data["topic"] = it["topic"]
    return produce(data, debug=debug)


def _label(it: dict) -> str:
    name = {"A": "Psychology Explainer", "B": "Fact Slideshow", "C": "Podcast clip", "D": "Brain Test",
            "E": "Which One Are You"}[it["engine"]]
    return f"{name}: {it['topic']}" if it.get("topic") else name


# ================================================================ run a batch

def start(count: int, mix: dict[str, int], episode_url: str = "", is_demo: bool = False,
          debug: bool = False) -> str:
    """Plan a batch and render it in a background thread. Returns the batch id."""
    if PROGRESS.running:
        raise RuntimeError("Autopilot is already running.")
    jobs = plan_jobs(count, mix)
    if not jobs:
        raise ValueError("Choose at least one video.")
    batch_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    batch = {"id": batch_id, "created": datetime.now().isoformat(timespec="seconds"),
             "demo": is_demo, "episode_url": episode_url.strip(), "mix": mix, "notes": [],
             "items": [{"id": n, **j, "topic": "", "folder": "", "status": PENDING, "error": ""}
                       for n, j in enumerate(jobs, 1)]}
    _save(batch)
    p = PROGRESS
    p.running, p.batch_id, p.cancel, p.done, p.total = True, batch_id, False, 0, len(jobs)
    p.log, p.started = [], time.monotonic()
    threading.Thread(target=_run, args=(batch_id, is_demo, debug), daemon=True,
                     name="synergia-autopilot").start()
    return batch_id


def _note(batch_id: str, msg: str) -> None:
    PROGRESS.say(msg)
    update(batch_id, lambda b: b["notes"].append(msg))


def _replan_without_c(batch_id: str, reason: str) -> None:
    """No episode: give the C slots to the other engines (keeping their proportions)."""
    b = load(batch_id)
    mix = {k: v for k, v in (b.get("mix") or default_mix()).items() if k != "C" and v}
    if not claude_ready() and not b.get("demo"):
        mix = {"D": 1}
    jobs = plan_jobs(len(b["items"]), mix or {"D": 1})

    def put(b: dict) -> None:
        b["items"] = [{"id": n, **j, "topic": "", "folder": "", "status": PENDING, "error": ""}
                      for n, j in enumerate(jobs, 1)]
        b["notes"].append(f"No podcast clips this time: {reason}. Their slots went to the other engines.")
    update(batch_id, put)
    PROGRESS.say(f"No podcast clips: {reason}.")


def _run(batch_id: str, is_demo: bool, debug: bool) -> None:
    p = PROGRESS
    state: dict = {}
    try:
        b = load(batch_id)
        # 1. Engine C needs an episode: without one, its slots go to the other engines.
        n_c = sum(1 for i in b["items"] if i["engine"] == "C")
        if n_c:
            p.say("Engine C: looking for an episode…")
            ep, why = find_episode(b.get("episode_url", ""), watched_channels(), log=p.say)
            if ep is None:
                _replan_without_c(batch_id, why)
            else:
                try:
                    _prepare_c(batch_id, ep, n_c, state, is_demo)
                except Exception as e:  # noqa: BLE001
                    _replan_without_c(batch_id, f"the episode couldn't be used ({e})")
        b = load(batch_id)
        p.total = len(b["items"])

        # 2. Topics, one Claude call per kind.
        kinds: dict[str, list[dict]] = {}
        for it in b["items"]:
            if it["engine"] in NEEDS_CLAUDE:
                kinds.setdefault(it["engine"] + (f":{it['mode']}" if it.get("mode") else ""), []).append(it)
        for kind, its in kinds.items():
            if p.cancel:
                break
            p.say(f"Asking Claude for {len(its)} fresh {kind} topic{'s' if len(its) > 1 else ''}…")
            try:
                topics = _topics(kind, len(its), state, is_demo)
            except Exception as e:  # noqa: BLE001 — these items fail, the rest go on
                for it in its:
                    set_item(batch_id, it["id"], status=FAILED, error=f"No topic: {e}")
                continue
            for it, t in zip(its, topics):
                set_item(batch_id, it["id"], topic=t)

        # 3. Scripts + renders, one item at a time.
        for it in load(batch_id)["items"]:
            if p.cancel:
                p.say("Stopped. The videos made so far are ready to review.")
                break
            if it["status"] != PENDING:
                p.done += 1
                continue
            p.say(f"{p.done + 1}/{p.total} · {_label(it)}")
            set_item(batch_id, it["id"], status=RENDERING)
            try:
                out = render_item(batch_id, it, state, is_demo, debug)
                topic = load(batch_id)["items"][it["id"] - 1].get("topic") or _title_of(out)
                set_item(batch_id, it["id"], status=REVIEW, folder=_rel(out), error="", topic=topic)
            except Exception as e:  # noqa: BLE001 — keep going with the next item
                set_item(batch_id, it["id"], status=FAILED, error=str(e) or type(e).__name__)
                p.say(f"✗ {_label(it)}: {e}")
                if debug:
                    traceback.print_exc()
            p.done += 1
        # Leftovers after a cancel go back to pending → shown as "not made".
        update(batch_id, lambda b: [i.update(status=FAILED, error="Stopped before it was made")
                                    for i in b["items"] if i["status"] in (PENDING, RENDERING)])
        c = counts(load(batch_id))
        p.say(f"Done: {c.get(REVIEW, 0)} ready to review"
              + (f", {c[FAILED]} failed" if c.get(FAILED) else "") + ".")
    except Exception as e:  # noqa: BLE001 — never kill the GUI
        p.say(f"Autopilot stopped with an error: {e}")
        traceback.print_exc()
    finally:
        p.running = False


def _title_of(out: Path) -> str:
    try:
        return strip_markup(json.loads((out / "script.json").read_text(encoding="utf-8")).get("title", ""))
    except (OSError, ValueError):
        return ""


def _rel(folder: Path) -> str:
    return Path(folder).resolve().relative_to(CFG.output.dir.resolve()).as_posix()


def folder_of(it: dict) -> Path | None:
    if not it.get("folder"):
        return None
    f = CFG.output.dir / it["folder"]
    return f if f.is_dir() else None


# ================================================================ review actions (called by the GUI)

def _discard(folder: Path | None) -> None:
    """Delete a replaced render, but never one that is on YouTube or waiting in the upload queue."""
    from synergia.publish import queue, read_ledger
    if folder and folder.is_dir() and not read_ledger(folder) and not queue.entry(folder):
        shutil.rmtree(folder, ignore_errors=True)


def regenerate(batch_id: str, item_id: int, debug: bool = False) -> dict:
    """Make this item again: a new script for the same topic (A/B/E), a new game (D) or the next
    spare moment (C). Runs in the caller's thread (the GUI uses a worker). Returns the item."""
    b = load(batch_id)
    it = item(b, item_id)
    old = folder_of(it)
    state: dict = {}
    if it["engine"] in NEEDS_CLAUDE and not it.get("topic"):
        kind = it["engine"] + (f":{it['mode']}" if it.get("mode") else "")
        set_item(batch_id, item_id, topic=_topics(kind, 1, state, b.get("demo", False))[0])
        it = item(load(batch_id), item_id)
    out = render_item(batch_id, it, state, b.get("demo", False), debug)
    _discard(old)
    extra = {"topic": _title_of(out)} if it["engine"] == "D" else {}
    return item(set_item(batch_id, item_id, status=REVIEW, folder=_rel(out), error="", **extra), item_id)


def spares_left(batch: dict) -> int:
    c = batch.get("c") or {}
    return max(0, len(c.get("cands", [])) - int(c.get("next", 0)))


def schedule_approved(batch_id: str) -> list[dict]:
    """Queue every approved item for upload (each gets the next free slot). Returns the new queue entries."""
    from synergia.publish import queue
    b = load(batch_id)
    approved = [i for i in b["items"] if i["status"] == APPROVED and folder_of(i)]
    added = queue.enqueue([folder_of(i) for i in approved])
    by_folder = {a["folder"]: a for a in added}

    def mark(b: dict) -> None:
        for i in b["items"]:
            if i["status"] == APPROVED and i.get("folder") in by_folder:
                i.update(status=SCHEDULED, publish_at=by_folder[i["folder"]]["publish_at"])
        if not any(i["status"] in (PENDING, RENDERING, REVIEW, APPROVED) for i in b["items"]):
            b["closed"] = True
    update(batch_id, mark)
    return added
