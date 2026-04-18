from __future__ import annotations

import types
import unittest

from app.trade_query_service import (
    build_route_request_with_max_age,
    resolve_focus_commodity_query,
    resolve_mission_quantity,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.values = {"focus_commodity": "silver"}

    def get_state(self, key, default=None):
        return self.values.get(key, default)


class TradeQueryServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72)
        return elite

    def test_resolve_focus_commodity_query_prefers_explicit_value(self) -> None:
        elite = self._elite()
        result = resolve_focus_commodity_query(elite, "gold", {"focus_commodity": "palladium"})
        self.assertEqual(result, "gold")

    def test_resolve_focus_commodity_query_uses_player_then_repo(self) -> None:
        elite = self._elite()
        self.assertEqual(resolve_focus_commodity_query(elite, None, {"focus_commodity": "palladium"}), "palladium")
        self.assertEqual(resolve_focus_commodity_query(elite, None, None), "silver")

    def test_resolve_mission_quantity_uses_best_available_value(self) -> None:
        filters = types.SimpleNamespace(cargo_capacity=120)
        self.assertEqual(resolve_mission_quantity(50, {"cargo_capacity": 80}, filters), 50)
        self.assertEqual(resolve_mission_quantity(None, {"cargo_capacity_override": 90}, filters), 90)
        self.assertEqual(resolve_mission_quantity(None, {"cargo_capacity": 80}, filters), 80)
        self.assertEqual(resolve_mission_quantity(None, {}, filters), 120)

    def test_build_route_request_with_max_age_overrides_default(self) -> None:
        elite = self._elite()
        request = build_route_request_with_max_age(elite, 24)
        self.assertEqual(request.max_age_hours, 24)


if __name__ == "__main__":
    unittest.main()
