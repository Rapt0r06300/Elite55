from __future__ import annotations

import types
import unittest

from app.trader_memory_service import (
    get_trader_memory,
    install_trader_memory_service_patches,
    remember_mission_plan,
    remember_ship_profile,
    remember_trader_query,
    remember_trader_selection,
    toggle_trader_favorite,
    trader_memory_snapshot,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.state = {}

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value):
        self.state[key] = value


class TraderMemoryServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.utc_now_iso = lambda: "2026-01-01T00:00:00Z"
        elite.normalize_lookup_key = lambda value: str(value or "").strip().lower().replace(" ", "_")
        elite.TRADER_MEMORY_LIMIT = 18
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_remember_trader_selection_stores_recent_item(self) -> None:
        elite = self._elite()
        remember_trader_selection(elite, "commodity", "gold", "Or")
        memory = get_trader_memory(elite)
        self.assertEqual(memory["recent"]["commodity"][0]["id"], "gold")

    def test_toggle_trader_favorite_adds_then_removes_item(self) -> None:
        elite = self._elite()
        added = toggle_trader_favorite(elite, "commodity", "gold", "Or")
        removed = toggle_trader_favorite(elite, "commodity", "gold", "Or")
        self.assertEqual(added["favorites"]["commodity"][0]["id"], "gold")
        self.assertEqual(removed["favorites"]["commodity"], [])

    def test_remember_trader_query_stores_query(self) -> None:
        elite = self._elite()
        remember_trader_query(elite, "gold")
        snapshot = trader_memory_snapshot(elite)
        self.assertEqual(snapshot["recents"]["query"][0]["id"], "gold")

    def test_remember_mission_plan_stores_last_mission(self) -> None:
        elite = self._elite()
        remember_mission_plan(elite, "gold", 120, commodity_name="Or", target_system="Sol", target_station="Galileo")
        snapshot = trader_memory_snapshot(elite)
        self.assertEqual(snapshot["last_missions"][0]["label"], "Or")

    def test_remember_ship_profile_stores_profile(self) -> None:
        elite = self._elite()
        remember_ship_profile(elite, {"current_ship_code": "python", "current_system": "Sol", "cargo_capacity": 100, "jump_range": 20})
        snapshot = trader_memory_snapshot(elite)
        self.assertEqual(snapshot["ship_profiles"][0]["id"], "python")

    def test_install_trader_memory_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_trader_memory_service_patches(elite)
        elite.remember_trader_selection("commodity", "gold", "Or")
        snapshot = elite.trader_memory_snapshot()
        self.assertEqual(snapshot["last_commodities"][0]["id"], "gold")


if __name__ == "__main__":
    unittest.main()
