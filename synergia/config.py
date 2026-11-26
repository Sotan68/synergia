"""Loads the configuration into a simple attribute-access object.

Three layers, later ones win:
1. config.toml   - tracked defaults and technical settings
2. theme preset  - the look picked in the setup wizard (synergia/brand/themes.py)
3. the profile   - one person's brand: name, logo, niche voice, Engine A wording, hashtags, engines,
                   theme... (profiles/<name>/profile.toml, written by the setup wizard).

Profiles: an install can hold several, each a folder under profiles/ with its own videos (output/),
history, upload queue and Autopilot batches (cache/) and YouTube sign-in (secrets/). The active one
is named in profiles/active.txt (or SYNERGIA_PROFILE_NAME / `main.py --profile`). Podcast downloads
and transcripts are shared in cache/. With no profile yet, CFG.configured is False and the app opens
the setup wizard. SYNERGIA_PROFILE=<file> loads a single profile file directly (tests, previews).
"""
from __future__ import annotations

import os
import re
import shutil
import tomllib
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
ACTIVE = PROFILES / "active.txt"
SHARED_CACHE = ROOT / "cache"


def _ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    return obj


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def merge(base: dict, over: dict) -> dict:
    """Deep merge: tables merge key by key, everything else in `over` replaces."""
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


# ---------------------------------------------------------------- profiles
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40].rstrip("-") or "profile"


def list_profiles() -> list[str]:
    if not PROFILES.is_dir():
        return []
    return sorted(p.name for p in PROFILES.iterdir() if (p / "profile.toml").is_file())


def active_name() -> str | None:
    names = list_profiles()
    want = os.environ.get("SYNERGIA_PROFILE_NAME")
    if not want and ACTIVE.is_file():
        want = ACTIVE.read_text(encoding="utf-8").strip()
    if want in names:
        return want
    return names[0] if names else None


def set_active(name: str) -> None:
    PROFILES.mkdir(parents=True, exist_ok=True)
    ACTIVE.write_text(name, encoding="utf-8")


def profile_dir(name: str) -> Path:
    return PROFILES / name


def profile_path() -> Path:
    """The active profile file (it may not exist yet, before the first setup)."""
    env = os.environ.get("SYNERGIA_PROFILE")
    if env:
        return Path(env)
    name = active_name()
    return (profile_dir(name) if name else PROFILES / "_new") / "profile.toml"


def read_profile(path: Path | None = None) -> dict:
    path = path or profile_path()
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def raw_config(path: Path | None = None, profile: dict | None = None) -> dict:
    """The merged settings as plain dicts (before paths are resolved)."""
    from synergia.brand import themes

    with open(path or ROOT / "config.toml", "rb") as f:
        raw = tomllib.load(f)
    profile = read_profile() if profile is None else profile
    preset = (profile.get("theme") or {}).get("preset") or (raw.get("theme") or {}).get("preset")
    raw = merge(raw, themes.expand(preset or themes.DEFAULT))
    return merge(raw, profile)


def load(path: Path | None = None, profile_file: Path | None = None) -> SimpleNamespace:
    prof_file = profile_file or profile_path()
    home = prof_file.parent                        # the profile's own folder
    cfg = _ns(raw_config(path, read_profile(prof_file)))
    # Resolve relative paths ("file.ttf|Weight=500" keeps its axes).
    for key, val in vars(cfg.fonts).items():
        if isinstance(val, str):
            setattr(cfg.fonts, key, str(ROOT / val))
    logo = getattr(cfg.brand, "logo", "")
    cfg.brand.logo = (home / logo if (home / logo).is_file() else ROOT / logo) if logo else None
    cfg.output.dir = home / cfg.output.dir
    cfg.output.cache_dir = home / cfg.output.cache_dir
    cfg.output.shared_cache = SHARED_CACHE
    own_secret = home / "secrets" / "client_secret.json"
    cfg.youtube.client_secret = own_secret if own_secret.is_file() else ROOT / cfg.youtube.client_secret
    cfg.youtube.token_file = home / "secrets" / "youtube_token.json"
    cfg.root = ROOT
    cfg.profile_file = prof_file
    cfg.profile_name = home.name
    cfg.configured = prof_file.is_file()
    return cfg


# ---------------------------------------------------------------- one-time migration
# Per-profile files that older installs kept directly in cache/.
_PER_PROFILE_CACHE = ("history.json", "queue.json", "upload_status.json", "autopilot",
                      "autopilot_settings.json", "autopilot.log", "last_prompt.txt", "claude")


def migrate_single_install() -> str | None:
    """Move an install from before profiles (profile.toml at the root, or just renders in output/)
    into profiles/<name>/ with its videos, history, queue and YouTube sign-in. Returns its name."""
    if list_profiles():
        return None
    old_profile = ROOT / "profile.toml"
    out = ROOT / "output"
    has_renders = out.is_dir() and any(out.iterdir())
    if not old_profile.is_file() and not has_renders:
        return None
    if old_profile.is_file():
        with open(old_profile, "rb") as f:
            name = slugify((tomllib.load(f).get("brand") or {}).get("name") or "synergia")
    else:
        name = "synergia"
    home = profile_dir(name)
    home.mkdir(parents=True, exist_ok=True)
    if old_profile.is_file():
        shutil.move(str(old_profile), home / "profile.toml")
    else:
        from synergia.profile import save, synergia_profile
        save(synergia_profile(), home / "profile.toml")
    if out.is_dir():
        shutil.move(str(out), home / "output")
    (home / "cache").mkdir(exist_ok=True)
    for item in _PER_PROFILE_CACHE:
        src = SHARED_CACHE / item
        if src.exists():
            shutil.move(str(src), home / "cache" / item)
    token = ROOT / "secrets" / "youtube_token.json"
    if token.is_file():
        (home / "secrets").mkdir(exist_ok=True)
        shutil.move(str(token), home / "secrets" / "youtube_token.json")
    set_active(name)
    return name


if not os.environ.get("SYNERGIA_PROFILE"):
    migrate_single_install()

CFG = load()
