"""Caching LLM-judge verdicts: identical judge inputs cost nothing the second time.

The cache is keyed by the full judge prompt (which embeds both the criterion and
the assistant output) plus the judge identity, and persisted as JSON in
`.promptseal/` so reruns and CI cache hits survive across processes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from promptseal._version import __version__
from promptseal.storage import base_dir

CACHE_FILENAME = "judge-cache.json"
MAX_ENTRIES = 2000


def _judge_cache_path(root: Optional[Path] = None) -> Path:
    return base_dir(root) / CACHE_FILENAME


def cache_key(user_text: str, judge_spec: str) -> str:
    """Stable key for one judge call (full prompt + judge identity)."""
    blob = json.dumps({"u": user_text, "j": judge_spec, "v": __version__}, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def load_cache(root: Optional[Path] = None) -> dict[str, Any]:
    path = _judge_cache_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(store: dict[str, Any], root: Optional[Path] = None) -> None:
    path = _judge_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(dict(list(store.items())[-MAX_ENTRIES:]), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except OSError:
        pass  # a broken cache must never break the run


class JudgeCache:
    """Wraps a JudgeFn with an exact-match answer cache (persisted as JSON)."""

    def __init__(self, judge_spec: str, root: Optional[Path] = None, enabled: bool = True):
        self.enabled = enabled
        self.judge_spec = judge_spec
        self.root = root
        self.store: dict[str, Any] = load_cache(root) if enabled else {}
        self.hits = 0
        self.misses = 0

    def wrap(self, judge_fn):
        if not self.enabled:
            return judge_fn

        def judge(system: str, user: str) -> str:
            key = cache_key(user, self.judge_spec)
            hit = self.store.get(key)
            if isinstance(hit, str):
                self.hits += 1
                return hit
            self.misses += 1
            answer = judge_fn(system, user)
            self.store[key] = answer
            return answer

        return judge

    def persist(self) -> None:
        if self.enabled:
            save_cache(self.store, self.root)