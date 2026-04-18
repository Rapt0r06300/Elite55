from __future__ import annotations

import asyncio
from typing import Any


def build_access_error(label: str) -> dict[str, Any]:
    return {"systems_checked": 0, "systems_blocked": 0, "errors": [f"{label}: access lookup failed"]}


async def refresh_access_for_systems(elite_main: Any, systems: list[str], *, label: str) -> dict[str, Any]:
    if not systems:
        return {"systems_checked": 0, "systems_blocked": 0, "errors": []}
    try:
        return await asyncio.to_thread(elite_main.edsm_client.refresh_system_accesses, systems)
    except Exception:
        return build_access_error(label)


def refresh_market_for_current_station(elite_main: Any, market_id: int | None) -> dict[str, int]:
    stats = {"spansh_rows": 0, "edsm_rows": 0}
    if not market_id:
        return stats
    try:
        stats["spansh_rows"] = elite_main.spansh_client.refresh_station(int(market_id))
    except Exception:
        stats["spansh_rows"] = 0
    try:
        stats["edsm_rows"] = elite_main.edsm_client.refresh_market(int(market_id))
    except Exception:
        stats["edsm_rows"] = 0
    return stats


def resolve_center_system(elite_main: Any, requested_system: str | None) -> str | None:
    center_system = requested_system or elite_main.repo.get_state("current_system")
    if not center_system:
        return None
    resolved = elite_main.repo.resolve_system(center_system)
    return resolved.get("name") if resolved else center_system
