from __future__ import annotations

import asyncio
from typing import Any

from app.api_route_patch import patch_api_route
from app.dashboard_api_service import build_dashboard_response


async def build_import_journals_response(elite_main: Any) -> dict[str, Any]:
    stats = elite_main.journal_service.import_all()
    current_system = elite_main.repo.get_state("current_system")
    if current_system:
        try:
            stats["access"] = await asyncio.to_thread(elite_main.edsm_client.refresh_system_accesses, [str(current_system)])
        except Exception:
            stats["access"] = {"systems_checked": 0, "systems_blocked": 0, "errors": ["current_system: access lookup failed"]}
    market_id = elite_main.repo.get_state("current_market_id")
    if market_id:
        try:
            stats["spansh_rows"] = elite_main.spansh_client.refresh_station(int(market_id))
        except Exception:
            stats["spansh_rows"] = 0
        try:
            stats["edsm_rows"] = elite_main.edsm_client.refresh_market(int(market_id))
        except Exception:
            stats["edsm_rows"] = 0
    stats["name_library"] = elite_main.name_library_service.refresh()
    return {"ok": True, "stats": stats, "dashboard": build_dashboard_response(elite_main)}


async def build_sync_ardent_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    center_system = payload.center_system or elite_main.repo.get_state("current_system")
    if not center_system:
        raise elite_main.HTTPException(status_code=400, detail="Aucun système courant connu. Importe d'abord les journaux.")
    resolved_center = elite_main.repo.resolve_system(center_system)
    center_system = resolved_center.get("name") if resolved_center else center_system
    elite_main.remember_trader_selection("system", center_system, center_system)
    stats = await elite_main.ardent_client.sync_region(
        center_system=center_system,
        max_distance=payload.max_distance,
        max_days_ago=payload.max_days_ago,
        max_systems=payload.max_systems,
    )
    try:
        stats["access"] = await asyncio.to_thread(elite_main.edsm_client.refresh_system_accesses, stats.get("systems_considered", []))
    except Exception:
        stats["access"] = {"systems_checked": 0, "systems_blocked": 0, "errors": ["region: access lookup failed"]}
    return {"ok": True, "stats": stats, "dashboard": build_dashboard_response(elite_main)}


async def build_refresh_current_market_response(elite_main: Any) -> dict[str, Any]:
    market_id = elite_main.repo.get_state("current_market_id")
    if not market_id:
        raise elite_main.HTTPException(status_code=400, detail="Aucun marché courant connu.")
    stats = {"spansh_rows": 0, "edsm_rows": 0}
    try:
        stats["spansh_rows"] = elite_main.spansh_client.refresh_station(int(market_id))
    except Exception:
        pass
    try:
        stats["edsm_rows"] = elite_main.edsm_client.refresh_market(int(market_id))
    except Exception:
        pass
    current_system = elite_main.repo.get_state("current_system")
    if current_system:
        try:
            stats["access"] = await asyncio.to_thread(elite_main.edsm_client.refresh_system_accesses, [str(current_system)])
        except Exception:
            stats["access"] = {"systems_checked": 0, "systems_blocked": 0, "errors": ["current_system: access lookup failed"]}
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
