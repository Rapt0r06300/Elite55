from __future__ import annotations

from typing import Any

from app.engine_state_service import (
    build_engine_status as build_engine_status_helper,
    build_engine_status_from_values as build_engine_status_from_values_helper,
    sources_payload as build_sources_payload,
)


def build_engine_status_from_values(
    elite_main: Any,
    rows: int,
    name_summary: dict[str, Any],
    local_status: dict[str, Any],
    current_market: dict[str, Any],
    current_system: str | None,
) -> dict[str, Any]:
    return build_engine_status_from_values_helper(
        elite_main,
        rows,
        name_summary,
        local_status,
        current_market,
        current_system,
    )


def build_engine_status(elite_main: Any) -> dict[str, Any]:
    return build_engine_status_helper(elite_main)


def dashboard_defaults(elite_main: Any) -> dict[str, Any]:
    repo = elite_main.repo
    return {
        "max_distance": 40,
        "max_days_ago": 7,
        "max_systems": 20,
        "max_age_hours": 72,
        "max_station_distance_ls": 5000,
        "min_profit_unit": 1000,
        "min_buy_stock": 0,
        "min_sell_demand": 0,
        "max_results": 25,
        "preferred_pad_size": repo.get_state("preferred_pad_size", "M"),
        "no_surprise": False,
    }


def build_dashboard_context(elite_main: Any, owned_permits: set[str] | None = None) -> dict[str, Any]:
    permits = owned_permits if owned_permits is not None else elite_main.known_owned_permits()
    return {
        "local_sync": elite_main.local_sync_service.status(),
        "eddn": elite_main.eddn_listener.status(),
        "nav_route": elite_main.nav_route_payload(),
        "combat_support": elite_main.combat_support_payload(),
        "name_library": elite_main.repo.name_library_summary(),
        "engine_status": build_engine_status(elite_main),
        "trader_memory": elite_main.trader_memory_snapshot(),
        "sources": build_sources_payload(elite_main),
        "defaults": dashboard_defaults(elite_main),
        "journal_dir": str(elite_main.JOURNAL_DIR),
        "game_dir": str(elite_main.GAME_DIR) if getattr(elite_main, "GAME_DIR", None) else None,
        "owned_permits": sorted(permits),
        "owned_permit_labels": elite_main.known_owned_permit_labels(),
    }


def enrich_dashboard_payload(
    elite_main: Any,
    data: dict[str, Any],
    route_request: Any,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    enriched = dict(data)
    enriched.update(build_dashboard_context(elite_main, owned_permits))
    return enriched


def build_local_pulse_payload(elite_main: Any) -> dict[str, Any]:
    player = elite_main.player_runtime_snapshot(elite_main.repo.get_all_state())
    local_sync = elite_main.local_sync_service.status()
    current_market = elite_main.repo.current_market()
    name_library = elite_main.repo.name_library_summary()
    market_rows = elite_main.repo.commodity_price_count()
    current_system = player.get("current_system") or elite_main.repo.get_state("current_system")
    return {
        "player": player,
        "current_market": current_market,
        "local_sync": local_sync,
        "eddn": elite_main.eddn_listener.status(),
        "name_library": name_library,
        "engine_status": build_engine_status_from_values(elite_main, market_rows, name_library, local_sync, current_market, current_system),
        "sources": build_sources_payload(elite_main),
        "nav_route": elite_main.nav_route_payload(),
        "combat_support": elite_main.combat_support_payload(),
        "journal_dir": str(elite_main.JOURNAL_DIR),
        "game_dir": str(elite_main.GAME_DIR) if getattr(elite_main, "GAME_DIR", None) else None,
        "owned_permits": sorted(elite_main.known_owned_permits()),
        "owned_permit_labels": elite_main.known_owned_permit_labels(),
        "dataset": {
            "rows": market_rows,
        },
    }


def install_pulse_context_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_pulse_context_service_installed", False):
        return

    elite_main.sources_payload = lambda: build_sources_payload(elite_main)
    elite_main.build_engine_status_from_values = lambda rows, name_summary, local_status, current_market, current_system: build_engine_status_from_values(
        elite_main,
        rows,
        name_summary,
        local_status,
        current_market,
        current_system,
    )
    elite_main.build_engine_status = lambda: build_engine_status(elite_main)
    elite_main.enrich_dashboard_payload = lambda data, route_request, owned_permits=None: enrich_dashboard_payload(
        elite_main,
        data,
        route_request,
        owned_permits,
    )
    elite_main.local_pulse_payload = lambda: build_local_pulse_payload(elite_main)
    elite_main.app.state.elite55_pulse_context_service_installed = True
