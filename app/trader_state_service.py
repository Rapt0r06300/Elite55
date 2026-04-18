from __future__ import annotations

from typing import Any


def normalized_commodity(elite_main: Any, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = elite_main.normalize_commodity_symbol(value)
    return normalized or value


def remember_focus_commodity(elite_main: Any, query: str | None) -> str | None:
    normalized = normalized_commodity(elite_main, query)
    if normalized:
        elite_main.repo.set_state("focus_commodity", normalized)
    return normalized


def remember_mission_commodity(elite_main: Any, query: str | None) -> str | None:
    normalized = normalized_commodity(elite_main, query)
    if normalized:
        elite_main.repo.set_state("mission_commodity", normalized)
    return normalized


def remember_resolved_commodity(elite_main: Any, query: str) -> dict[str, Any] | None:
    resolved = elite_main.repo.resolve_commodity(query)
    if resolved:
        elite_main.remember_trader_selection("commodity", resolved["symbol"], resolved["commodity_name"])
    elite_main.remember_trader_query(query)
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


def apply_player_config(elite_main: Any, payload: Any) -> None:
    elite_main.repo.set_states(
        {
            "cargo_capacity_override": payload.cargo_capacity_override,
            "jump_range_override": payload.jump_range_override,
            "preferred_pad_size": payload.preferred_pad_size,
        }
    )
