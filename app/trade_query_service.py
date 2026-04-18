from __future__ import annotations

from typing import Any

DEFAULT_COMMODITY_QUERY = "gold"
DEFAULT_MISSION_QUANTITY = 100


def resolve_focus_commodity_query(
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
    return query or DEFAULT_COMMODITY_QUERY


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


def build_route_request_with_max_age(elite_main: Any, max_age_hours: float | None = None) -> Any:
    route_request = elite_main.default_route_request()
    if max_age_hours is not None:
        route_request.max_age_hours = max_age_hours
    return route_request
