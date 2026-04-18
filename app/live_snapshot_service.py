from __future__ import annotations

from typing import Any

from app.commodity_intel_service import build_commodity_intel_payload, resolve_commodity_query
from app.mission_intel_service import build_mission_intel_payload, resolve_mission_quantity


def build_local_pulse_payload(elite_main: Any) -> dict[str, Any]:
    player = elite_main.player_runtime_snapshot(elite_main.repo.get_all_state())
    local_sync = elite_main.local_sync_service.status()
    current_market = elite_main.repo.current_market()
    name_library = elite_main.repo.name_library_summary()
    market_rows = elite_main.repo.commodity_price_count()
    current_system = player.get("current_system") or elite_main.repo.get_state("current_system")
    permit_labels = elite_main.known_owned_permit_labels()
    return {
        "player": player,
        "current_market": current_market,
        "local_sync": local_sync,
        "eddn": elite_main.eddn_listener.status(),
        "name_library": name_library,
        "engine_status": elite_main.build_engine_status_from_values(
            market_rows,
            name_library,
            local_sync,
            current_market,
            current_system,
        ),
        "sources": elite_main.sources_payload(),
        "nav_route": elite_main.nav_route_payload(),
        "combat_support": elite_main.combat_support_payload(),
        "journal_dir": str(elite_main.JOURNAL_DIR),
        "game_dir": str(elite_main.GAME_DIR) if elite_main.GAME_DIR else None,
        "owned_permits": sorted(elite_main.known_owned_permits()),
        "owned_permit_labels": permit_labels,
        "dataset": {
            "rows": market_rows,
        },
    }


def build_live_snapshot_payload(elite_main: Any, payload: Any | None = None) -> dict[str, Any]:
    snapshot = payload or elite_main.LiveSnapshotRequest()
    route_request = snapshot.route or elite_main.default_route_request()
    filters = elite_main.build_filters(route_request)
    player = elite_main.player_runtime_snapshot(elite_main.repo.get_all_state())
    all_rows = elite_main.repo.filtered_trade_rows(filters)
    owned_permits = elite_main.known_owned_permits()
    player_position = elite_main.repo.system_position(player.get("current_system"))

    dashboard = elite_main.build_trade_dashboard(
        filters,
        player=player,
        all_rows=all_rows,
        owned_permits=owned_permits,
        player_position=player_position,
    )
    dashboard = elite_main.enrich_dashboard_payload(dashboard, route_request, owned_permits)

    commodity_query = resolve_commodity_query(elite_main, snapshot.commodity_query, player)
    commodity_intel = build_commodity_intel_payload(
        elite_main,
        commodity_query,
        route_request,
    )

    mission_payload = snapshot.mission
    mission_query = commodity_query
    mission_quantity = resolve_mission_quantity(None, player, filters)
    mission_target_system = None
    mission_target_station = None
    if mission_payload is not None:
        mission_query = mission_payload.commodity_query
        mission_quantity = mission_payload.quantity
        mission_target_system = mission_payload.target_system
        mission_target_station = mission_payload.target_station
    mission_intel = build_mission_intel_payload(
        elite_main,
        mission_query,
        mission_quantity,
        target_system=mission_target_system,
        target_station=mission_target_station,
        route_request=route_request,
    )
    return {
        "dashboard": dashboard,
        "commodity_intel": commodity_intel,
        "mission_intel": mission_intel,
    }


def install_live_snapshot_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_live_snapshot_service_installed", False):
        return

    def patched_local_pulse_payload() -> dict[str, Any]:
        return build_local_pulse_payload(elite_main)

    def patched_build_live_snapshot_payload(payload: Any | None = None) -> dict[str, Any]:
        return build_live_snapshot_payload(elite_main, payload)

    elite_main.local_pulse_payload = patched_local_pulse_payload
    elite_main.build_live_snapshot_payload = patched_build_live_snapshot_payload
    elite_main.app.state.elite55_live_snapshot_service_installed = True
