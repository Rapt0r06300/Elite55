from __future__ import annotations

import json
import time
from typing import Any


def live_snapshot_cache_key(payload: Any) -> str:
    return json.dumps(payload.model_dump(mode="json", exclude_none=False), ensure_ascii=False, sort_keys=True)


def get_cached_live_snapshot(
    cache: dict[str, tuple[float, dict[str, Any]]],
    lock: Any,
    key: str,
    *,
    max_age_seconds: float,
) -> dict[str, Any] | None:
    with lock:
        cached = cache.get(key)
    if not cached:
        return None
    cached_at, value = cached
    if time.monotonic() - cached_at > max_age_seconds:
        return None
    return value


def store_cached_live_snapshot(
    cache: dict[str, tuple[float, dict[str, Any]]],
    lock: Any,
    key: str,
    value: dict[str, Any],
    *,
    max_entries: int = 12,
) -> None:
    with lock:
        cache[key] = (time.monotonic(), value)
        if len(cache) > max_entries:
            oldest_key = min(cache.items(), key=lambda item: item[1][0])[0]
            cache.pop(oldest_key, None)


def install_live_snapshot_backend_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_live_snapshot_backend_installed", False):
        return

    def patched_live_snapshot_cache_key(payload: Any) -> str:
        return live_snapshot_cache_key(payload)

    def patched_get_cached_live_snapshot(key: str, *, max_age_seconds: float) -> dict[str, Any] | None:
        return get_cached_live_snapshot(
            elite_main.snapshot_cache,
            elite_main.snapshot_cache_lock,
            key,
            max_age_seconds=max_age_seconds,
        )

    def patched_store_cached_live_snapshot(key: str, value: dict[str, Any]) -> None:
        store_cached_live_snapshot(
            elite_main.snapshot_cache,
            elite_main.snapshot_cache_lock,
            key,
            value,
        )

    elite_main.live_snapshot_cache_key = patched_live_snapshot_cache_key
    elite_main.get_cached_live_snapshot = patched_get_cached_live_snapshot
    elite_main.store_cached_live_snapshot = patched_store_cached_live_snapshot
    elite_main.app.state.elite55_live_snapshot_backend_installed = True
