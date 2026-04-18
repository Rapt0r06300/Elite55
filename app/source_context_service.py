from __future__ import annotations

import asyncio
from typing import Any


def access_fallback(label: str) -> dict[str, Any]:
    return {
        "systems_checked": 0,
        "systems_blocked": 0,
        "errors": [f"{label}: access lookup failed"],
    }


async def refresh_access_for_systems(elite_main: Any, systems: list[str], *, label: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(elite_main.edsm_client.refresh_system_accesses, systems)
    except Exception:
        return access_fallback(label)


async def build_import_journal_stats(elite_main: Any) -> dict[str, Any]:
    stats = elite_main.journal_service.import_all()
    current_system = elite_main.repo.get_state("current_system")
    if current_system:
        stats["access"] = await refresh_access_for_systems(elite_main, [str(current_system)], label="current_system")
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
    return stats


async def build_sync_ardent_stats(elite_main: Any, payload: Any) -> tuple[str, dict[str, Any]]:
    center_system = payload.center_system or elite_main.repo.get_state("current_system")
    if not center_system:
        raise elite_main.HTTPException(status_code=400, detail="Systeme courant inconnu. Importe les journaux d abord.")
    resolved_center = elite_main.repo.resolve_system(center_system)
    center_system = resolved_center.get("name") if resolved_center else center_system
    elite_main.remember_trader_selection("system", center_system, center_system)
    stats = await elite_main.ardent_client.sync_region(
        center_system=center_system,
        max_distance=payload.max_distance,
        max_days_ago=payload.max_days_ago,
        max_systems=payload.max_systems,
    )
    stats["access"] = await refresh_access_for_systems(elite_main, stats.get("systems_considered", []), label="region")
    return center_system, stats


async def build_refresh_current_market_stats(elite_main: Any) -> dict[str, Any]:
    market_id = elite_main.repo.get_state("current_market_id")
    if not market_id:
        raise elite_main.HTTPException(status_code=400, detail="Aucun marche courant connu.")
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
        stats["access"] = await refresh_access_for_systems(elite_main, [str(current_system)], label="current_system")
    return stats
