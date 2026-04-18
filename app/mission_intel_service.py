from __future__ import annotations

from typing import Any


DEFAULT_MISSION_QUERY = "gold"
DEFAULT_MISSION_QUANTITY = 100


def resolve_mission_query(
    elite_main: Any,
    explicit_query: str | None = None,
    player: dict[str, Any] | None = None,
) -> str:
    query = explicit_query
    if query is None and player is not None:
        query = player.get("focus_commodity")
    if query is None:
        query = elite_main.repo.get_state("focus_commodity")
    query = str(query or "").strip().lower()
    return query or DEFAULT_MISSION_QUERY


def resolve_mission_quantity(
    explicit_quantity: int | None = None,
    player: dict[str, Any] | None = None,
    filters: Any | None = None,
) -> int:
    if explicit_quantity is not None:
        return max(1, int(explicit_quantity))
    values = [
        (player or {}).get("cargo_capacity_override"),
        (player or {}).get("cargo_capacity"),
        getattr(filters, "cargo_capacity", None),
        DEFAULT_MISSION_QUANTITY,
    ]
    for value in values:
        if value is None:
            continue
        return max(1, int(value))
    return DEFAULT_MISSION_QUANTITY


def build_mission_intel_payload(
    elite_main: Any,
    commodity_query: str | None = None,
    quantity: int | None = None,
    *,
    target_system: str | None = None,
    target_station: str | None = None,
    route_request: Any | None = None,
) -> dict[str, Any]:
    request = route_request or elite_main.default_route_request()
    filters = elite_main.build_filters(request)
    player = elite_main.player_runtime_snapshot(elite_main.repo.get_all_state())
    rows = elite_main.repo.filtered_trade_rows(filters)
    owned_permits = elite_main.known_owned_permits()
    player_position = elite_main.repo.system_position(player.get("current_system"))
    resolved_query = resolve_mission_query(elite_main, commodity_query, player)
    resolved_quantity = resolve_mission_quantity(quantity, player, filters)
    return elite_main.build_mission_intel(
        resolved_query,
        resolved_quantity,
        filters,
        target_system=target_system,
        target_station=target_station,
        all_rows=rows,
        player_position=player_position,
        owned_permits=owned_permits,
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
    ) -> dict[str, Any]:
        return build_mission_intel_payload(
            elite_main,
            commodity_query,
            quantity,
            target_system=target_system,
            target_station=target_station,
            route_request=route_request,
        )

    elite_main.build_mission_intel_payload = patched_build_mission_intel_payload
    elite_main.app.state.elite55_mission_intel_service_installed = True
