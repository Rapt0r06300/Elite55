from __future__ import annotations

from typing import Any

from app.route_engine import build_route_context


DEFAULT_COMMODITY_QUERY = "gold"


def resolve_commodity_query(elite_main: Any, explicit_query: str | None = None, player: dict[str, Any] | None = None) -> str:
    query = explicit_query
    if query is None and player is not None:
        query = player.get("focus_commodity")
    if query is None:
        query = elite_main.repo.get_state("focus_commodity")
    query = str(query or "").strip().lower()
    return query or DEFAULT_COMMODITY_QUERY


def build_commodity_intel_payload(
    elite_main: Any,
    commodity_query: str | None = None,
    route_request: Any | None = None,
) -> dict[str, Any]:
    context = build_route_context(elite_main, route_request)
    resolved_query = resolve_commodity_query(elite_main, commodity_query, context.player)
    return elite_main.build_commodity_intel(
        resolved_query,
        context.filters,
        all_rows=context.rows,
        player_position=context.player_position,
        owned_permits=context.owned_permits,
    )


def install_commodity_intel_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_commodity_intel_service_installed", False):
        return

    def patched_build_commodity_intel_payload(
        commodity_query: str | None = None,
        route_request: Any | None = None,
    ) -> dict[str, Any]:
        return build_commodity_intel_payload(elite_main, commodity_query, route_request)

    elite_main.build_commodity_intel_payload = patched_build_commodity_intel_payload
    elite_main.app.state.elite55_commodity_intel_service_installed = True
