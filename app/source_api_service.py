from __future__ import annotations

from typing import Any

from app.api_route_patch import patch_api_route
from app.dashboard_api_service import build_dashboard_response
from app.source_context_service import (
    build_import_journal_stats,
    build_refresh_current_market_stats,
    build_sync_ardent_stats,
)


async def build_import_journals_response(elite_main: Any) -> dict[str, Any]:
    stats = await build_import_journal_stats(elite_main)
    return {"ok": True, "stats": stats, "dashboard": build_dashboard_response(elite_main)}


async def build_sync_ardent_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    _, stats = await build_sync_ardent_stats(elite_main, payload)
    return {"ok": True, "stats": stats, "dashboard": build_dashboard_response(elite_main)}


async def build_refresh_current_market_response(elite_main: Any) -> dict[str, Any]:
    stats = await build_refresh_current_market_stats(elite_main)
    return {"ok": True, "stats": stats, "dashboard": build_dashboard_response(elite_main)}


def install_source_api_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_source_api_service_installed", False):
        return

    elite_main.import_journals_response = lambda: build_import_journals_response(elite_main)
    elite_main.sync_ardent_response = lambda payload: build_sync_ardent_response(elite_main, payload)
    elite_main.refresh_current_market_response = lambda: build_refresh_current_market_response(elite_main)

    async def api_import_journals_wrapper() -> dict[str, Any]:
        return await elite_main.import_journals_response()

    async def api_sync_ardent_wrapper(payload: Any) -> dict[str, Any]:
        return await elite_main.sync_ardent_response(payload)

    async def api_refresh_current_market_wrapper() -> dict[str, Any]:
        return await elite_main.refresh_current_market_response()

    patch_api_route(elite_main.app, "/api/import/journals", {"POST"}, api_import_journals_wrapper)
    patch_api_route(elite_main.app, "/api/sync/ardent", {"POST"}, api_sync_ardent_wrapper)
    patch_api_route(elite_main.app, "/api/refresh/current-market", {"POST"}, api_refresh_current_market_wrapper)

    elite_main.app.state.elite55_source_api_service_installed = True
