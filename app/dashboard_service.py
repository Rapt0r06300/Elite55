from __future__ import annotations

from typing import Any

from app.route_engine import build_route_context


def build_dashboard_payload(
    elite_main: Any,
    route_request: Any | None = None,
) -> dict[str, Any]:
    context = build_route_context(elite_main, route_request)
    dashboard = elite_main.build_trade_dashboard(
        context.filters,
        player=context.player,
        all_rows=context.rows,
        owned_permits=context.owned_permits,
        player_position=context.player_position,
    )
    return elite_main.enrich_dashboard_payload(dashboard, context.request, context.owned_permits)


def install_dashboard_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_dashboard_service_installed", False):
        return

    def patched_build_dashboard_payload(route_request: Any | None = None) -> dict[str, Any]:
        return build_dashboard_payload(elite_main, route_request)

    elite_main.build_dashboard_payload = patched_build_dashboard_payload
    elite_main.app.state.elite55_dashboard_service_installed = True
