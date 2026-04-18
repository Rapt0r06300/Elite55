from __future__ import annotations

import types
import unittest

from app.mission_intel_service import (
    build_mission_intel_payload,
    resolve_mission_query,
    resolve_mission_quantity,
)


class _FakeRepo:
    def __init__(self) -> None:
        self._state = {
            "current_system": "Sol",
            "focus_commodity": "silver",
        }

    def get_all_state(self):
        return dict(self._state)

    def get_state(self, key, default=None):
        return self._state.get(key, default)

    def system_position(self, _name):
        return {"x": 0, "y": 0, "z": 0}

    def filtered_trade_rows(self, _filters):
        return [{"commodity_symbol": "silver"}]


class MissionIntelServiceTests(unittest.TestCase):
    def _elite(self):
        repo = _FakeRepo()
        elite = types.SimpleNamespace()
        elite.repo = repo
        elite.player_runtime_snapshot = lambda state: {
            "current_system": state.get("current_system"),
            "focus_commodity": "gold",
            "cargo_capacity": 128,
        }
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72, cargo_capacity=128)
        elite.build_filters = lambda request: types.SimpleNamespace(max_age_hours=request.max_age_hours, cargo_capacity=getattr(request, "cargo_capacity", 128))
        elite.known_owned_permits = lambda: {"sol"}
        elite.build_mission_intel = lambda query, quantity, filters, **kwargs: {
            "resolved": True,
            "commodity_name": query,
            "quantity": quantity,
            "rows": len(kwargs.get("all_rows") or []),
            "max_age_hours": filters.max_age_hours,
            "owned_permits": sorted(kwargs.get("owned_permits") or []),
            "target_system": kwargs.get("target_system"),
            "target_station": kwargs.get("target_station"),
        }
        return elite

    def test_resolve_mission_query_prefers_explicit_value(self) -> None:
        elite = self._elite()
        player = {"focus_commodity": "gold"}
        self.assertEqual(resolve_mission_query(elite, "tritium", player), "tritium")

    def test_resolve_mission_query_falls_back_to_player_then_repo(self) -> None:
        elite = self._elite()
        self.assertEqual(resolve_mission_query(elite, None, {"focus_commodity": "gold"}), "gold")
        self.assertEqual(resolve_mission_query(elite, None, {}), "silver")

    def test_resolve_mission_quantity_prefers_explicit_value(self) -> None:
        self.assertEqual(resolve_mission_quantity(42, {"cargo_capacity": 128}, types.SimpleNamespace(cargo_capacity=64)), 42)

    def test_resolve_mission_quantity_falls_back_to_player_then_filters(self) -> None:
        self.assertEqual(resolve_mission_quantity(None, {"cargo_capacity_override": 96}, types.SimpleNamespace(cargo_capacity=64)), 96)
        self.assertEqual(resolve_mission_quantity(None, {"cargo_capacity": 128}, types.SimpleNamespace(cargo_capacity=64)), 128)
        self.assertEqual(resolve_mission_quantity(None, {}, types.SimpleNamespace(cargo_capacity=64)), 64)

    def test_build_mission_intel_payload_uses_defaults(self) -> None:
        elite = self._elite()
        payload = build_mission_intel_payload(elite)
        self.assertTrue(payload["resolved"])
        self.assertEqual(payload["commodity_name"], "gold")
        self.assertEqual(payload["quantity"], 128)
        self.assertEqual(payload["rows"], 1)
        self.assertEqual(payload["owned_permits"], ["sol"])

    def test_build_mission_intel_payload_uses_explicit_values(self) -> None:
        elite = self._elite()
        route_request = types.SimpleNamespace(max_age_hours=24, cargo_capacity=64)
        payload = build_mission_intel_payload(
            elite,
            "palladium",
            42,
            target_system="Achenar",
            target_station="Dawes Hub",
            route_request=route_request,
        )
        self.assertEqual(payload["commodity_name"], "palladium")
        self.assertEqual(payload["quantity"], 42)
        self.assertEqual(payload["max_age_hours"], 24)
        self.assertEqual(payload["target_system"], "Achenar")
        self.assertEqual(payload["target_station"], "Dawes Hub")


if __name__ == "__main__":
    unittest.main()
