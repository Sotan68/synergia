"""The user's profile (profile.toml): read, write, draft with Claude, and the original Synergia profile.

profile.toml is merged over config.toml by synergia.config. The setup wizard (gui/setup.py and
cli.setup_wizard) builds it from the user's answers plus a Claude draft of the niche-specific
writing; `synergia_profile()` is the original psychology setup, written for installs that
predate profiles so they keep behaving exactly as before.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# synergia.config imports this module while it loads (one-time migration), so config is
# imported inside the functions that need it.

ENGINES = ("A", "B", "C", "D", "E")
GENERIC_NAMES = {"A": "Explainer", "B": "Slideshow", "C": "Podcast Clipper", "D": "Brain Test",
                 "E": "Which One Are You"}


# ---------------------------------------------------------------- TOML writing
def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)     # JSON string escapes are valid TOML


def _key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def dumps(data: dict, _prefix: str = "") -> str:
    """Minimal TOML writer for the profile: scalars, lists of scalars and nested tables."""
    lines = [f"{_key(k)} = {_value(v)}" for k, v in data.items() if not isinstance(v, dict)]
    out = "\n".join(lines)
    for k, v in data.items():
        if isinstance(v, dict):
            name = f"{_prefix}.{_key(k)}" if _prefix else _key(k)
            body = dumps(v, name)
            out += ("\n\n" if out else "") + f"[{name}]" + (("\n" + body) if body else "")
    return out.strip("\n")


def save(profile: dict, path: Path | None = None) -> Path:
    from synergia.config import profile_path

    path = path or profile_path()
    header = ("# Your Synergia setup, written by the setup wizard / Settings page.\n"
              "# Merged over config.toml; edit here or re-run the wizard from Settings.\n\n")
    path.write_text(header + dumps(profile) + "\n", encoding="utf-8")
    return path


def load(path: Path | None = None) -> dict:
    from synergia.config import read_profile

    return read_profile(path)


# ---------------------------------------------------------------- the original Synergia setup
def synergia_profile() -> dict:
    """Today's SYNERGIA psychology brand, so existing installs keep the same prompts and look."""
    return {
        "brand": {"name": "SYNERGIA"},
        "theme": {"preset": "synergia"},
        "voice": {
            "niche": "human psychology, life advice and real experiences",
            "niche_short": "psychology, life advice, real experiences",
            "clip_payoff": "psychology, life advice or a raw human experience",
            "audience": "",
            "tone": 'minimalist, direct, second-person ("you"), slightly provocative, emotionally sharp',
            "topic_scope": ["psychology", "relationships", "habits", "work", "friendship",
                            "self-image"],
            "concept_kind": ("psychology concepts for 10-second explainers: named effects, biases, "
                             "laws or phenomena"),
            "concept_examples": ["The Spotlight Effect", "The Zeigarnik Effect"],
            "carousel_kind": "life-advice",
            "hook_examples": ["5 things people regret not doing after 25",
                              "5 signs someone truly respects you"],
            "examples": {
                "concept": "The Spotlight Effect",
                "hook": "5 things people regret not doing after 25",
                "checklist_cover": "signs you **overthink** everything",
                "pick_cover": "Pick a **door** and see what it says about you",
                "checklist_topic": "signs you're a high-functioning overthinker",
                "pick_topic": "pick a door to reveal your hidden strength",
            },
        },
        "engine_a": {
            "wording": {
                "kind": "psychology",
                "intro_label": "Explained in 10 seconds",
                "step_labels": ["The mirror", "The mechanism", "The shift"],
                "title_template": "{concept}, explained in 10 seconds",
                "hook_line": 'the "why it matters" line that follows "<Concept> explained in 10 seconds:"',
                "gotcha": '"The Mirror": a hyper-relatable scenario that makes the viewer feel caught',
                "mechanism": "how the brain tricks them, in plain language",
                "shift": "one punchy concluding sentence that reframes everything",
            },
            "example": {
                "concept": "The Spotlight Effect",
                "hook_line": "Why you **overthink** everything you do.",
                "gotcha": ("Think about that slightly awkward thing you said three days ago. You've "
                           "replayed it 20 times. Meanwhile, the person you said it to **forgot it** "
                           "10 seconds later."),
                "mechanism": ("Because you are the center of your own universe, your brain assumes "
                              "everyone is **watching and judging** you as closely as you watch "
                              "yourself."),
                "shift": ("Nobody is keeping score of your mistakes — they're too busy worrying "
                          "about **how they look to you**."),
            },
        },
        "hashtags": {
            "A": ["#psychology"], "B": ["#lifeadvice"], "C": ["#podcast"],
            "D": ["#braintest", "#brainteaser", "#iqtest", "#puzzle", "#challenge", "#psychology",
                  "#focus", "#memorytest", "#mindgames"],
            "E_checklist": ["#psychology"], "E_pick": ["#personalitytest"],
        },
        "engines": {
            "enabled": list(ENGINES),
            "names": {"A": "Psychology Explainer", "B": "Random Fact Slideshow",
                      "C": "Podcast Clipper", "D": "Brain Test", "E": "Which One Are You"},
        },
        "engine_c": {
            "keywords": ["brain", "psycholog", "fear", "anxiety", "love", "relationship",
                         "happiness", "happy", "success", "fail", "confidence", "habit",
                         "discipline", "money", "purpose", "meaning", "lonely", "trauma", "dopamine",
                         "emotion", "ego", "identity", "therapy", "parents", "childhood", "death",
                         "life"],
        },
    }


def create(prof: dict) -> str:
    """Save a new profile under profiles/<name>/ (a free folder name from the brand name) and
    make it the active one. Returns the folder name."""
    from synergia.config import PROFILES, list_profiles, set_active, slugify

    base = slugify((prof.get("brand") or {}).get("name") or "profile")
    taken, name, n = set(list_profiles()), base, 2
    while name in taken or (PROFILES / name).exists():
        name, n = f"{base}-{n}", n + 1
    (PROFILES / name).mkdir(parents=True, exist_ok=True)
    save(prof, PROFILES / name / "profile.toml")
    set_active(name)
    return name


# ---------------------------------------------------------------- Claude draft for a new niche
def draft_prompt(name: str, description: str, audience: str = "") -> str:
    aud = f'\nTheir audience: "{audience}"' if audience.strip() else ""
    return f"""You are setting up an automated short-form video brand (TikTok, Reels, YouTube Shorts).
Brand name: "{name}"
What the creator wants to post about: "{description}"{aud}

The tool has these formats:
- A "explainer": a 10-second video in 4 steps (hook_line, then 3 slides), about one named concept.
- B "carousel": a hook + 5 points.
- C "podcast clips": the best moments cut from long podcast episodes.
- D "brain test": generic mini-games (no writing needed).
- E "which one are you": "How many apply to you?" checklists and "Pick one" personality reveals.

TASK: Fill in the brand settings below for THIS niche. Write like a real person, not an ad:
plain words, no buzzwords ("unlock", "elevate", "journey", "game-changer"), no emojis.

Field notes:
- niche: what the brand is about, as it would end the sentence "a short-form brand about ..." (max 12 words).
- niche_short: 3-5 comma-separated words for the niche.
- clip_payoff: what a great podcast clip delivers for this audience, e.g. "a money lesson or a raw founder story".
- tone: 6-14 words describing the writing voice; keep it second person ("you").
- topic_scope: 5-8 short subject areas the brand covers.
- concept_kind: what Engine A explains, as "<kind> for 10-second explainers: <what they are>".
- concept_examples: 3 real, searchable concept names from the niche.
- carousel_kind: 1-3 words, as in "hooks for 5-point <carousel_kind> carousels".
- hook_examples: 3 carousel hooks, each starting with "5 ", max 12 words.
- examples.checklist_cover: like "signs you **overthink** everything" (no number; one **highlighted** word).
- examples.pick_cover: like "Pick a **door** and see what it says about you".
- examples.checklist_topic / pick_topic: one topic each for format E, max 10 words.
- engine_a.kind: 1-2 words for the niche ("psychology", "money", "fitness").
- engine_a.step_labels: names of the 3 slides after the hook, 1-3 words each, e.g. ["The mirror", "The mechanism", "The shift"].
- engine_a.gotcha / mechanism / shift: one line each telling a writer what that slide must do, matching its label.
- hashtags: for each format, 3-6 hashtags, most important first.
- keywords: 15-25 lowercase words that signal an on-topic podcast moment (word stems are fine).
- engines: which formats suit this niche, from ["A","B","C","D","E"] (D is always fine).

Reply with ONE ```json code block and nothing else. Valid JSON only.
```json
{{
  "niche": "...", "niche_short": "...", "clip_payoff": "...", "tone": "...",
  "topic_scope": ["..."], "concept_kind": "...", "concept_examples": ["...", "...", "..."],
  "carousel_kind": "...", "hook_examples": ["5 ...", "5 ...", "5 ..."],
  "examples": {{"checklist_cover": "...", "pick_cover": "...", "checklist_topic": "...", "pick_topic": "..."}},
  "engine_a": {{"kind": "...", "step_labels": ["...", "...", "..."], "gotcha": "...", "mechanism": "...", "shift": "..."}},
  "hashtags": {{"A": ["#..."], "B": ["#..."], "C": ["#..."], "E_checklist": ["#..."], "E_pick": ["#..."]}},
  "keywords": ["..."],
  "engines": ["A", "B", "D", "E"]
}}
```"""


def _str(d: dict, key: str, errors: list[str], where: str = "", max_words: int = 0) -> None:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        errors.append(f'"{where}{key}" must be a non-empty string')
    elif max_words and len(v.split()) > max_words:
        errors.append(f'"{where}{key}" must be at most {max_words} words')


def _list(d: dict, key: str, errors: list[str], lo: int, hi: int, where: str = "") -> None:
    v = d.get(key)
    if not isinstance(v, list) or not lo <= len(v) <= hi or not all(isinstance(x, str) and x.strip() for x in v):
        errors.append(f'"{where}{key}" must be a list of {lo}-{hi} non-empty strings')


def validate_draft(data: dict) -> list[str]:
    errors: list[str] = []
    for k, w in (("niche", 16), ("niche_short", 8), ("clip_payoff", 14), ("tone", 18),
                 ("concept_kind", 22), ("carousel_kind", 4)):
        _str(data, k, errors, max_words=w)
    _list(data, "topic_scope", errors, 3, 10)
    _list(data, "concept_examples", errors, 1, 5)
    _list(data, "hook_examples", errors, 1, 5)
    _list(data, "keywords", errors, 8, 40)
    ex = data.get("examples") if isinstance(data.get("examples"), dict) else {}
    for k in ("checklist_cover", "pick_cover", "checklist_topic", "pick_topic"):
        _str(ex, k, errors, "examples.", 16)
    ea = data.get("engine_a") if isinstance(data.get("engine_a"), dict) else {}
    for k in ("kind", "gotcha", "mechanism", "shift"):
        _str(ea, k, errors, "engine_a.", 30)
    _list(ea, "step_labels", errors, 3, 3, "engine_a.")
    tags = data.get("hashtags") if isinstance(data.get("hashtags"), dict) else {}
    for k in ("A", "B", "C", "E_checklist", "E_pick"):
        _list(tags, k, errors, 1, 8, "hashtags.")
    eng = data.get("engines")
    if not isinstance(eng, list) or not eng or any(e not in ENGINES for e in eng):
        errors.append('"engines" must be a non-empty list of letters from A, B, C, D, E')
    if not errors:   # normalise
        for k in ("A", "B", "C", "E_checklist", "E_pick"):
            tags[k] = ["#" + re.sub(r"\s+", "", t).lstrip("#") for t in tags[k]]
        data["keywords"] = [k.lower().strip() for k in data["keywords"]]
        data["engines"] = [e for e in ENGINES if e in eng]
    return errors


def draft_from_config(cfg) -> dict:
    """The current settings in draft form, to prefill the Settings page."""
    v, w = cfg.voice, cfg.engine_a.wording
    ex = v.examples
    return {
        "niche": v.niche, "niche_short": v.niche_short, "clip_payoff": v.clip_payoff,
        "tone": v.tone, "topic_scope": list(v.topic_scope), "concept_kind": v.concept_kind,
        "concept_examples": list(v.concept_examples) or [ex.concept],
        "carousel_kind": v.carousel_kind, "hook_examples": list(v.hook_examples) or [ex.hook],
        "examples": {k: getattr(ex, k) for k in ("checklist_cover", "pick_cover",
                                                  "checklist_topic", "pick_topic")},
        "engine_a": {"kind": w.kind, "step_labels": list(w.step_labels), "gotcha": w.gotcha,
                     "mechanism": w.mechanism, "shift": w.shift},
        "hashtags": {k: list(getattr(cfg.hashtags, k, []) or [])
                     for k in ("A", "B", "C", "E_checklist", "E_pick")},
        "keywords": list(cfg.engine_c.keywords),
        "engines": list(cfg.engines.enabled),
    }


def from_draft(name: str, draft: dict, theme: str, engines: list[str], audience: str = "",
               logo: str = "", names: dict | None = None) -> dict:
    """A complete profile from the wizard's answers and Claude's (reviewed) draft.
    `names`: engine display names to keep (default: the generic ones)."""
    ex, ea = draft["examples"], draft["engine_a"]
    kind = ea["kind"].strip()
    concepts = draft["concept_examples"]
    return {
        "brand": {"name": name.strip(), **({"logo": logo} if logo else {})},
        "theme": {"preset": theme},
        "voice": {
            "niche": draft["niche"], "niche_short": draft["niche_short"],
            "clip_payoff": draft["clip_payoff"], "audience": audience.strip(),
            "tone": draft["tone"], "topic_scope": draft["topic_scope"],
            "concept_kind": draft["concept_kind"], "concept_examples": concepts,
            "carousel_kind": draft["carousel_kind"], "hook_examples": draft["hook_examples"],
            "examples": {"concept": concepts[0], "hook": draft["hook_examples"][0], **ex},
        },
        "engine_a": {"wording": {
            "kind": kind, "step_labels": ea["step_labels"],
            "gotcha": ea["gotcha"], "mechanism": ea["mechanism"], "shift": ea["shift"],
        }},
        "hashtags": {**draft["hashtags"],
                     "D": ["#braintest", "#brainteaser", "#iqtest", "#puzzle", "#challenge",
                           "#focus", "#memorytest", "#mindgames"]},
        "engines": {"enabled": [e for e in ENGINES if e in engines],
                    "names": {**GENERIC_NAMES, **(names or {})}},
        "engine_c": {"keywords": draft["keywords"]},
    }
