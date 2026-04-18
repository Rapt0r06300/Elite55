from __future__ import annotations

import asyncio
import types
import unittest

from app.background_seed_service import install_background_seed_service_patches, startup_seed_remote_data


class BackgroundSeedServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.background_flags = {"remote_seed_running": False}
        elite.repo = types.SimpleNamespace(
            get_state=lambda key, default=None: {"current_system": "Sol", "current_market_id": None, "source_ardent_last_sync": None}.get(key, default),
            commodity_price_count=lambda: 0,
        )
        elite.age_hours = lambda value: None
        elite.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None)
        elite.asyncio = asyncio
        elite.ardent_client = types.SimpleNamespace(sync_region=self._sync_region)
        elite.edsm_client = types.SimpleNamespace(refresh_system_accesses=lambda systems: {"systems_checked": len(systems)})
        elite.spansh_client = types.SimpleNamespace(refresh_station=lambda market_id: 0)
        elite.BACKGROUND_START_DELAY_SECONDS = 0
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        self.synced = False
        return elite

    async def _sync_region(self, *args, **kwargs):
        self.synced = True
        return {"ok": True}

    def test_startup_seed_remote_data_runs_and_clears_flag(self) -> None:
        elite = self._elite()
        asyncio.run(startup_seed_remote_data(elite))
        self.assertTrue(self.synced)
        self.assertFalse(elite.background_flags["remote_seed_running"])

    def test_install_background_seed_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_background_seed_service_patches(elite)
        asyncio.run(elite.startup_seed_remote_data())
        self.assertFalse(elite.background_flags["remote_seed_running"])


if __name__ == "__main__":
    unittest.main()
