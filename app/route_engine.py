from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RouteContext:
    request: Any
    filters: Any
    player: dict[str, Any]
    rows: list[dict[str, Any]]
    owned_permits: set[str]
    player_position: Any


def resolve_route_request(elite_main: Any, route_request: Any | None = None) -> Any:
    return route_request or elite_main.default_route_request()


def build_route_context(elite_main: Any, route_request: Any | None = None) -> RouteContext:
    request = resolve_route_request(elite_main, route_request)
    filters = elite_main.build_filters(request)
    player = elite_main.player_runtime_snapshot(elite_main.repo.get_all_state())
    rows = list(elite_main.repo.filtered_trade_rows(filters))
    owned_permits = set(elite_main.known_owned_permits())
    player_position = elite_main.repo.system_position(player.get("current_system"))
    return RouteContext(
        request=request,
        filters=filters,
        player=player,
        rows=rows,
        owned_permits=owned_permits,
        player_position=player_position,
    )


def route_context_payload(context: RouteContext) -> dict[str, Any]:
    return {
        "request": context.request,
        "filters": context.filters,
        "player": context.player,
        "rows": context.rows,
        "owned_permits": context.owned_permits,
        "player_position": context.player_position,
    }


def install_route_engine_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_route_engine_installed", False):
        return

    def patched_build_route_context(route_request: Any | None = None) -> RouteContext:
        return build_route_context(elite_main, route_request)

    elite_main.build_route_context = patched_build_route_context
    elite_main.app.state.elite55_route_engine_installed = True
