from __future__ import annotations

import unittest

from app.trade_ranking import ranking_payload, sort_loops_by_mode, sort_routes_by_mode


class TradeRankingTests(unittest.TestCase):
    def test_profit_hour_prefers_best_hourly_route(self) -> None:
        routes = [
            {
                "commodity_name": "Gold",
                "trip_profit": 90000,
                "profit_per_hour": 1200000,
                "profit_per_minute": 20000,
                "unit_profit": 1500,
                "estimated_minutes": 6,
                "freshness_hours": 2,
                "confidence_score": 70,
                "route_score": 72,
            },
            {
                "commodity_name": "Silver",
                "trip_profit": 150000,
                "profit_per_hour": 1000000,
                "profit_per_minute": 16000,
                "unit_profit": 1800,
                "estimated_minutes": 9,
                "freshness_hours": 1,
                "confidence_score": 80,
                "route_score": 81,
            },
        ]

        ranked = sort_routes_by_mode(routes, "profit_hour")
        self.assertEqual(ranked[0]["commodity_name"], "Gold")

    def test_profit_total_prefers_highest_trip_profit(self) -> None:
        routes = [
            {
                "commodity_name": "Gold",
                "trip_profit": 90000,
                "profit_per_hour": 1200000,
                "profit_per_minute": 20000,
                "unit_profit": 1500,
                "estimated_minutes": 6,
                "freshness_hours": 2,
                "confidence_score": 70,
                "route_score": 72,
            },
            {
                "commodity_name": "Silver",
                "trip_profit": 150000,
                "profit_per_hour": 1000000,
                "profit_per_minute": 16000,
                "unit_profit": 1800,
                "estimated_minutes": 9,
                "freshness_hours": 1,
                "confidence_score": 80,
                "route_score": 81,
            },
        ]

        ranked = sort_routes_by_mode(routes, "profit_total")
        self.assertEqual(ranked[0]["commodity_name"], "Silver")

    def test_fast_prefers_shortest_route(self) -> None:
        routes = [
            {
                "commodity_name": "Slow",
                "trip_profit": 180000,
                "profit_per_hour": 900000,
                "profit_per_minute": 15000,
                "unit_profit": 1900,
                "estimated_minutes": 12,
                "freshness_hours": 0.5,
                "confidence_score": 90,
                "route_score": 91,
            },
            {
                "commodity_name": "Quick",
                "trip_profit": 100000,
                "profit_per_hour": 950000,
                "profit_per_minute": 25000,
                "unit_profit": 1100,
                "estimated_minutes": 4,
                "freshness_hours": 1.0,
                "confidence_score": 80,
                "route_score": 85,
            },
        ]

        ranked = sort_routes_by_mode(routes, "fast")
        self.assertEqual(ranked[0]["commodity_name"], "Quick")

    def test_fresh_prefers_freshest_route(self) -> None:
        routes = [
            {
                "commodity_name": "Old",
                "trip_profit": 160000,
                "profit_per_hour": 1100000,
                "profit_per_minute": 18000,
                "unit_profit": 1600,
                "estimated_minutes": 7,
                "freshness_hours": 8.0,
                "confidence_score": 92,
                "route_score": 92,
            },
            {
                "commodity_name": "Fresh",
                "trip_profit": 120000,
                "profit_per_hour": 900000,
                "profit_per_minute": 17000,
                "unit_profit": 1400,
                "estimated_minutes": 7,
                "freshness_hours": 0.2,
                "confidence_score": 88,
                "route_score": 90,
            },
        ]

        ranked = sort_routes_by_mode(routes, "fresh")
        self.assertEqual(ranked[0]["commodity_name"], "Fresh")

    def test_loops_follow_requested_mode(self) -> None:
        loops = [
            {
                "from_station": "A",
                "to_station": "B",
                "total_profit": 300000,
                "profit_per_hour": 900000,
                "freshness_hours": 5.0,
                "confidence_score": 75,
                "route_score": 77,
            },
            {
                "from_station": "C",
                "to_station": "D",
                "total_profit": 220000,
                "profit_per_hour": 950000,
                "freshness_hours": 0.4,
                "confidence_score": 86,
                "route_score": 88,
            },
        ]

        ranked_fast = sort_loops_by_mode(loops, "fast")
        ranked_fresh = sort_loops_by_mode(loops, "fresh")
        self.assertEqual(ranked_fast[0]["from_station"], "C")
        self.assertEqual(ranked_fresh[0]["from_station"], "C")

    def test_ranking_payload_returns_french_metadata(self) -> None:
        payload = ranking_payload("profit_total")
        self.assertEqual(payload["ranking_mode"], "profit_total")
        self.assertEqual(payload["ranking_label"], "Profit brut")
        self.assertIn("rentable", payload["ranking_title"])


if __name__ == "__main__":
    unittest.main()
