from __future__ import annotations

import types
import unittest

from app.trade_config_service import build_filters, default_route_request, tracked_live_commodity_symbols


class _FakeRepo:
    def __init__(self) -> None:
        self.values = {
            "cargo_capacity_override": 128,
            "jump_range_override": 22.5,
            "preferred_pad_size": "L",
            "focus_commodity": "gold",
            "mission_commodity": "silver",
        }

    def get_state(self, key, default=None):
        return self.values.get(key, default)


class TradeConfigServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.RouteRequest = lambda **kwargs: types.SimpleNamespace(
            cargo_capacity=kwargs.get("cargo_capacity"),
            jump_range=kwargs.get("jump_range"),
            min_pad_size=kwargs.get("min_pad_size", "M"),
            max_age_hours=kwargs.get("max_age_hours", 72),
            max_station_distance_ls=kwargs.get("max_station_distance_ls", 5000),
            min_profit_unit=kwargs.get("min_profit_unit", 1000),
            min_buy_stock=kwargs.get("min_buy_stock", 0),
            min_sell_demand=kwargs.get("min_sell_demand", 0),
            include_planetary=kwargs.get("include_planetary", True),
            include_settlements=kwargs.get("include_settlements", False),
            include_fleet_carriers=kwargs.get("include_fleet_carriers", False),
            no_surprise=kwargs.get("no_surprise", False),
            max_results=kwargs.get("max_results", 25),
        )
        elite.TradeFilters = lambda **kwargs: types.SimpleNamespace(**kwargs)
        elite.WATCHLIST_SYMBOLS = ["gold", "tritium"]
        elite.normalize_commodity_symbol = lambda value: str(value or "").strip().lower()
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_default_route_request_reads_repo_values(self) -> None:
        elite = self._elite()
        request = default_route_request(elite)
        self.assertEqual(request.cargo_capacity, 128)
        self.assertEqual(request.jump_range, 22.5)
        self.assertEqual(request.min_pad_size, "L")

    def test_build_filters_uses_repo_fallbacks(self) -> None:
        elite = self._elite()
        payload = elite.RouteRequest(cargo_capacity=None, jump_range=None)
        filters = build_filters(elite, payload)
        self.assertEqual(filters.cargo_capacity, 128)
        self.assertEqual(filters.jump_range, 22.5)
        self.assertEqual(filters.min_pad_size, "M")

    def test_tracked_live_commodity_symbols_merges_watchlist_and_states(self) -> None:
        elite = self._elite()
        result = tracked_live_commodity_symbols(elite)
        self.assertEqual(result, {"gold", "silver", "tritium"})


if __name__ == "__main__":
    unittest.main()
