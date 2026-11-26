"""Profiles: config layering, themes, the original Synergia setup, the TOML writer, Claude drafts.

Run: .venv\\Scripts\\python -m pytest tests
"""
from __future__ import annotations

import tomllib

import pytest

from synergia import config, profile
from synergia.brand import themes
from synergia.llm import prompts

# The brand voice exactly as it was hard-coded before profiles existed.
OLD_BRAND_VOICE = """You are the head writer for SYNERGIA, a faceless short-form brand (TikTok, Reels, Shorts)
about human psychology, life advice and real experiences.
Voice: minimalist, direct, second-person ("you"), slightly provocative, emotionally sharp.
No fluff, no emojis, no hashtags inside the text, no clichés like "In today's world".
Every sentence must be short and readable on a phone screen in under 3 seconds."""

DRAFT = {
    "niche": "quick home workouts and simple food tips for busy dads",
    "niche_short": "dad fitness, home workouts, food",
    "clip_payoff": "a training tip you can try tonight",
    "tone": "talks to you like a friend who also has kids and no time",
    "topic_scope": ["home workouts", "simple meals", "sleep and energy"],
    "concept_kind": "fitness ideas for 10-second explainers: training principles with a real name",
    "concept_examples": ["Progressive overload", "Time under tension"],
    "carousel_kind": "dad fitness",
    "hook_examples": ["5 home exercises you can do while the kids nap"],
    "examples": {"checklist_cover": "signs you're a **tired** dad", "pick_cover": "Pick a **breakfast**",
                 "checklist_topic": "habits that keep dads out of shape",
                 "pick_topic": "which workout fits your schedule"},
    "engine_a": {"kind": "fitness", "step_labels": ["The mistake", "Why it happens", "The fix"],
                 "gotcha": "a habit dads recognise", "mechanism": "what happens in the body",
                 "shift": "one small change for this week"},
    "hashtags": {"A": ["dadfitness", "#homeworkout"], "B": ["#fitdad"], "C": ["#fitnesspodcast"],
                 "E_checklist": ["#dadlife"], "E_pick": ["#pickone"]},
    "keywords": ["Workout", "squat", "protein", "sleep", "dad", "habit", "meal", "strength"],
    "engines": ["E", "A", "D"],
}


def cfg_with(tmp_path, prof: dict):
    path = tmp_path / "profile.toml"
    profile.save(prof, path)
    return config.load(profile_file=path)


# ---------------------------------------------------------------- layering
def test_no_profile_means_not_configured(tmp_path):
    cfg = config.load(profile_file=tmp_path / "missing.toml")
    assert cfg.configured is False
    assert cfg.engines.names.A == "Explainer"            # generic default


def test_profile_overrides_defaults_and_theme(tmp_path):
    cfg = cfg_with(tmp_path, {"brand": {"name": "X"}, "theme": {"preset": "sunset"},
                              "paper": {"accent": "#123456"}})
    assert cfg.configured is True
    assert cfg.brand.name == "X"
    assert cfg.paper.accent == "#123456"                  # profile beats the preset
    assert cfg.paper.ink == themes.THEMES["sunset"]["paper"]["ink"]   # preset beats config.toml
    assert cfg.paper.grain > 0                            # untouched config.toml value


def test_logo_path_resolved(tmp_path):
    cfg = cfg_with(tmp_path, {"brand": {"name": "X", "logo": "assets/user/logo.png"}})
    assert cfg.brand.logo == config.ROOT / "assets/user/logo.png"
    assert cfg_with(tmp_path, {"brand": {"name": "X"}}).brand.logo is None


@pytest.mark.parametrize("name", list(themes.THEMES))
def test_every_theme_is_complete(name):
    t = themes.expand(name)
    assert {"background", "ink", "soft", "accent", "accent2"} <= set(t["paper"])
    assert {"style", "surface", "text", "muted", "accent", "accent2"} <= set(t["quiz"])
    assert {"serif", "serif_italic", "paragraph", "quiz_heavy", "quiz_medium"} <= set(t["fonts"])
    assert len(t["brand"]["mark_colors"]) == 2


# ---------------------------------------------------------------- the original Synergia setup
@pytest.fixture
def synergia_cfg(tmp_path, monkeypatch):
    cfg = cfg_with(tmp_path, profile.synergia_profile())
    monkeypatch.setattr(prompts, "CFG", cfg)
    return cfg


def test_synergia_profile_keeps_the_old_prompts(synergia_cfg):
    assert prompts.brand_voice() == OLD_BRAND_VOICE
    a = prompts.psychology_prompt("The Halo Effect")
    assert 'TASK: Write a 10-second psychology explainer about: "The Halo Effect"' in a
    assert '2. gotcha — "The Mirror": a hyper-relatable scenario that makes the viewer feel caught' in a
    assert 'TONE REFERENCE (concept "The Spotlight Effect"):' in a
    assert '"hashtags": ["#psychology", "...", "5-8 relevant hashtags"]' in a
    c = prompts.highlights_prompt("00:01 hi", 20, 55)
    assert "video editor for SYNERGIA (psychology, life advice, real experiences)" in c
    assert "delivers psychology, life advice or a raw human experience." in c
    t = prompts.topics_prompt("checklist", [])
    assert "about psychology, relationships, habits, work, friendship, self-image - things" in t
    assert '"signs you\'re a high-functioning overthinker"' in t
    ideas = prompts.ideas_prompt("concepts", 10, [])
    assert '(e.g. "The Spotlight Effect", "The Zeigarnik Effect")' in ideas


def test_synergia_profile_keeps_names_and_look(synergia_cfg):
    assert synergia_cfg.engines.names.A == "Psychology Explainer"
    assert synergia_cfg.engine_a.wording.step_labels == ["The mirror", "The mechanism", "The shift"]
    assert synergia_cfg.quiz.muted == "#6A6E96" and synergia_cfg.paper.soft == "#585C84"
    assert synergia_cfg.brand.mark_colors == ["#5B9CFF", "#A78BFA"]


# ---------------------------------------------------------------- writer + drafts
def test_dumps_round_trips():
    prof = profile.synergia_profile()
    assert tomllib.loads(profile.dumps(prof)) == prof


def test_validate_draft_normalises():
    d = {**DRAFT, "hashtags": dict(DRAFT["hashtags"])}
    assert profile.validate_draft(d) == []
    assert d["hashtags"]["A"] == ["#dadfitness", "#homeworkout"]
    assert d["keywords"][0] == "workout"
    assert d["engines"] == ["A", "D", "E"]


def test_validate_draft_rejects_gaps():
    bad = {**DRAFT, "engine_a": {**DRAFT["engine_a"], "step_labels": ["only one"]}, "niche": ""}
    errors = profile.validate_draft(bad)
    assert any("step_labels" in e for e in errors) and any('"niche"' in e for e in errors)


def test_from_draft_drives_prompts(tmp_path, monkeypatch):
    d = {**DRAFT, "hashtags": dict(DRAFT["hashtags"])}
    profile.validate_draft(d)
    cfg = cfg_with(tmp_path, profile.from_draft("FitDad Daily", d, "forest", ["D", "A"]))
    monkeypatch.setattr(prompts, "CFG", cfg)
    assert cfg.engines.enabled == ["A", "D"]
    assert cfg.engines.names.A == "Explainer"
    voice = prompts.brand_voice()
    assert "head writer for FitDad Daily" in voice and "about quick home workouts" in voice
    a = prompts.psychology_prompt("Progressive overload")
    assert "Write a 10-second fitness explainer" in a and "TONE REFERENCE" not in a
    assert '"hashtags": ["#dadfitness", "...", "5-8 relevant hashtags"]' in a


@pytest.mark.parametrize("name", list(themes.THEMES))
def test_every_theme_has_a_layout_and_numeral(name):
    t = themes.expand(name)
    assert t["layout"]["bg"] in ("paper", "grid", "notebook", "gradient", "flat")
    from synergia.brand.layouts import BLUEPRINTS
    assert t["layout"]["blueprint"] in ("editorial", *BLUEPRINTS)
    assert t["layout"]["align"] in ("left", "center")
    assert t["layout"]["highlight"] in ("italic", "color", "marker", "underline")
    assert t["layout"]["header"] in ("rule", "pill", "plain")
    assert t["quiz"]["style"] in ("sheet", "grid", "cobalt", "plain")
    assert "numeral" in t["fonts"]


def test_old_theme_names_still_load():
    assert themes.expand("grid") == themes.expand("notebook")


# ---------------------------------------------------------------- several profiles
@pytest.fixture
def sandbox_root(tmp_path, monkeypatch):
    """config's folders pointed at an empty fake install (with the real config.toml)."""
    (tmp_path / "config.toml").write_bytes((config.ROOT / "config.toml").read_bytes())
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(config, "ACTIVE", tmp_path / "profiles" / "active.txt")
    monkeypatch.setattr(config, "SHARED_CACHE", tmp_path / "cache")
    monkeypatch.delenv("SYNERGIA_PROFILE_NAME", raising=False)
    monkeypatch.delenv("SYNERGIA_PROFILE", raising=False)
    return tmp_path


def test_create_and_switch_profiles(sandbox_root):
    assert config.active_name() is None
    a = profile.create({"brand": {"name": "FitDad Daily"}})
    b = profile.create({"brand": {"name": "FitDad Daily"}})       # same name: a free folder
    assert (a, b) == ("fitdad-daily", "fitdad-daily-2")
    assert config.list_profiles() == ["fitdad-daily", "fitdad-daily-2"]
    assert config.active_name() == b                               # the new one is active
    config.set_active(a)
    cfg = config.load()
    assert cfg.profile_name == a and cfg.brand.name == "FitDad Daily"
    home = sandbox_root / "profiles" / a
    assert cfg.output.dir == home / "output" and cfg.output.cache_dir == home / "cache"
    assert cfg.youtube.token_file == home / "secrets" / "youtube_token.json"
    assert cfg.output.shared_cache == sandbox_root / "cache"


def test_migrates_an_install_from_before_profiles(sandbox_root):
    (sandbox_root / "output" / "A - Psychology Explainer" / "run1").mkdir(parents=True)
    (sandbox_root / "cache" / "transcripts").mkdir(parents=True)
    (sandbox_root / "cache" / "history.json").write_text("{}", encoding="utf-8")
    (sandbox_root / "secrets").mkdir()
    (sandbox_root / "secrets" / "youtube_token.json").write_text("{}", encoding="utf-8")
    assert config.migrate_single_install() == "synergia"
    home = sandbox_root / "profiles" / "synergia"
    assert (home / "output" / "A - Psychology Explainer" / "run1").is_dir()
    assert (home / "cache" / "history.json").is_file()
    assert (home / "secrets" / "youtube_token.json").is_file()
    assert (sandbox_root / "cache" / "transcripts").is_dir()      # shared caches stay put
    assert tomllib.loads((home / "profile.toml").read_text(encoding="utf-8"))["brand"]["name"] == "SYNERGIA"
    assert config.migrate_single_install() is None                 # only once


def test_footer_name_keeps_user_casing(monkeypatch):
    from synergia.brand import elements
    monkeypatch.setattr(elements.CFG.brand, "name", "SYNERGIA")
    assert elements.footer_name() == "Synergia"
    monkeypatch.setattr(elements.CFG.brand, "name", "FitDad Daily")
    assert elements.footer_name() == "FitDad Daily"
