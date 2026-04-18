from __future__ import annotations

from typing import Any


def build_dashboard_payload(
    elite_main: Any,
    route_request: Any | None = None,
) -> dict[str, Any]:
    request = route_request or elite_main.default_route_request()
    filters = elite_main.build_filters(request)
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
    return elite_main.enrich_dashboard_payload(dashboard, request, owned_permits)


def install_dashboard_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_dashboard_service_installed", False):
        return

    def patched_build_dashboard_payload(route_request: Any | None = None) -> dict[str, Any]:
        return build_dashboard_payload(elite_main, route_request)

    elite_main.build_dashboard_payload = patched_build_dashboard_payload
    elite_main.app.state.elite55_dashboard_service_installed = True
