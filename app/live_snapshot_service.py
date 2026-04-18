from __future__ import annotations

from typing import Any

from app.commodity_intel_service import build_commodity_intel_payload, resolve_commodity_query
from app.dashboard_service import build_dashboard_payload
from app.mission_intel_service import build_mission_intel_payload, resolve_mission_quantity
from app.pulse_context_service import build_local_pulse_payload
from app.route_engine import build_route_context


def build_live_snapshot_payload(elite_main: Any, payload: Any | None = None) -> dict[str, Any]:
    snapshot = payload or elite_main.LiveSnapshotRequest()
    route_request = snapshot.route or elite_main.default_route_request()
    context = build_route_context(elite_main, route_request)

    dashboard = build_dashboard_payload(
        elite_main,
        context.request,
        context,
    )

    commodity_query = resolve_commodity_query(elite_main, snapshot.commodity_query, context.player)
    commodity_intel = build_commodity_intel_payload(
        elite_main,
        commodity_query,
        context.request,
        context,
    )

    mission_payload = snapshot.mission
    mission_query = commodity_query
    mission_quantity = resolve_mission_quantity(None, context.player, context.filters)
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
        route_request=context.request,
        route_context=context,
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
