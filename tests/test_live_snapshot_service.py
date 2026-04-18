from __future__ import annotations

import types
import unittest

from app.live_snapshot_service import build_live_snapshot_payload, build_local_pulse_payload


class _FakeRepo:
    def __init__(self) -> None:
        self._state = {
            "current_system": "Sol",
            "focus_commodity": "gold",
        }

    def get_all_state(self):
        return dict(self._state)

    def current_market(self):
        return {"station_name": "Galileo"}

    def name_library_summary(self):
        return {"total": 12}

    def commodity_price_count(self):
        return 345

    def get_state(self, key, default=None):
        return self._state.get(key, default)

    def system_position(self, _name):
        return {"x": 0, "y": 0, "z": 0}

    def filtered_trade_rows(self, _filters):
        return [{"commodity_symbol": "gold"}]


class _FakeSnapshot:
    def __init__(self, route=None, commodity_query=None, mission=None):
        self.route = route
        self.commodity_query = commodity_query
        self.mission = mission


class LiveSnapshotServiceTests(unittest.TestCase):
    def _elite(self):
        repo = _FakeRepo()
        elite = types.SimpleNamespace()
        elite.repo = repo
        elite.player_runtime_snapshot = lambda state: {"current_system": state.get("current_system"), "cargo_capacity": 128}
        elite.local_sync_service = types.SimpleNamespace(status=lambda: {"running": True})
        elite.eddn_listener = types.SimpleNamespace(status=lambda: {"running": False})
        elite.build_engine_status_from_values = lambda rows, name_summary, local_sync, current_market, current_system: {
            "rows": rows,
            "current_system": current_system,
            "ready": bool(local_sync.get("running")),
            "library": name_summary.get("total"),
            "market": current_market.get("station_name"),
        }
        elite.sources_payload = lambda: {"journal_last_import": "ok"}
        elite.nav_route_payload = lambda: {"available": True}
        elite.combat_support_payload = lambda: {"stations": []}
        elite.JOURNAL_DIR = "journal"
        elite.GAME_DIR = "game"
        elite.known_owned_permits = lambda: {"sol"}
        elite.known_owned_permit_labels = lambda: ["Sol"]
        elite.LiveSnapshotRequest = _FakeSnapshot
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72)
        elite.build_filters = lambda route_request: types.SimpleNamespace(cargo_capacity=128, max_age_hours=route_request.max_age_hours)
        elite.build_trade_dashboard = lambda filters, **kwargs: {"filters": filters, "dashboard": True, "routes": []}
        elite.enrich_dashboard_payload = lambda dashboard, route_request, owned_permits: {
            **dashboard,
            "owned_permits": sorted(owned_permits),
            "max_age_hours": route_request.max_age_hours,
        }
        elite.build_commodity_intel = lambda query, filters, **kwargs: {"resolved": True, "commodity_name": query, "filters": filters.max_age_hours}
        elite.build_mission_intel = lambda query, quantity, filters, **kwargs: {
            "resolved": True,
            "commodity_name": query,
            "quantity": quantity,
            "filters": filters.max_age_hours,
        }
        return elite

    def test_local_pulse_payload_contains_expected_sections(self) -> None:
        elite = self._elite()
        payload = build_local_pulse_payload(elite)
        self.assertEqual(payload["player"]["current_system"], "Sol")
        self.assertEqual(payload["dataset"]["rows"], 345)
        self.assertEqual(payload["owned_permit_labels"], ["Sol"])

    def test_live_snapshot_payload_builds_dashboard_commodity_and_mission(self) -> None:
        elite = self._elite()
        payload = build_live_snapshot_payload(elite)
        self.assertTrue(payload["dashboard"]["dashboard"])
        self.assertEqual(payload["commodity_intel"]["commodity_name"], "gold")
        self.assertEqual(payload["mission_intel"]["quantity"], 128)

    def test_live_snapshot_payload_uses_explicit_snapshot_values(self) -> None:
        elite = self._elite()
        mission = types.SimpleNamespace(commodity_query="silver", quantity=42, target_system="Achenar", target_station="Dawes Hub")
        snapshot = _FakeSnapshot(route=types.SimpleNamespace(max_age_hours=24), commodity_query="tritium", mission=mission)
        payload = build_live_snapshot_payload(elite, snapshot)
        self.assertEqual(payload["commodity_intel"]["commodity_name"], "tritium")
        self.assertEqual(payload["mission_intel"]["commodity_name"], "silver")
        self.assertEqual(payload["mission_intel"]["quantity"], 42)
        self.assertEqual(payload["dashboard"]["max_age_hours"], 24)


if __name__ == "__main__":
    unittest.main()
