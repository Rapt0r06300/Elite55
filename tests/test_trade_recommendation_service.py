from __future__ import annotations

import types
import unittest

from app.trade_recommendation_service import (
    build_dashboard_decision_cards,
    install_trade_recommendation_service_patches,
    select_best_local_buy,
    select_best_local_sell,
    select_route_views,
    summarize_market_offer,
    summarize_purchase_plan,
)


class TradeRecommendationServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.DEFAULT_CONFIDENCE_FILTERS = types.SimpleNamespace(max_age_hours=72, max_station_distance_ls=5000, min_pad_size="M")
        elite.age_hours = lambda value: 2.0 if value else None
        elite.row_confidence = lambda row, filters, owned_permits=None: 88
        elite.confidence_label = lambda score: "Haute"
        elite.station_badges = lambda row, owned_permits=None: ["Pad M"]
        elite.station_accessibility_label = lambda row, owned_permits=None: "Acces direct"
        elite.euclidean_distance = lambda row, pos: 5.0 if pos else None
        elite.clamp_score = lambda value, minimum=0, maximum=100: max(minimum, min(maximum, int(round(value))))
        elite.relative_value_score = lambda value, minimum, maximum, higher_is_better: 80 if higher_is_better else 90
        elite.player_distance_confidence = lambda distance: 80
        elite.ls_confidence = lambda distance_ls, max_station_distance_ls: 90
        elite.freshness_confidence = lambda freshness_hours, max_age_hours: 85
        elite.estimate_minutes = lambda route_distance_ly, source_ls, target_ls, jump_range: 12.5
        elite.pad_confidence = lambda row, min_pad_size: 100
        elite.station_accessible = lambda row, owned_permits=None: True
        elite.meaningful_buy_rows = lambda rows, filters: list(rows)
        elite.meaningful_sell_rows = lambda rows, filters: list(rows)
        elite.WATCHLIST_SYMBOLS = ["gold"]
        elite.normalize_commodity_symbol = lambda value: str(value or "").strip().lower()
        elite.trader_memory_snapshot = lambda: {"favorites": {"commodity": [{"id": "gold"}]}, "recents": {"commodity": []}}
        elite.build_commodity_intel = lambda symbol, filters, **kwargs: {
            "resolved": True,
            "symbol": symbol,
            "commodity_name": "Or",
            "best_buys": [{"price": 100}],
            "best_sells": [{"price": 150}],
            "best_routes": [{"trip_profit": 5000}],
            "quick_trade": {"spread": 50},
        }
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def _row(self, buy_price=100, sell_price=150):
        return {
            "commodity_symbol": "gold",
            "commodity_name_fr": "Or",
            "system_name": "Sol",
            "station_name": "Galileo",
            "market_id": 1,
            "distance_to_arrival": 500,
            "landing_pad": "M",
            "buy_price": buy_price,
            "sell_price": sell_price,
            "stock": 100,
            "demand": 200,
            "price_updated_at": "2026-01-01T00:00:00Z",
        }

    def test_offer_and_purchase_helpers_return_expected_blocks(self) -> None:
        elite = self._elite()
        row = self._row()
        offer = summarize_market_offer(elite, row, {"x": 0}, mode="buy")
        purchase = summarize_purchase_plan(elite, row, 40, {"x": 0})
        self.assertEqual(offer["commodity_name"], "Or")
        self.assertEqual(purchase["units_covered"], 40)

    def test_local_buy_and_sell_selectors_return_best_offer(self) -> None:
        elite = self._elite()
        filters = elite.DEFAULT_CONFIDENCE_FILTERS
        rows = [self._row(100, 150), self._row(90, 140)]
        self.assertIsNotNone(select_best_local_buy(elite, rows, filters, {"x": 0}))
        self.assertIsNotNone(select_best_local_sell(elite, rows, filters, {"x": 0}))

    def test_route_views_and_decision_cards_return_main_blocks(self) -> None:
        elite = self._elite()
        routes = [
            {"unit_profit": 50, "trip_profit": 5000, "route_score": 90, "profit_per_minute": 300, "profit_per_hour": 18000, "confidence_score": 88, "freshness_hours": 2, "source_system": "Sol", "source_market_id": 1},
            {"unit_profit": 40, "trip_profit": 4000, "route_score": 85, "profit_per_minute": 250, "profit_per_hour": 15000, "confidence_score": 80, "freshness_hours": 3, "source_system": "Achenar", "source_market_id": 2},
        ]
        views = select_route_views(elite, routes, {"current_system": "Sol", "current_market_id": 1})
        cards = build_dashboard_decision_cards(elite, [self._row()], routes, elite.DEFAULT_CONFIDENCE_FILTERS, {"current_system": "Sol"}, {"x": 0})
        self.assertIsNotNone(views["best_margin"])
        self.assertIn("cheapest_buy", cards)

    def test_install_trade_recommendation_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_trade_recommendation_service_patches(elite)
        row = self._row()
        offer = elite.summarize_market_offer(row, {"x": 0}, mode="buy")
        self.assertEqual(offer["station_name"], "Galileo")


if __name__ == "__main__":
    unittest.main()
