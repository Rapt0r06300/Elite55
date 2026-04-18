from __future__ import annotations

import asyncio
import types
import unittest

from fastapi import FastAPI

from app.lookup_api_service import (
    build_names_response,
    build_refresh_names_response,
    build_suggest_response,
    build_trader_memory_response,
    install_lookup_api_service_patches,
    toggle_trader_favorite_response,
    track_trader_memory_response,
)


class LookupApiServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.build_suggestions = lambda q, **kwargs: [{"label": q, "scope": kwargs.get("scope")}]
        elite.build_engine_status = lambda: {"phase": "ready"}
        elite.trader_memory_snapshot = lambda: {"favorites": {}, "recents": {}}
        elite.remember_trader_selection = lambda *args, **kwargs: {"tracked": args[1]}
        elite.toggle_trader_favorite = lambda *args, **kwargs: {"favorites": {"commodity": [args[1]]}}
        elite.name_library_service = types.SimpleNamespace(refresh=lambda: {"entries_total": 12})
        elite.repo = types.SimpleNamespace(
            name_library_summary=lambda: {"total": 12},
            search_name_library=lambda **kwargs: [{"lookup_key": "gold", "query": kwargs.get("query", "")}],
        )
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_build_suggest_response_wraps_results(self) -> None:
        elite = self._elite()
        result = build_suggest_response(elite, "gold", scope="commodity")
        self.assertEqual(result["query"], "gold")
        self.assertEqual(result["results"][0]["label"], "gold")
        self.assertEqual(result["engine_status"]["phase"], "ready")

    def test_build_trader_memory_response_returns_snapshot(self) -> None:
        elite = self._elite()
        result = build_trader_memory_response(elite)
        self.assertIn("favorites", result)

    def test_track_and_toggle_memory_delegate_to_runtime(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(kind="commodity", entity_id="gold", label="Or", secondary=None, extra=None)
        tracked = track_trader_memory_response(elite, payload)
        toggled = toggle_trader_favorite_response(elite, payload)
        self.assertIn("favorites", tracked)
        self.assertIn("commodity", toggled["favorites"])

    def test_build_refresh_names_response_returns_summary(self) -> None:
        elite = self._elite()
        result = build_refresh_names_response(elite)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["total"], 12)

    def test_build_names_response_returns_results(self) -> None:
        elite = self._elite()
        result = build_names_response(elite, q="gold", limit=5)
        self.assertEqual(result["results"][0]["lookup_key"], "gold")

    def test_install_lookup_api_service_patches_rewires_routes(self) -> None:
        app = FastAPI()

        @app.get("/api/suggest")
        async def old_suggest(q: str):
            return {"old": q}

        @app.get("/api/trader-memory")
        async def old_memory():
            return {"old": True}

        elite = self._elite()
        elite.app = app
        install_lookup_api_service_patches(elite)

        suggest_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/suggest")
        memory_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/trader-memory")

        suggest_result = asyncio.run(suggest_route.endpoint("gold"))
        memory_result = asyncio.run(memory_route.endpoint())

        self.assertEqual(suggest_result["results"][0]["label"], "gold")
        self.assertIn("favorites", memory_result)


if __name__ == "__main__":
    unittest.main()
