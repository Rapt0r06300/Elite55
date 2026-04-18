from __future__ import annotations

import asyncio
import types
import unittest

from fastapi import FastAPI

from app.dashboard_api_service import build_dashboard_response, install_dashboard_api_service_patches


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

    def test_install_dashboard_api_service_patches_rewires_dashboard_route(self) -> None:
        app = FastAPI()

        @app.get("/api/dashboard")
        async def old_dashboard():
            return {"old": True}

        elite = types.SimpleNamespace()
        elite.app = app
        elite.build_dashboard_payload = lambda route_request=None: {"source": "builder"}
        install_dashboard_api_service_patches(elite)

        dashboard_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/dashboard")
        result = asyncio.run(dashboard_route.endpoint())
        self.assertEqual(result["source"], "builder")


if __name__ == "__main__":
    unittest.main()
