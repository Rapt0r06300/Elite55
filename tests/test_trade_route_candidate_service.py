from __future__ import annotations

import math
import types
import unittest

from app.trade_route_candidate_service import build_route_candidate, install_trade_route_candidate_service_patches


class TradeRouteCandidateServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.minimum_trade_units = lambda filters: 10
        elite.euclidean_distance = lambda a, b: 12.0
        elite.estimate_minutes = lambda distance, source_ls, target_ls, jump_range: 15.0
        elite.age_hours = lambda value: 2.0 if value else None
        elite.row_confidence = lambda row, filters, owned_permits=None: 88
        elite.clamp_score = lambda value, minimum=0, maximum=100: max(minimum, min(maximum, int(round(value))))
        elite.freshness_confidence = lambda freshness, max_age_hours: 90
        elite.confidence_label = lambda score: "Haute"
        elite.station_badges = lambda row, owned_permits=None: ["Pad M"]
        elite.station_accessibility_label = lambda row, owned_permits=None: "Acces direct"
        elite.math = math
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def _filters(self):
        return types.SimpleNamespace(cargo_capacity=100, min_profit_unit=10, jump_range=20.0, max_age_hours=72)

    def _row(self, market_id, buy_price, sell_price, stock, demand):
        return {
            "market_id": market_id,
            "commodity_symbol": "gold",
            "commodity_name_fr": "Or",
            "system_name": "Sol" if market_id == 1 else "Achenar",
            "station_name": "Galileo" if market_id == 1 else "Dawes",
            "buy_price": buy_price,
            "sell_price": sell_price,
            "stock": stock,
            "demand": demand,
            "distance_to_arrival": 500,
            "price_updated_at": "2026-01-01T00:00:00Z",
        }

    def test_build_route_candidate_returns_candidate(self) -> None:
        elite = self._elite()
        filters = self._filters()
        source = self._row(1, 100, 0, 100, 0)
        target = self._row(2, 0, 150, 0, 100)
        result = build_route_candidate(elite, source, target, filters, {"x": 0, "y": 0, "z": 0})
        self.assertIsNotNone(result)
        self.assertEqual(result["trip_profit"], 5000)

    def test_install_trade_route_candidate_service_patches_exposes_builder(self) -> None:
        elite = self._elite()
        filters = self._filters()
        source = self._row(1, 100, 0, 100, 0)
        target = self._row(2, 0, 150, 0, 100)
        install_trade_route_candidate_service_patches(elite)
        result = elite.build_route_candidate(source, target, filters, {"x": 0, "y": 0, "z": 0})
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
