from __future__ import annotations

import types
import unittest

from app.trade_rows_service import (
    build_default_confidence_filters,
    install_trade_rows_service_patches,
    meaningful_buy_rows,
    meaningful_sell_rows,
    station_badges,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.values = {"preferred_pad_size": "M"}

    def get_state(self, key, default=None):
        return self.values.get(key, default)


class TradeRowsServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.default_route_request = lambda: types.SimpleNamespace(min_pad_size="M", max_age_hours=72, max_station_distance_ls=5000, min_buy_stock=0, min_sell_demand=0)
        elite.build_filters = lambda payload: payload
        elite.station_accessible = lambda row, permits=None: not row.get("requires_permit")
        elite.known_owned_permits = lambda: set()
        elite.pad_confidence = lambda row, min_pad_size: 100 if row.get("landing_pad") in {"M", "L"} else 0
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def _row(self, **overrides):
        row = {
            "landing_pad": "M",
            "buy_price": 100,
            "sell_price": 150,
            "stock": 50,
            "demand": 60,
            "has_market": 1,
            "is_planetary": 0,
            "is_odyssey": 0,
            "is_fleet_carrier": 0,
            "price_source": "journal_market",
            "requires_permit": 0,
        }
        row.update(overrides)
        return row

    def test_station_badges_builds_simple_badges(self) -> None:
        elite = self._elite()
        badges = station_badges(elite, self._row())
        self.assertIn("Pad M", badges)
        self.assertIn("Marché", badges)
        self.assertIn("Live", badges)

    def test_meaningful_buy_and_sell_rows_filter_invalid_rows(self) -> None:
        elite = self._elite()
        filters = types.SimpleNamespace(min_buy_stock=20, min_sell_demand=20, min_pad_size="M")
        buy_rows = meaningful_buy_rows(elite, [self._row(stock=10), self._row(stock=30)], filters)
        sell_rows = meaningful_sell_rows(elite, [self._row(demand=10), self._row(demand=30)], filters)
        self.assertEqual(len(buy_rows), 1)
        self.assertEqual(len(sell_rows), 1)

    def test_build_default_confidence_filters_uses_default_route_request(self) -> None:
        elite = self._elite()
        filters = build_default_confidence_filters(elite)
        self.assertEqual(filters.min_pad_size, "M")

    def test_install_trade_rows_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_trade_rows_service_patches(elite)
        badges = elite.station_badges(self._row())
        self.assertIn("Pad M", badges)
        self.assertEqual(elite.DEFAULT_CONFIDENCE_FILTERS.min_pad_size, "M")


if __name__ == "__main__":
    unittest.main()
