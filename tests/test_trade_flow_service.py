from __future__ import annotations

import types
import unittest

from app.trade_flow_service import (
    commodity_price_filters,
    filter_trade_rows_by_context,
    install_trade_flow_service_patches,
    minimum_buy_stock,
    minimum_sell_demand,
    minimum_trade_units,
    relaxed_trade_filters,
    resolve_trade_context,
    rows_for_symbol_with_fallback,
    station_allowed,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.rows = []

    def resolve_system(self, system_name):
        if not system_name:
            return None
        return {"name": system_name}

    def resolve_station(self, station_name, system_name=None):
        if not station_name:
            return None
        return {"system_name": system_name or "Sol", "station_name": station_name, "market_id": 42}

    def filtered_trade_rows(self, filters, commodity_symbols=None):
        return list(self.rows)


class TradeFlowServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.PAD_RANK = {"?": 0, "S": 1, "M": 2, "L": 3}
        elite.TradeFilters = lambda **kwargs: types.SimpleNamespace(**kwargs)
        elite.replace = lambda payload, **changes: types.SimpleNamespace(**{**payload.__dict__, **changes})
        elite.NO_DISTANCE_LIMIT_LS = 2_147_483_647
        elite.station_accessible = lambda row, owned_permits=None: not row.get("requires_permit")
        elite.age_hours = lambda value: 2.0 if value else None
        elite.normalize_search_text = lambda value: str(value or "").strip().lower()
        elite.meaningful_buy_rows = lambda rows, filters: [row for row in rows if int(row.get("buy_price") or 0) > 0]
        elite.meaningful_sell_rows = lambda rows, filters: [row for row in rows if int(row.get("sell_price") or 0) > 0]
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def _filters(self):
        return types.SimpleNamespace(
            cargo_capacity=100,
            jump_range=20.0,
            max_age_hours=72,
            max_station_distance_ls=5000,
            min_profit_unit=1000,
            min_buy_stock=10,
            min_sell_demand=20,
            min_pad_size="M",
            include_planetary=True,
            include_settlements=False,
            include_fleet_carriers=False,
            no_surprise=False,
            max_results=25,
        )

    def _row(self, **overrides):
        row = {
            "commodity_symbol": "gold",
            "market_id": 1,
            "system_name": "Sol",
            "station_name": "Galileo",
            "landing_pad": "M",
            "distance_to_arrival": 500,
            "price_updated_at": "2026-01-01T00:00:00Z",
            "buy_price": 100,
            "sell_price": 150,
            "requires_permit": 0,
            "is_planetary": 0,
            "is_odyssey": 0,
            "is_fleet_carrier": 0,
        }
        row.update(overrides)
        return row

    def test_station_allowed_and_threshold_helpers_work(self) -> None:
        elite = self._elite()
        filters = self._filters()
        self.assertTrue(station_allowed(elite, self._row(), filters))
        self.assertGreaterEqual(minimum_trade_units(filters), 4)
        self.assertGreaterEqual(minimum_buy_stock(filters), 10)
        self.assertGreaterEqual(minimum_sell_demand(filters), 20)

    def test_relaxed_and_commodity_filters_expand_limits(self) -> None:
        elite = self._elite()
        filters = self._filters()
        relaxed = relaxed_trade_filters(elite, filters)
        commodity = commodity_price_filters(elite, filters)
        self.assertGreaterEqual(relaxed.max_station_distance_ls, 20000)
        self.assertEqual(commodity.max_station_distance_ls, elite.NO_DISTANCE_LIMIT_LS)

    def test_resolve_trade_context_and_filter_rows_by_context(self) -> None:
        elite = self._elite()
        context = resolve_trade_context(elite, "Sol", "Galileo")
        rows = [self._row(system_name="Sol", market_id=42), self._row(system_name="Achenar", market_id=43)]
        filtered = filter_trade_rows_by_context(elite, rows, system_name=context["system_name"], market_id=context["market_id"])
        self.assertEqual(context["market_id"], 42)
        self.assertEqual(len(filtered), 1)

    def test_rows_for_symbol_with_fallback_merges_rows(self) -> None:
        elite = self._elite()
        filters = self._filters()
        elite.repo.rows = [self._row(market_id=1, buy_price=100, sell_price=0), self._row(market_id=2, buy_price=0, sell_price=150)]
        rows, fallback_used = rows_for_symbol_with_fallback(elite, "gold", filters, set())
        self.assertEqual(len(rows), 2)
        self.assertFalse(fallback_used)

    def test_install_trade_flow_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_trade_flow_service_patches(elite)
        filters = self._filters()
        self.assertTrue(elite.station_allowed(self._row(), filters))
        self.assertEqual(elite.resolve_trade_context("Sol", "Galileo")["market_id"], 42)


if __name__ == "__main__":
    unittest.main()
