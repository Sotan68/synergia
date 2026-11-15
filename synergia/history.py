"""Remembers recently used content (hooks, character pairs, words, topics) so renders don't repeat.

Stored in <cache_dir>/history.json as {key: [most recent first, ...]}.
"""
from __future__ import annotations

import json
import random
from collections.abc import Sequence
from typing import TypeVar

from synergia.config import CFG

T = TypeVar("T")
KEEP = 60   # items remembered per key (roughly the last ~20 renders)


def _path():
    return CFG.output.cache_dir / "history.json"


def _load() -> dict[str, list]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def recent(key: str) -> list:
    return _load().get(key, [])


def remember(key: str, items: Sequence, keep: int = KEEP) -> None:
    data = _load()
    new = [x for x in items]
    old = [x for x in data.get(key, []) if x not in new]
    data[key] = (new + old)[:keep]
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def pick_fresh(rng: random.Random, pool: Sequence[T], k: int, key: str) -> list[T]:
    """k distinct items from pool, preferring ones not used recently (falls back gracefully)."""
    used = set(map(_hashable, recent(key)))
    fresh = [x for x in pool if _hashable(x) not in used]
    if len(fresh) < k:   # pool nearly exhausted: oldest-used items become fresh again
        order = {_hashable(x): i for i, x in enumerate(recent(key))}
        fresh += sorted((x for x in pool if _hashable(x) in used),
                        key=lambda x: -order.get(_hashable(x), 0))[: k - len(fresh)]
    return rng.sample(fresh, k) if len(fresh) >= k else rng.sample(list(pool), k)


def _hashable(x):
    return tuple(x) if isinstance(x, list) else x
