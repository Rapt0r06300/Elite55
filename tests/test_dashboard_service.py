from __future__ import annotations

import types
import unittest

from app.dashboard_service import build_dashboard_payload


class _FakeRepo:
    def __init__(self) -> None:
        self._state = {
            "current_system": "Sol",
        }

    def get_all_state(self):
        return dict(self._state)

    def system_position(self, _name):
        return {"x": 0, "y": 0, "z": 0}

    def filtered_trade_rows(self, _filters):
        return [{"commodity_symbol": "gold"}, {"commodity_symbol": "silver"}]


class DashboardServiceTests(unittest.TestCase):
    def _elite(self):
        repo = _FakeRepo()
        elite = types.SimpleNamespace()
        elite.repo = repo
        elite.player_runtime_snapshot = lambda state: {"current_system": state.get("current_system")}
        elite.default_route_request = lambda: types.SimpleNamespace(max_age_hours=72, cargo_capacity=128)
        elite.build_filters = lambda request: types.SimpleNamespace(max_age_hours=request.max_age_hours, cargo_capacity=getattr(request, "cargo_capacity", 128))
        elite.known_owned_permits = lambda: {"sol"}
        elite.build_trade_dashboard = lambda filters, **kwargs: {
            "dashboard": True,
            "rows": len(kwargs.get("all_rows") or []),
            "current_system": kwargs.get("player", {}).get("current_system"),
            "max_age_hours": filters.max_age_hours,
        }
        elite.enrich_dashboard_payload = lambda dashboard, request, owned_permits: {
            **dashboard,
            "owned_permits": sorted(owned_permits),
            "request_age": request.max_age_hours,
        }
        return elite

    def test_build_dashboard_payload_uses_defaults(self) -> None:
        elite = self._elite()
        payload = build_dashboard_payload(elite)
        self.assertTrue(payload["dashboard"])
        self.assertEqual(payload["rows"], 2)
        self.assertEqual(payload["current_system"], "Sol")
        self.assertEqual(payload["owned_permits"], ["sol"])
        self.assertEqual(payload["request_age"], 72)

    def test_build_dashboard_payload_uses_explicit_request(self) -> None:
        elite = self._elite()
        request = types.SimpleNamespace(max_age_hours=24, cargo_capacity=64)
        payload = build_dashboard_payload(elite, request)
        self.assertEqual(payload["max_age_hours"], 24)
        self.assertEqual(payload["request_age"], 24)


if __name__ == "__main__":
    unittest.main()
