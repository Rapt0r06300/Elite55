from __future__ import annotations

import types
import unittest

from app.lookup_context_service import (
    build_names_payload,
    build_refresh_names_payload,
    build_suggest_payload,
    build_trader_memory_payload,
    toggle_trader_favorite,
    track_trader_memory,
)


class LookupContextServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.build_suggestions = lambda q, **kwargs: [{"label": q, "scope": kwargs.get("scope")}]
        elite.build_engine_status = lambda: {"phase": "ready"}
        elite.trader_memory_snapshot = lambda: {"favorites": {}, "recents": {}}
        elite.remember_trader_selection = lambda *args, **kwargs: None
        elite.toggle_trader_favorite = lambda *args, **kwargs: {"favorites": {"commodity": [args[1]]}}
        elite.name_library_service = types.SimpleNamespace(refresh=lambda: {"entries_total": 12})
        elite.repo = types.SimpleNamespace(
            name_library_summary=lambda: {"total": 12},
            search_name_library=lambda **kwargs: [{"lookup_key": "gold", "query": kwargs.get("query", "")}],
        )
        return elite

    def test_build_suggest_payload_returns_engine_status(self) -> None:
        elite = self._elite()
        result = build_suggest_payload(elite, "gold", scope="commodity")
        self.assertEqual(result["results"][0]["label"], "gold")
        self.assertEqual(result["engine_status"]["phase"], "ready")

    def test_build_trader_memory_payload_returns_snapshot(self) -> None:
        elite = self._elite()
        result = build_trader_memory_payload(elite)
        self.assertIn("favorites", result)

    def test_track_and_toggle_memory_delegate(self) -> None:
        elite = self._elite()
        payload = types.SimpleNamespace(kind="commodity", entity_id="gold", label="Or", secondary=None, extra=None)
        tracked = track_trader_memory(elite, payload)
        toggled = toggle_trader_favorite(elite, payload)
        self.assertIn("favorites", tracked)
        self.assertIn("commodity", toggled["favorites"])

    def test_build_refresh_names_payload_returns_summary(self) -> None:
        elite = self._elite()
        result = build_refresh_names_payload(elite)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["total"], 12)

    def test_build_names_payload_returns_results(self) -> None:
        elite = self._elite()
        result = build_names_payload(elite, q="gold", limit=5)
        self.assertEqual(result["results"][0]["lookup_key"], "gold")


if __name__ == "__main__":
    unittest.main()
