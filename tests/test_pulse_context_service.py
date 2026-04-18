from __future__ import annotations

import types
import unittest

from app.pulse_context_service import (
    build_dashboard_context,
    build_engine_status,
    build_local_pulse_payload,
    build_sources_payload,
    enrich_dashboard_payload,
    install_pulse_context_service_patches,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.values = {
            "source_journal_last_import": "journal",
            "source_ardent_last_sync": "ardent",
            "source_spansh_last_refresh": "spansh",
            "source_edsm_last_refresh": "edsm",
            "source_eddn_last_refresh": "eddn",
            "source_edsm_access_last_refresh": "access",
            "source_local_last_poll": "poll",
            "source_local_last_event": "event",
            "preferred_pad_size": "M",
            "current_system": "Sol",
        }

    def get_state(self, key, default=None):
        return self.values.get(key, default)

    def name_library_summary(self):
        return {"total": 12}

    def commodity_price_count(self):
        return 800

    def current_market(self):
        return {"station_name": "Galileo"}

    def get_all_state(self):
        return {"current_system": "Sol"}


class PulseContextServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.local_sync_service = types.SimpleNamespace(status=lambda: {"running": True})
        elite.eddn_listener = types.SimpleNamespace(status=lambda: {"running": False})
        elite.nav_route_payload = lambda: {"destination_system": "Achenar"}
        elite.combat_support_payload = lambda: {"best_restock": {"station_name": "Galileo"}}
        elite.trader_memory_snapshot = lambda: {"favorites": {}, "recents": {}}
        elite.known_owned_permits = lambda: {"sol"}
        elite.known_owned_permit_labels = lambda: ["Sol"]
        elite.player_runtime_snapshot = lambda state: {"current_system": state.get("current_system")}
        elite.JOURNAL_DIR = "JOURNAL_DIR"
        elite.GAME_DIR = "GAME_DIR"
        elite.background_flags = {"remote_seed_running": False}
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_build_sources_payload_reads_repo_states(self) -> None:
        elite = self._elite()
        result = build_sources_payload(elite)
        self.assertEqual(result["journal_last_import"], "journal")
        self.assertEqual(result["local_last_event"], "event")

    def test_build_engine_status_returns_ready_when_everything_is_ok(self) -> None:
        elite = self._elite()
        result = build_engine_status(elite)
        self.assertEqual(result["phase"], "ready")
        self.assertTrue(result["ready"])

    def test_build_dashboard_context_adds_main_blocks(self) -> None:
        elite = self._elite()
        result = build_dashboard_context(elite)
        self.assertIn("local_sync", result)
        self.assertIn("sources", result)
        self.assertIn("owned_permit_labels", result)

    def test_enrich_dashboard_payload_merges_context(self) -> None:
        elite = self._elite()
        result = enrich_dashboard_payload(elite, {"routes": []}, object())
        self.assertIn("routes", result)
        self.assertIn("engine_status", result)
        self.assertIn("combat_support", result)

    def test_build_local_pulse_payload_returns_full_snapshot(self) -> None:
        elite = self._elite()
        result = build_local_pulse_payload(elite)
        self.assertEqual(result["player"]["current_system"], "Sol")
        self.assertIn("current_market", result)
        self.assertIn("dataset", result)

    def test_install_pulse_context_service_patches_replaces_helpers(self) -> None:
        elite = self._elite()
        install_pulse_context_service_patches(elite)
        self.assertEqual(elite.sources_payload()["journal_last_import"], "journal")
        self.assertEqual(elite.build_engine_status()["phase"], "ready")
        self.assertIn("engine_status", elite.enrich_dashboard_payload({}, object()))
        self.assertIn("current_market", elite.local_pulse_payload())


if __name__ == "__main__":
    unittest.main()
