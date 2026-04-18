from __future__ import annotations

import types
import unittest

from app.trader_api_service import (
    apply_player_config_response,
    build_commodity_intel_response,
    build_live_snapshot_response,
    build_local_pulse_response,
    build_mission_intel_response,
    build_routes_response,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.state_calls: list[tuple[str, object]] = []
        self.states_calls: list[dict[str, object]] = []

    def set_state(self, key, value):
        self.state_calls.append((key, value))

    def set_states(self, values):
        self.states_calls.append(dict(values))

    def resolve_commodity(self, query):
        if query == "gold":
            return {"symbol": "gold", "commodity_name": "Or"}
        return None


class TraderApiServiceTests(unittest.TestCase):
    def _elite(self):
        repo = _FakeRepo()
        remembered: list[tuple] = []
        mission_plans: list[tuple] = []
        ship_profiles: list[dict[str, object]] = []
        elite = types.SimpleNamespace()
        elite.repo = repo
        elite.normalize_commodity_symbol = lambda value: str(value or "").strip().lower()
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72)
        elite.build_filters = lambda payload: {"max_age_hours": payload.max_age_hours}
        elite.build_dashboard_payload = lambda route_request=None: {"player": {"ship": "Python"}, "route_request": route_request}
        elite.dashboard_payload = lambda route_request=None: {"player": {"ship": "Fallback"}, "route_request": route_request}
        elite.local_pulse_payload = lambda: {"pulse": True}
        elite.build_live_snapshot_payload = lambda payload=None: {"snapshot": True, "payload": payload}
        elite.build_commodity_intel = lambda query, filters, **kwargs: {"resolved": True, "symbol": "gold", "commodity_name": "Or", "query": query, "filters": filters, **kwargs}
        elite.build_mission_intel = lambda query, quantity, filters, **kwargs: {"resolved": True, "symbol": "gold", "commodity_name": "Or", "query": query, "quantity": quantity, "filters": filters, "target_system": kwargs.get("target_system"), "target_station": kwargs.get("target_station")}
        elite.remember_trader_selection = lambda *args, **kwargs: remembered.append((args, kwargs))
        elite.remember_trader_query = lambda query: remembered.append((("query", query), {}))
        elite.remember_mission_plan = lambda *args, **kwargs: mission_plans.append((args, kwargs))
        elite.remember_ship_profile = lambda player: ship_profiles.append(dict(player))
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        elite._remembered = remembered
        elite._mission_plans = mission_plans
        elite._ship_profiles = ship_profiles
        return elite

    def test_build_routes_response_wraps_dashboard(self) -> None:
        elite = self._elite()
        result = build_routes_response(elite, "demo")
        self.assertTrue(result["ok"])
        self.assertEqual(result["dashboard"]["route_request"], "demo")

    def test_build_local_pulse_response_wraps_pulse(self) -> None:
        elite = self._elite()
        result = build_local_pulse_response(elite)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dashboard"]["pulse"])

    def test_build_live_snapshot_response_updates_focus_state(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(commodity_query="gold", mission=types.SimpleNamespace(commodity_query="silver"))
        result = build_live_snapshot_response(elite, payload)
        self.assertTrue(result["snapshot"])
        self.assertIn(("focus_commodity", "gold"), elite.repo.state_calls)
        self.assertIn(("mission_commodity", "silver"), elite.repo.state_calls)

    def test_build_commodity_intel_response_updates_memory_and_filters(self) -> None:
        elite = self._elite()
        result = build_commodity_intel_response(elite, "gold", max_age_hours=24, origin_system="Sol")
        self.assertEqual(result["query"], "gold")
        self.assertEqual(result["filters"]["max_age_hours"], 24)
        self.assertEqual(result["origin_system"], "Sol")
        self.assertIn(("focus_commodity", "gold"), elite.repo.state_calls)
        self.assertTrue(elite._remembered)

    def test_build_mission_intel_response_updates_memory_and_plan(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(
            commodity_query="gold",
            quantity=120,
            target_system="Sol",
            target_station="Galileo",
            max_age_hours=18,
        )
        result = build_mission_intel_response(elite, payload)
        self.assertEqual(result["quantity"], 120)
        self.assertEqual(result["filters"]["max_age_hours"], 18)
        self.assertEqual(result["target_system"], "Sol")
        self.assertTrue(elite._mission_plans)
        self.assertIn(("mission_commodity", "gold"), elite.repo.state_calls)

    def test_apply_player_config_response_updates_state_and_ship_profile(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(cargo_capacity_override=160, jump_range_override=24.5, preferred_pad_size="L")
        result = apply_player_config_response(elite, payload)
        self.assertTrue(result["ok"])
        self.assertEqual(elite.repo.states_calls[0]["preferred_pad_size"], "L")
        self.assertTrue(elite._ship_profiles)


if __name__ == "__main__":
    unittest.main()
