from __future__ import annotations

import asyncio
import types
import unittest

from app.source_api_service import (
    build_import_journals_response,
    build_refresh_current_market_response,
    build_sync_ardent_response,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.values = {
            "current_system": "Sol",
            "current_market_id": 42,
        }

    def get_state(self, key, default=None):
        return self.values.get(key, default)

    def resolve_system(self, system_name):
        if not system_name:
            return None
        return {"name": system_name}


class SourceApiServiceTests(unittest.TestCase):
    def _elite(self):
        repo = _FakeRepo()
        remembered: list[tuple] = []
        elite = types.SimpleNamespace()
        elite.repo = repo
        elite.HTTPException = RuntimeError
        elite.journal_service = types.SimpleNamespace(import_all=lambda: {"journal_files": 1})
        elite.edsm_client = types.SimpleNamespace(
            refresh_system_accesses=lambda systems: {"systems_checked": len(systems), "systems_blocked": 0, "errors": []},
            refresh_market=lambda market_id: 7,
        )
        elite.spansh_client = types.SimpleNamespace(refresh_station=lambda market_id: 5)
        elite.name_library_service = types.SimpleNamespace(refresh=lambda: {"entries_total": 12})
        elite.ardent_client = types.SimpleNamespace(
            sync_region=lambda **kwargs: asyncio.sleep(0, result={
                "systems_loaded": 1,
                "systems_synced": 1,
                "systems_failed": 0,
                "stations_loaded": 2,
                "market_rows_upserted": 9,
                "systems_considered": [kwargs["center_system"]],
                "errors": [],
            })
        )
        elite.remember_trader_selection = lambda *args, **kwargs: remembered.append((args, kwargs))
        elite.build_dashboard_payload = lambda route_request=None: {"player": {"ship": "Python"}}
        elite.dashboard_payload = lambda route_request=None: {"player": {"ship": "Fallback"}}
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        elite._remembered = remembered
        return elite

    def test_build_import_journals_response_returns_dashboard_and_stats(self) -> None:
        elite = self._elite()
        result = asyncio.run(build_import_journals_response(elite))
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"]["journal_files"], 1)
        self.assertEqual(result["stats"]["name_library"]["entries_total"], 12)
        self.assertIn("dashboard", result)

    def test_build_sync_ardent_response_uses_current_system_and_memory(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(center_system=None, max_distance=10, max_days_ago=3, max_systems=4)
        result = asyncio.run(build_sync_ardent_response(elite, payload))
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"]["systems_considered"], ["Sol"])
        self.assertTrue(elite._remembered)

    def test_build_refresh_current_market_response_returns_market_stats(self) -> None:
        elite = self._elite()
        result = asyncio.run(build_refresh_current_market_response(elite))
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"]["spansh_rows"], 5)
        self.assertEqual(result["stats"]["edsm_rows"], 7)


if __name__ == "__main__":
    unittest.main()
