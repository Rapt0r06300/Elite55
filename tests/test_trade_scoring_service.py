from __future__ import annotations

import types
import unittest

from app.trade_scoring_service import (
    clamp_score,
    confidence_label,
    estimate_minutes,
    freshness_confidence,
    install_trade_scoring_service_patches,
    ls_confidence,
    player_distance_confidence,
    relative_value_score,
    row_confidence,
    source_confidence,
)


class TradeScoringServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.SOURCE_CONFIDENCE = {"journal_market": 98}
        elite.PAD_RANK = {"?": 0, "S": 1, "M": 2, "L": 3}
        elite.age_hours = lambda value: 2.0 if value else None
        elite.station_accessible = lambda row, permits=None: True
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_basic_scoring_helpers_return_values(self) -> None:
        self.assertEqual(clamp_score(120), 100)
        self.assertEqual(confidence_label(85), "Haute")
        self.assertGreater(estimate_minutes(20, 500, 500, 20), 0)
        self.assertGreater(freshness_confidence(2, 72), 0)
        self.assertGreater(ls_confidence(500, 5000), 0)
        self.assertGreater(player_distance_confidence(10), 0)
        self.assertGreaterEqual(relative_value_score(10, 0, 20, higher_is_better=True), 0)

    def test_source_and_row_confidence_use_elite_helpers(self) -> None:
        elite = self._elite()
        self.assertEqual(source_confidence(elite, "journal_market"), 98)
        filters = types.SimpleNamespace(max_age_hours=72, max_station_distance_ls=5000, min_pad_size="M")
        row = {"price_source": "journal_market", "distance_to_arrival": 500, "landing_pad": "M", "price_updated_at": "2026-01-01T00:00:00Z"}
        self.assertGreater(row_confidence(elite, row, filters), 0)

    def test_install_trade_scoring_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_trade_scoring_service_patches(elite)
        filters = types.SimpleNamespace(max_age_hours=72, max_station_distance_ls=5000, min_pad_size="M")
        row = {"price_source": "journal_market", "distance_to_arrival": 500, "landing_pad": "M", "price_updated_at": "2026-01-01T00:00:00Z"}
        self.assertGreater(elite.row_confidence(row, filters), 0)
        self.assertEqual(elite.confidence_label(95), "Très haute")


if __name__ == "__main__":
    unittest.main()
