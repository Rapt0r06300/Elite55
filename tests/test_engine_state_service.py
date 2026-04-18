from __future__ import annotations

import types
import unittest

from app.engine_state_service import (
    build_engine_status,
    build_engine_status_from_values,
    install_engine_state_service_patches,
    sources_payload,
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
            "current_system": "Sol",
        }

    def get_state(self, key, default=None):
        return self.values.get(key, default)

    def commodity_price_count(self):
        return 900

    def name_library_summary(self):
        return {"total": 12}

    def current_market(self):
        return {"station_name": "Galileo"}


class EngineStateServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.local_sync_service = types.SimpleNamespace(status=lambda: {"running": True})
        elite.background_flags = {"remote_seed_running": False}
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_sources_payload_reads_repo_values(self) -> None:
        elite = self._elite()
        result = sources_payload(elite)
        self.assertEqual(result["journal_last_import"], "journal")
        self.assertEqual(result["local_last_event"], "event")

    def test_build_engine_status_from_values_returns_ready(self) -> None:
        elite = self._elite()
        result = build_engine_status_from_values(elite, 900, {"total": 12}, {"running": True}, {"station_name": "Galileo"}, "Sol")
        self.assertEqual(result["phase"], "ready")
        self.assertTrue(result["ready"])

    def test_build_engine_status_uses_repo_and_services(self) -> None:
        elite = self._elite()
        result = build_engine_status(elite)
        self.assertEqual(result["current_system"], "Sol")
        self.assertEqual(result["current_market"], "Galileo")

    def test_install_engine_state_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_engine_state_service_patches(elite)
        self.assertEqual(elite.sources_payload()["ardent_last_sync"], "ardent")
        self.assertEqual(elite.build_engine_status()["phase"], "ready")


if __name__ == "__main__":
    unittest.main()
