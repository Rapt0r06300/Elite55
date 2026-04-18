from __future__ import annotations

import json
import time
from typing import Any, Callable

from app.trader_context_service import update_live_snapshot_states


def live_snapshot_cache_key(elite_main: Any, payload: Any) -> str:
    builder = getattr(elite_main, "live_snapshot_cache_key", None)
    if callable(builder):
        return builder(payload)
    if payload is None:
        return "null"
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json", exclude_none=False)
    else:
        data = payload
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def get_cached_live_snapshot(elite_main: Any, key: str, *, max_age_seconds: float) -> dict[str, Any] | None:
    lock = getattr(elite_main, "snapshot_cache_lock", None)
    cache = getattr(elite_main, "snapshot_cache", None)
    if lock is None or not isinstance(cache, dict):
        return None
    with lock:
        cached = cache.get(key)
    if not cached:
        return None
    cached_at, value = cached
    if time.monotonic() - cached_at > max_age_seconds:
        return None
    return value


def store_cached_live_snapshot(elite_main: Any, key: str, value: dict[str, Any]) -> None:
    lock = getattr(elite_main, "snapshot_cache_lock", None)
    cache = getattr(elite_main, "snapshot_cache", None)
    if lock is None or not isinstance(cache, dict):
        return
    with lock:
        cache[key] = (time.monotonic(), value)
        if len(cache) > 12:
            oldest_key = min(cache.items(), key=lambda item: item[1][0])[0]
            cache.pop(oldest_key, None)


def build_cached_live_snapshot_response(
    elite_main: Any,
    payload: Any | None,
    builder: Callable[[Any | None], dict[str, Any]],
) -> dict[str, Any]:
    update_live_snapshot_states(elite_main, payload)

    cache_key = live_snapshot_cache_key(elite_main, payload)
    fresh = get_cached_live_snapshot(
        elite_main,
        cache_key,
        max_age_seconds=float(getattr(elite_main, "SNAPSHOT_CACHE_TTL_SECONDS", 1.5)),
    )
    if fresh is not None:
        return fresh

    background_flags = getattr(elite_main, "background_flags", {}) or {}
    if background_flags.get("remote_seed_running"):
        stale = get_cached_live_snapshot(
            elite_main,
            cache_key,
            max_age_seconds=float(getattr(elite_main, "SNAPSHOT_CACHE_BUSY_STALE_SECONDS", 45.0)),
        )
        if stale is not None:
            return stale

    result = builder(payload)
    store_cached_live_snapshot(elite_main, cache_key, result)
    return result
