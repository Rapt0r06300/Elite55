from __future__ import annotations

import types
import unittest

from app.trader_context_service import (
    build_route_request_with_max_age,
    remember_commodity_lookup,
    remember_mission_result,
    set_focus_commodity_state,
    set_mission_commodity_state,
    update_live_snapshot_states,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.state_calls: list[tuple[str, object]] = []

    def set_state(self, key, value):
        self.state_calls.append((key, value))

    def resolve_commodity(self, query):
        if query == "gold":
            return {"symbol": "gold", "commodity_name": "Or"}
        return None


class TraderContextServiceTests(unittest.TestCase):
    def _elite(self):
        remembered: list[tuple] = []
        mission_plans: list[tuple] = []
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.normalize_commodity_symbol = lambda value: str(value or "").strip().lower()
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72)
        elite.remember_trader_selection = lambda *args, **kwargs: remembered.append((args, kwargs))
        elite.remember_trader_query = lambda query: remembered.append((("query", query), {}))
        elite.remember_mission_plan = lambda *args, **kwargs: mission_plans.append((args, kwargs))
        elite._remembered = remembered
        elite._mission_plans = mission_plans
        return elite

    def test_set_focus_and_mission_states_store_normalized_values(self) -> None:
        elite = self._elite()
        set_focus_commodity_state(elite, " Gold ")
        set_mission_commodity_state(elite, "Silver")
        self.assertIn(("focus_commodity", "gold"), elite.repo.state_calls)
        self.assertIn(("mission_commodity", "silver"), elite.repo.state_calls)

    def test_build_route_request_with_max_age_overrides_default(self) -> None:
        elite = self._elite()
        request = build_route_request_with_max_age(elite, 24)
        self.assertEqual(request.max_age_hours, 24)

    def test_remember_commodity_lookup_updates_state_and_memory(self) -> None:
        elite = self._elite()
        resolved = remember_commodity_lookup(elite, "gold")
        self.assertEqual(resolved["symbol"], "gold")
        self.assertIn(("focus_commodity", "gold"), elite.repo.state_calls)
        self.assertTrue(elite._remembered)

    def test_remember_mission_result_updates_memory_and_plan(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(commodity_query="gold", quantity=120)
        result = {
            "resolved": True,
            "symbol": "gold",
            "commodity_name": "Or",
            "target_system": "Sol",
            "target_station": "Galileo",
        }
        remember_mission_result(elite, payload, result)
        self.assertTrue(elite._remembered)
        self.assertTrue(elite._mission_plans)

    def test_update_live_snapshot_states_updates_both_values(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(commodity_query="gold", mission=types.SimpleNamespace(commodity_query="silver"))
        update_live_snapshot_states(elite, payload)
        self.assertIn(("focus_commodity", "gold"), elite.repo.state_calls)
        self.assertIn(("mission_commodity", "silver"), elite.repo.state_calls)


if __name__ == "__main__":
    unittest.main()
