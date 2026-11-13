"""Loads config.toml into a simple attribute-access object."""
from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def _ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    return obj


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def load(path: Path | None = None) -> SimpleNamespace:
    path = path or ROOT / "config.toml"
    with open(path, "rb") as f:
        cfg = _ns(tomllib.load(f))
    # Resolve relative paths against project root.
    for key in ("bold", "semibold", "medium", "black"):
        setattr(cfg.fonts, key, str(ROOT / getattr(cfg.fonts, key)))
    cfg.output.dir = ROOT / cfg.output.dir
    cfg.output.cache_dir = ROOT / cfg.output.cache_dir
    cfg.root = ROOT
    return cfg


CFG = load()
