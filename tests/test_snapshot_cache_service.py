from __future__ import annotations

import threading
import types
import unittest

from app.snapshot_cache_service import build_cached_live_snapshot_response


class _FakeRepo:
    def __init__(self) -> None:
        self.state_calls: list[tuple[str, object]] = []

    def set_state(self, key, value):
        self.state_calls.append((key, value))


class SnapshotCacheServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.normalize_commodity_symbol = lambda value: str(value or "").strip().lower()
        elite.snapshot_cache_lock = threading.Lock()
        elite.snapshot_cache = {}
        elite.background_flags = {"remote_seed_running": False}
        elite.SNAPSHOT_CACHE_TTL_SECONDS = 1.5
        elite.SNAPSHOT_CACHE_BUSY_STALE_SECONDS = 45.0
        return elite

    def test_build_cached_live_snapshot_response_caches_first_result(self) -> None:
        elite = self._elite()
        calls = {"count": 0}

        def builder(payload=None):
            calls["count"] += 1
            return {"call": calls["count"], "payload": payload}

        payload = types.SimpleNamespace(commodity_query="gold", mission=None)
        first = build_cached_live_snapshot_response(elite, payload, builder)
        second = build_cached_live_snapshot_response(elite, payload, builder)

        self.assertEqual(first["call"], 1)
        self.assertEqual(second["call"], 1)
        self.assertEqual(calls["count"], 1)
        self.assertIn(("focus_commodity", "gold"), elite.repo.state_calls)

    def test_build_cached_live_snapshot_response_uses_stale_cache_when_busy(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(commodity_query="gold", mission=types.SimpleNamespace(commodity_query="silver"))
        elite.snapshot_cache["busy"] = (__import__("time").monotonic(), {"cached": True})
        elite.live_snapshot_cache_key = lambda incoming_payload: "busy"
        elite.background_flags["remote_seed_running"] = True

        def builder(payload=None):
            return {"fresh": True}

        result = build_cached_live_snapshot_response(elite, payload, builder)
        self.assertTrue(result["cached"])
        self.assertIn(("focus_commodity", "gold"), elite.repo.state_calls)
        self.assertIn(("mission_commodity", "silver"), elite.repo.state_calls)


if __name__ == "__main__":
    unittest.main()
