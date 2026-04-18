from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from app.live_snapshot_backend import (
    get_cached_live_snapshot,
    live_snapshot_cache_key,
    store_cached_live_snapshot,
)


class FakePayload:
    def __init__(self, data):
        self.data = data

    def model_dump(self, mode="json", exclude_none=False):
        return self.data


class LiveSnapshotBackendTests(unittest.TestCase):
    def test_cache_key_is_stable_and_sorted(self) -> None:
        payload = FakePayload({"b": 2, "a": 1})
        key = live_snapshot_cache_key(payload)
        self.assertEqual(key, '{"a": 1, "b": 2}')

    def test_store_and_read_snapshot(self) -> None:
        cache = {}
        lock = threading.Lock()
        value = {"ok": True}
        store_cached_live_snapshot(cache, lock, "demo", value, max_entries=4)
        cached = get_cached_live_snapshot(cache, lock, "demo", max_age_seconds=10)
        self.assertEqual(cached, value)

    def test_expired_snapshot_returns_none(self) -> None:
        cache = {"demo": (10.0, {"ok": True})}
        lock = threading.Lock()
        with patch("app.live_snapshot_backend.time.monotonic", return_value=25.5):
            cached = get_cached_live_snapshot(cache, lock, "demo", max_age_seconds=10)
        self.assertIsNone(cached)

    def test_cache_drops_oldest_entry_when_limit_is_reached(self) -> None:
        cache = {}
        lock = threading.Lock()
        with patch("app.live_snapshot_backend.time.monotonic", side_effect=[1.0, 2.0, 3.0]):
            store_cached_live_snapshot(cache, lock, "one", {"value": 1}, max_entries=2)
            store_cached_live_snapshot(cache, lock, "two", {"value": 2}, max_entries=2)
            store_cached_live_snapshot(cache, lock, "three", {"value": 3}, max_entries=2)
        self.assertNotIn("one", cache)
        self.assertIn("two", cache)
        self.assertIn("three", cache)


if __name__ == "__main__":
    unittest.main()
