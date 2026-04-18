from __future__ import annotations

from typing import Any

from app.route_engine import RouteContext, ensure_route_context
from app.trade_query_service import resolve_focus_commodity_query, resolve_mission_quantity


def resolve_mission_query(
    elite_main: Any,
    explicit_query: str | None = None,
    player: dict[str, Any] | None = None,
) -> str:
    return resolve_focus_commodity_query(elite_main, explicit_query, player)


def build_mission_intel_payload(
    elite_main: Any,
    commodity_query: str | None = None,
    quantity: int | None = None,
    *,
    target_system: str | None = None,
    target_station: str | None = None,
    route_request: Any | None = None,
    route_context: RouteContext | None = None,
) -> dict[str, Any]:
    context = ensure_route_context(elite_main, route_request, route_context)
    resolved_query = resolve_mission_query(elite_main, commodity_query, context.player)
    resolved_quantity = resolve_mission_quantity(quantity, context.player, context.filters)
    return elite_main.build_mission_intel(
        resolved_query,
        resolved_quantity,
        context.filters,
        target_system=target_system,
        target_station=target_station,
        all_rows=context.rows,
        player_position=context.player_position,
        owned_permits=context.owned_permits,
    )


def install_mission_intel_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_mission_intel_service_installed", False):
        return

    def patched_build_mission_intel_payload(
        commodity_query: str | None = None,
        quantity: int | None = None,
        *,
        target_system: str | None = None,
        target_station: str | None = None,
        route_request: Any | None = None,
        route_context: RouteContext | None = None,
    ) -> dict[str, Any]:
        return build_mission_intel_payload(
            elite_main,
            commodity_query,
            quantity,
            target_system=target_system,
            target_station=target_station,
            route_request=route_request,
            route_context=route_context,
        )

    elite_main.build_mission_intel_payload = patched_build_mission_intel_payload
    elite_main.app.state.elite55_mission_intel_service_installed = True
