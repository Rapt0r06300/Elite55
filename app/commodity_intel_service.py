from __future__ import annotations

from typing import Any

from app.route_engine import RouteContext, ensure_route_context
from app.trade_query_service import resolve_focus_commodity_query


def resolve_commodity_query(elite_main: Any, explicit_query: str | None = None, player: dict[str, Any] | None = None) -> str:
    return resolve_focus_commodity_query(elite_main, explicit_query, player)


def build_commodity_intel_payload(
    elite_main: Any,
    commodity_query: str | None = None,
    route_request: Any | None = None,
    route_context: RouteContext | None = None,
    *,
    origin_system: str | None = None,
    origin_station: str | None = None,
    target_system: str | None = None,
    target_station: str | None = None,
) -> dict[str, Any]:
    context = ensure_route_context(elite_main, route_request, route_context)
    resolved_query = resolve_commodity_query(elite_main, commodity_query, context.player)
    return elite_main.build_commodity_intel(
        resolved_query,
        context.filters,
        all_rows=context.rows,
        player_position=context.player_position,
        owned_permits=context.owned_permits,
        origin_system=origin_system,
        origin_station=origin_station,
        target_system=target_system,
        target_station=target_station,
    )


def install_commodity_intel_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_commodity_intel_service_installed", False):
        return

    def patched_build_commodity_intel_payload(
        commodity_query: str | None = None,
        route_request: Any | None = None,
        route_context: RouteContext | None = None,
        *,
        origin_system: str | None = None,
        origin_station: str | None = None,
        target_system: str | None = None,
        target_station: str | None = None,
    ) -> dict[str, Any]:
        return build_commodity_intel_payload(
            elite_main,
            commodity_query,
            route_request,
            route_context,
            origin_system=origin_system,
            origin_station=origin_station,
            target_system=target_system,
            target_station=target_station,
        )

    elite_main.build_commodity_intel_payload = patched_build_commodity_intel_payload
    elite_main.app.state.elite55_commodity_intel_service_installed = True
