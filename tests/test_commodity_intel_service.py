from __future__ import annotations

import types
import unittest

from app.commodity_intel_service import build_commodity_intel_payload, resolve_commodity_query


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


class CommodityIntelServiceTests(unittest.TestCase):
    def _elite(self):
        repo = _FakeRepo()
        elite = types.SimpleNamespace()
        elite.repo = repo
        elite.player_runtime_snapshot = lambda state: {"current_system": state.get("current_system"), "focus_commodity": "gold"}
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72, cargo_capacity=128)
        elite.build_filters = lambda request: types.SimpleNamespace(max_age_hours=request.max_age_hours, cargo_capacity=getattr(request, "cargo_capacity", 128))
        elite.known_owned_permits = lambda: {"sol"}
        elite.build_commodity_intel = lambda query, filters, **kwargs: {
            "resolved": True,
            "commodity_name": query,
            "rows": len(kwargs.get("all_rows") or []),
            "max_age_hours": filters.max_age_hours,
            "owned_permits": sorted(kwargs.get("owned_permits") or []),
        }
        return elite

    def test_resolve_commodity_query_prefers_explicit_value(self) -> None:
        elite = self._elite()
        player = {"focus_commodity": "gold"}
        self.assertEqual(resolve_commodity_query(elite, "tritium", player), "tritium")

    def test_resolve_commodity_query_falls_back_to_player_then_repo(self) -> None:
        elite = self._elite()
        self.assertEqual(resolve_commodity_query(elite, None, {"focus_commodity": "gold"}), "gold")
        self.assertEqual(resolve_commodity_query(elite, None, {}), "silver")

    def test_build_commodity_intel_payload_uses_defaults(self) -> None:
        elite = self._elite()
        payload = build_commodity_intel_payload(elite)
        self.assertTrue(payload["resolved"])
        self.assertEqual(payload["commodity_name"], "gold")
        self.assertEqual(payload["rows"], 1)
        self.assertEqual(payload["max_age_hours"], 72)
        self.assertEqual(payload["owned_permits"], ["sol"])

    def test_build_commodity_intel_payload_uses_explicit_request(self) -> None:
        elite = self._elite()
        route_request = types.SimpleNamespace(max_age_hours=24, cargo_capacity=64)
        payload = build_commodity_intel_payload(elite, "palladium", route_request)
        self.assertEqual(payload["commodity_name"], "palladium")
        self.assertEqual(payload["max_age_hours"], 24)


if __name__ == "__main__":
    unittest.main()
