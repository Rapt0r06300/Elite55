from __future__ import annotations

import asyncio
import types
import unittest

from fastapi import FastAPI

from app.app_event_patch import patch_app_event_handler
from app.runtime_api_service import (
    build_eddn_start_response,
    build_eddn_stop_response,
    build_health_response,
    install_runtime_api_service_patches,
)


class _FakeRepo:
    def commodity_price_count(self):
        return 42

    def name_library_summary(self):
        return {"total": 12}


class _FakeLocalSyncService:
    def __init__(self) -> None:
        self.bootstrap_calls = 0
        self.start_calls = 0
        self.stop_calls = 0

    def bootstrap(self):
        self.bootstrap_calls += 1
        return {"ok": True}

    async def start(self):
        self.start_calls += 1
        return {"running": True}

    async def stop(self):
        self.stop_calls += 1
        return {"running": False}


class RuntimeApiServiceTests(unittest.TestCase):
    def _elite(self):
        listener_events: list[str] = []

        async def delayed_background_startup():
            listener_events.append("delayed")

        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.build_engine_status = lambda: {"phase": "ready"}
        elite.eddn_listener = types.SimpleNamespace(
            start=lambda: listener_events.append("start") or {"running": True},
            stop=lambda: listener_events.append("stop") or {"running": False},
        )
        elite.local_sync_service = _FakeLocalSyncService()
        elite.name_library_service = types.SimpleNamespace(refresh=lambda: {"entries_total": 12})
        elite.delayed_background_startup = delayed_background_startup
        elite.logger = types.SimpleNamespace(exception=lambda *args, **kwargs: None)
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        elite._listener_events = listener_events
        return elite

    def test_build_health_response_returns_runtime_summary(self) -> None:
        elite = self._elite()
        result = build_health_response(elite)
        self.assertTrue(result["ok"])
        self.assertEqual(result["market_rows"], 42)
        self.assertEqual(result["name_library_total"], 12)

    def test_build_eddn_responses_delegate_to_listener(self) -> None:
        elite = self._elite()
        started = build_eddn_start_response(elite)
        stopped = build_eddn_stop_response(elite)
        self.assertTrue(started["ok"])
        self.assertTrue(stopped["ok"])
        self.assertIn("start", elite._listener_events)
        self.assertIn("stop", elite._listener_events)

    def test_patch_app_event_handler_replaces_named_handler(self) -> None:
        app = FastAPI()

        @app.on_event("startup")
        async def startup_event():
            return None

        async def replacement():
            return None

        patched = patch_app_event_handler(app, "startup", "startup_event", replacement)
        self.assertTrue(patched)
        self.assertIs(app.router.on_startup[0], replacement)

    def test_install_runtime_api_service_patches_rewires_routes_and_events(self) -> None:
        app = FastAPI()

        @app.get("/api/health")
        async def old_health():
            return {"old": True}

        @app.post("/api/eddn/start")
        async def old_eddn_start():
            return {"old": True}

        @app.post("/api/eddn/stop")
        async def old_eddn_stop():
            return {"old": True}

        @app.on_event("startup")
        async def startup_event():
            return None

        @app.on_event("shutdown")
        async def shutdown_event():
            return None

        elite = self._elite()
        elite.app = app
        install_runtime_api_service_patches(elite)

        health_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/health")
        start_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/eddn/start")
        stop_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/eddn/stop")

        health_result = asyncio.run(health_route.endpoint())
        start_result = asyncio.run(start_route.endpoint())
        stop_result = asyncio.run(stop_route.endpoint())
        asyncio.run(app.router.on_startup[0]())
        asyncio.run(app.router.on_shutdown[0]())

        self.assertTrue(health_result["ok"])
        self.assertTrue(start_result["ok"])
        self.assertTrue(stop_result["ok"])
        self.assertEqual(elite.local_sync_service.bootstrap_calls, 1)
        self.assertEqual(elite.local_sync_service.start_calls, 1)
        self.assertEqual(elite.local_sync_service.stop_calls, 1)


if __name__ == "__main__":
    unittest.main()
