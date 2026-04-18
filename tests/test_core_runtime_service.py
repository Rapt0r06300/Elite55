from __future__ import annotations

import types
import unittest

from app.core_runtime_service import (
    age_hours,
    age_minutes,
    compact_key,
    compact_search_key,
    euclidean_distance,
    install_core_runtime_service_patches,
    normalize_commodity_symbol,
    normalize_lookup_key,
    normalize_search_text,
    normalize_text_key,
    parse_dt,
    player_runtime_snapshot,
    search_words,
    strip_diacritics,
)


class CoreRuntimeServiceTests(unittest.TestCase):
    def test_parse_dt_and_age_helpers_accept_iso_values(self) -> None:
        self.assertIsNotNone(parse_dt("2026-01-01T00:00:00Z"))
        self.assertIsNotNone(age_hours("2026-01-01T00:00:00Z"))
        self.assertIsNotNone(age_minutes("2026-01-01T00:00:00Z"))

    def test_text_normalization_helpers_work(self) -> None:
        self.assertEqual(normalize_text_key(" $Gold_Name; "), "gold_name")
        self.assertEqual(strip_diacritics("Elite"), "Elite")
        self.assertEqual(normalize_search_text("  Elite   Dangerous "), "elite dangerous")
        self.assertEqual(compact_search_key("Elite Dangerous"), "elitedangerous")
        self.assertEqual(search_words("Elite Dangerous"), ["elite", "dangerous"])
        self.assertEqual(compact_key("Gold & Silver"), "goldandsilver")
        self.assertEqual(normalize_lookup_key("Python Mk II"), "python_mk_ii")
        self.assertEqual(normalize_commodity_symbol("$Gold_Name;"), "gold")

    def test_player_runtime_snapshot_adds_display_fields(self) -> None:
        result = player_runtime_snapshot(
            {
                "status_flags": {"docked": True},
                "current_station": "Galileo",
                "current_system": "Sol",
            }
        )
        self.assertEqual(result["local_mode"], "Amarré")
        self.assertEqual(result["station_display"], "Galileo")
        self.assertIn("Sol", result["location_line"])

    def test_euclidean_distance_returns_distance(self) -> None:
        result = euclidean_distance({"x": 0, "y": 0, "z": 0}, {"x": 3, "y": 4, "z": 0})
        self.assertEqual(result, 5.0)

    def test_install_core_runtime_service_patches_exposes_helpers(self) -> None:
        elite = types.SimpleNamespace()
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        install_core_runtime_service_patches(elite)
        self.assertEqual(elite.normalize_lookup_key("Python Mk II"), "python_mk_ii")
        self.assertEqual(elite.normalize_commodity_symbol("$Gold_Name;"), "gold")
        self.assertEqual(elite.euclidean_distance({"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 5}), 5.0)


if __name__ == "__main__":
    unittest.main()
