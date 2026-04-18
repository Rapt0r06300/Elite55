from __future__ import annotations

import types
import unittest

from app.dashboard_api_service import build_dashboard_response


class DashboardApiServiceTests(unittest.TestCase):
    def test_uses_build_dashboard_payload_when_available(self) -> None:
        elite = types.SimpleNamespace()
        elite.build_dashboard_payload = lambda route_request=None: {"source": "builder", "request": route_request}
        elite.dashboard_payload = lambda route_request=None: {"source": "fallback", "request": route_request}
        result = build_dashboard_response(elite, "demo")
        self.assertEqual(result["source"], "builder")
        self.assertEqual(result["request"], "demo")

    def test_falls_back_to_dashboard_payload_when_needed(self) -> None:
        elite = types.SimpleNamespace()
        elite.dashboard_payload = lambda route_request=None: {"source": "fallback", "request": route_request}
        result = build_dashboard_response(elite, "demo")
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["request"], "demo")

    def test_raises_when_no_dashboard_builder_exists(self) -> None:
        elite = types.SimpleNamespace()
        with self.assertRaises(RuntimeError):
            build_dashboard_response(elite)


if __name__ == "__main__":
    unittest.main()
