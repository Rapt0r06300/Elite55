from __future__ import annotations

from typing import Any


async def startup_seed_remote_data(elite_main: Any) -> None:
    elite_main.background_flags["remote_seed_running"] = True
    try:
        current_system = str(elite_main.repo.get_state("current_system") or "").strip()
        if not current_system:
            return
        current_market_id = elite_main.repo.get_state("current_market_id")
        existing_rows = elite_main.repo.commodity_price_count()
        last_sync = elite_main.repo.get_state("source_ardent_last_sync")
        last_sync_age = elite_main.age_hours(last_sync) or 9999
        if current_market_id:
            elite_main.logger.info("Startup current-market refresh for %s", current_market_id)
            try:
                await elite_main.asyncio.to_thread(elite_main.spansh_client.refresh_station, int(current_market_id))
            except Exception:
                elite_main.logger.exception("Startup Spansh refresh failed for market %s", current_market_id)
            try:
                await elite_main.asyncio.to_thread(elite_main.edsm_client.refresh_market, int(current_market_id))
            except Exception:
                elite_main.logger.exception("Startup EDSM refresh failed for market %s", current_market_id)
            try:
                await elite_main.asyncio.to_thread(elite_main.edsm_client.refresh_system_accesses, [current_system])
            except Exception:
                elite_main.logger.exception("Startup access refresh failed for %s", current_system)
            return
        if existing_rows > 0 and last_sync_age <= 12.0:
            return
        elite_main.logger.info("Startup remote seed sync for %s", current_system)
        await elite_main.ardent_client.sync_region(current_system, 5, 1, 2)
        try:
            await elite_main.asyncio.to_thread(elite_main.edsm_client.refresh_system_accesses, [current_system])
        except Exception:
            elite_main.logger.exception("Startup access refresh failed for %s", current_system)
    except Exception:
        elite_main.logger.exception("Startup remote seed sync failed")
    finally:
        elite_main.background_flags["remote_seed_running"] = False


async def delayed_background_startup(elite_main: Any) -> None:
    await elite_main.asyncio.sleep(elite_main.BACKGROUND_START_DELAY_SECONDS)
    await startup_seed_remote_data(elite_main)


def install_background_seed_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_background_seed_service_installed", False):
        return

    elite_main.startup_seed_remote_data = lambda: startup_seed_remote_data(elite_main)
    elite_main.delayed_background_startup = lambda: delayed_background_startup(elite_main)
    elite_main.app.state.elite55_background_seed_service_installed = True
