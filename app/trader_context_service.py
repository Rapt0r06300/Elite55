from __future__ import annotations

from typing import Any


def normalize_commodity_value(elite_main: Any, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = elite_main.normalize_commodity_symbol(value)
    return normalized or value


def set_focus_commodity_state(elite_main: Any, query: str | None) -> str | None:
    normalized = normalize_commodity_value(elite_main, query)
    if normalized:
        elite_main.repo.set_state("focus_commodity", normalized)
    return normalized


def set_mission_commodity_state(elite_main: Any, query: str | None) -> str | None:
    normalized = normalize_commodity_value(elite_main, query)
    if normalized:
        elite_main.repo.set_state("mission_commodity", normalized)
    return normalized


def build_route_request_with_max_age(elite_main: Any, max_age_hours: float | None = None) -> Any:
    route_request = elite_main.default_route_request()
    if max_age_hours is not None:
        route_request.max_age_hours = max_age_hours
    return route_request


def remember_commodity_lookup(elite_main: Any, query: str) -> dict[str, Any] | None:
    normalized = set_focus_commodity_state(elite_main, query)
    resolved = elite_main.repo.resolve_commodity(query)
    if resolved:
        elite_main.remember_trader_selection("commodity", resolved["symbol"], resolved["commodity_name"])
    elite_main.remember_trader_query(normalized or query)
    return resolved


def remember_mission_result(elite_main: Any, payload: Any, result: dict[str, Any]) -> None:
    if result.get("resolved"):
        elite_main.remember_trader_selection("commodity", result["symbol"], result["commodity_name"])
    if result.get("target_system"):
        elite_main.remember_trader_selection("system", result["target_system"], result["target_system"])
    if result.get("target_station"):
        elite_main.remember_trader_selection(
            "station",
            f"{result.get('target_system') or ''}::{result['target_station']}",
            result["target_station"],
            secondary=result.get("target_system"),
        )
    elite_main.remember_mission_plan(
        payload.commodity_query,
        payload.quantity,
        commodity_name=result.get("commodity_name"),
        target_system=result.get("target_system"),
        target_station=result.get("target_station"),
    )


def update_live_snapshot_states(elite_main: Any, payload: Any | None) -> None:
    if payload is None:
        return
    set_focus_commodity_state(elite_main, getattr(payload, "commodity_query", None))
    mission_payload = getattr(payload, "mission", None)
    set_mission_commodity_state(elite_main, getattr(mission_payload, "commodity_query", None))
