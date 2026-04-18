from __future__ import annotations

import types
import unittest

from app.route_engine import (
    RouteContext,
    build_route_context,
    build_route_selection_payload,
    ensure_route_context,
    resolve_route_request,
    route_context_payload,
    select_primary_loop,
    select_primary_route,
)


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

    def test_ensure_route_context_reuses_existing_context(self) -> None:
        elite = self._elite()
        existing = RouteContext(
            request=types.SimpleNamespace(max_age_hours=12),
            filters=types.SimpleNamespace(cargo_capacity=32),
            player={"current_system": "Achenar"},
            rows=[{"commodity_symbol": "tritium"}],
            owned_permits={"achenar"},
            player_position={"x": 1, "y": 2, "z": 3},
        )
        resolved = ensure_route_context(elite, route_context=existing)
        self.assertIs(resolved, existing)

    def test_select_primary_route_prefers_best_hourly_result(self) -> None:
        routes = [
            {"commodity_name": "Gold", "trip_profit": 90000, "profit_per_hour": 1200000, "profit_per_minute": 20000, "unit_profit": 1500, "estimated_minutes": 6, "freshness_hours": 2, "confidence_score": 70, "route_score": 72},
            {"commodity_name": "Silver", "trip_profit": 150000, "profit_per_hour": 1000000, "profit_per_minute": 16000, "unit_profit": 1800, "estimated_minutes": 9, "freshness_hours": 1, "confidence_score": 80, "route_score": 81},
        ]
        primary = select_primary_route(routes, "profit_hour")
        self.assertEqual(primary["commodity_name"], "Gold")

    def test_select_primary_loop_prefers_fresh_loop_when_requested(self) -> None:
        loops = [
            {"from_station": "A", "to_station": "B", "total_profit": 300000, "profit_per_hour": 900000, "freshness_hours": 5.0, "confidence_score": 75, "route_score": 77},
            {"from_station": "C", "to_station": "D", "total_profit": 220000, "profit_per_hour": 950000, "freshness_hours": 0.4, "confidence_score": 86, "route_score": 88},
        ]
        primary = select_primary_loop(loops, "fresh")
        self.assertEqual(primary["from_station"], "C")

    def test_build_route_selection_payload_returns_ranked_results(self) -> None:
        routes = [
            {"commodity_name": "Slow", "trip_profit": 180000, "profit_per_hour": 900000, "profit_per_minute": 15000, "unit_profit": 1900, "estimated_minutes": 12, "freshness_hours": 0.5, "confidence_score": 90, "route_score": 91},
            {"commodity_name": "Quick", "trip_profit": 100000, "profit_per_hour": 950000, "profit_per_minute": 25000, "unit_profit": 1100, "estimated_minutes": 4, "freshness_hours": 1.0, "confidence_score": 80, "route_score": 85},
        ]
        loops = [
            {"from_station": "X", "to_station": "Y", "total_profit": 100000, "profit_per_hour": 700000, "freshness_hours": 1.0, "confidence_score": 70, "route_score": 70},
        ]
        payload = build_route_selection_payload(routes, loops, "fast")
        self.assertEqual(payload["ranking_mode"], "fast")
        self.assertEqual(payload["primary_route"]["commodity_name"], "Quick")
        self.assertEqual(payload["primary_loop"]["from_station"], "X")

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
