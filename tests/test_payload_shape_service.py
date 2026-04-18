from __future__ import annotations

import types
import unittest

from app.payload_shape_service import (
    install_payload_shape_service_patches,
    normalize_commodity_intel_payload,
    normalize_dashboard_payload,
    normalize_live_snapshot_payload,
    normalize_local_pulse_payload,
    normalize_mission_intel_payload,
)


class PayloadShapeServiceTests(unittest.TestCase):
    def test_normalize_dashboard_payload_adds_missing_blocks(self) -> None:
        result = normalize_dashboard_payload({})
        self.assertIn("routes", result)
        self.assertIn("route_views", result)
        self.assertIn("decision_cards", result)
        self.assertIn("ranking_mode", result)

    def test_normalize_commodity_intel_payload_adds_quick_trade(self) -> None:
        result = normalize_commodity_intel_payload({})
        self.assertIn("best_routes", result)
        self.assertIn("quick_trade", result)
        self.assertIn("decision_cards", result)
        self.assertFalse(result["resolved"])

    def test_normalize_mission_intel_payload_adds_expected_keys(self) -> None:
        result = normalize_mission_intel_payload({})
        self.assertIn("best_routes", result)
        self.assertIn("route_views", result)
        self.assertIn("decision_cards", result)
        self.assertFalse(result["resolved"])

    def test_normalize_local_pulse_payload_adds_dataset(self) -> None:
        result = normalize_local_pulse_payload({})
        self.assertIn("dataset", result)
        self.assertEqual(result["dataset"]["rows"], 0)

    def test_normalize_live_snapshot_payload_normalizes_nested_blocks(self) -> None:
        result = normalize_live_snapshot_payload({})
        self.assertIn("dashboard", result)
        self.assertIn("commodity_intel", result)
        self.assertIn("mission_intel", result)
        self.assertIn("ranking_mode", result["dashboard"])

    def test_install_payload_shape_service_patches_wraps_builders(self) -> None:
        elite = types.SimpleNamespace()
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        elite.build_dashboard_payload = lambda *args, **kwargs: {}
        elite.build_commodity_intel_payload = lambda *args, **kwargs: {}
        elite.build_mission_intel_payload = lambda *args, **kwargs: {}
        elite.local_pulse_payload = lambda *args, **kwargs: {}
        elite.build_live_snapshot_payload = lambda *args, **kwargs: {"dashboard": {}, "commodity_intel": {}, "mission_intel": {}}

        install_payload_shape_service_patches(elite)

        dashboard = elite.build_dashboard_payload()
        commodity = elite.build_commodity_intel_payload()
        mission = elite.build_mission_intel_payload()
        pulse = elite.local_pulse_payload()
        snapshot = elite.build_live_snapshot_payload()

        self.assertIn("route_views", dashboard)
        self.assertIn("quick_trade", commodity)
        self.assertIn("route_views", mission)
        self.assertIn("dataset", pulse)
        self.assertIn("dashboard", snapshot)


if __name__ == "__main__":
    unittest.main()
