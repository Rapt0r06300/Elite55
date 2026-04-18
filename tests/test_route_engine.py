from __future__ import annotations

import types
import unittest

from app.route_engine import build_route_context, resolve_route_request, route_context_payload


class _FakeRepo:
    def __init__(self) -> None:
        self._state = {
            "current_system": "Sol",
        }

    def get_all_state(self):
        return dict(self._state)

    def system_position(self, _name):
        return {"x": 0, "y": 0, "z": 0}

    def filtered_trade_rows(self, _filters):
        return [{"commodity_symbol": "gold"}, {"commodity_symbol": "silver"}]


class RouteEngineTests(unittest.TestCase):
    def _elite(self):
        repo = _FakeRepo()
        elite = types.SimpleNamespace()
        elite.repo = repo
        elite.player_runtime_snapshot = lambda state: {"current_system": state.get("current_system"), "cargo_capacity": 128}
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72, cargo_capacity=128)
        elite.build_filters = lambda request: types.SimpleNamespace(max_age_hours=request.max_age_hours, cargo_capacity=getattr(request, "cargo_capacity", 128))
        elite.known_owned_permits = lambda: {"sol", "achenar"}
        return elite

    def test_resolve_route_request_uses_default_when_missing(self) -> None:
        elite = self._elite()
        request = resolve_route_request(elite)
        self.assertEqual(request.max_age_hours, 72)

    def test_build_route_context_collects_shared_values(self) -> None:
        elite = self._elite()
        context = build_route_context(elite)
        self.assertEqual(context.player["current_system"], "Sol")
        self.assertEqual(len(context.rows), 2)
        self.assertEqual(context.filters.max_age_hours, 72)
        self.assertEqual(context.owned_permits, {"sol", "achenar"})
        self.assertEqual(context.player_position, {"x": 0, "y": 0, "z": 0})

    def test_build_route_context_uses_explicit_request(self) -> None:
        elite = self._elite()
        request = types.SimpleNamespace(max_age_hours=24, cargo_capacity=64)
        context = build_route_context(elite, request)
        self.assertEqual(context.request.max_age_hours, 24)
        self.assertEqual(context.filters.cargo_capacity, 64)

    def test_route_context_payload_exposes_expected_keys(self) -> None:
        elite = self._elite()
        payload = route_context_payload(build_route_context(elite))
        self.assertIn("request", payload)
        self.assertIn("filters", payload)
        self.assertIn("player", payload)
        self.assertIn("rows", payload)
        self.assertIn("owned_permits", payload)
        self.assertIn("player_position", payload)


if __name__ == "__main__":
    unittest.main()
