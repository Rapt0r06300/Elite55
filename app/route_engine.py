from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class RouteContext:
    request: Any
    filters: Any
    player: dict[str, Any]
    rows: list[dict[str, Any]]
    owned_permits: set[str]
    player_position: Any


DEFAULT_SORT_MODE = "profit_hour"
ALLOWED_SORT_MODES = {"profit_total", "profit_hour", "fast", "fresh"}


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


def ensure_route_context(
    elite_main: Any,
    route_request: Any | None = None,
    route_context: RouteContext | None = None,
) -> RouteContext:
    return route_context or build_route_context(elite_main, route_request)


def normalize_sort_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in ALLOWED_SORT_MODES else DEFAULT_SORT_MODE


def _num(value: Any, fallback: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return numeric if numeric == numeric else float(fallback)


def route_sort_key(route: dict[str, Any], mode: str) -> tuple[float, ...]:
    selected_mode = normalize_sort_mode(mode)
    freshness = _num(route.get("freshness_hours"), 999999)
    confidence = _num(route.get("confidence_score", route.get("route_score", 0)), 0)
    total_profit = _num(route.get("trip_profit"), 0)
    per_hour = _num(route.get("profit_per_hour"), 0)
    per_minute = _num(route.get("profit_per_minute"), 0)
    unit_profit = _num(route.get("unit_profit"), 0)
    minutes = _num(route.get("estimated_minutes"), 999999)
    score = _num(route.get("route_score"), 0)

    if selected_mode == "profit_total":
        return (total_profit, unit_profit, per_hour, confidence, -freshness, score)
    if selected_mode == "fast":
        return (-minutes, per_minute, confidence, -freshness, total_profit, score)
    if selected_mode == "fresh":
        return (-freshness, confidence, score, per_hour, total_profit, -minutes)
    return (per_hour, per_minute, confidence, -freshness, total_profit, score)


def loop_sort_key(loop: dict[str, Any], mode: str) -> tuple[float, ...]:
    selected_mode = normalize_sort_mode(mode)
    freshness = _num(loop.get("freshness_hours"), 999999)
    confidence = _num(loop.get("confidence_score", loop.get("route_score", 0)), 0)
    total_profit = _num(loop.get("total_profit"), 0)
    per_hour = _num(loop.get("profit_per_hour"), 0)
    score = _num(loop.get("route_score"), 0)

    if selected_mode == "profit_total":
        return (total_profit, per_hour, confidence, -freshness, score)
    if selected_mode == "fast":
        return (per_hour, confidence, -freshness, total_profit, score)
    if selected_mode == "fresh":
        return (-freshness, confidence, score, per_hour, total_profit)
    return (per_hour, total_profit, confidence, -freshness, score)


def sort_routes_by_mode(routes: list[dict[str, Any]] | None, mode: str | None = None) -> list[dict[str, Any]]:
    selected_mode = normalize_sort_mode(mode)
    return sorted(list(routes or []), key=lambda row: route_sort_key(row, selected_mode), reverse=True)


def sort_loops_by_mode(loops: list[dict[str, Any]] | None, mode: str | None = None) -> list[dict[str, Any]]:
    selected_mode = normalize_sort_mode(mode)
    return sorted(list(loops or []), key=lambda row: loop_sort_key(row, selected_mode), reverse=True)


def select_primary_route(routes: list[dict[str, Any]] | None, mode: str | None = None) -> dict[str, Any] | None:
    ranked = sort_routes_by_mode(routes, mode)
    return ranked[0] if ranked else None


def select_primary_loop(loops: list[dict[str, Any]] | None, mode: str | None = None) -> dict[str, Any] | None:
    ranked = sort_loops_by_mode(loops, mode)
    return ranked[0] if ranked else None


def build_route_selection_payload(
    routes: list[dict[str, Any]] | None,
    loops: list[dict[str, Any]] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    selected_mode = normalize_sort_mode(mode)
    ranked_routes = sort_routes_by_mode(routes, selected_mode)
    ranked_loops = sort_loops_by_mode(loops, selected_mode)
    return {
        "ranking_mode": selected_mode,
        "routes": ranked_routes,
        "loops": ranked_loops,
        "primary_route": ranked_routes[0] if ranked_routes else None,
        "primary_loop": ranked_loops[0] if ranked_loops else None,
    }


def build_route_view_player(current_system: Any = None, current_market_id: Any = None) -> dict[str, Any]:
    return {
        "current_system": current_system,
        "current_market_id": current_market_id,
    }


def build_ranked_route_views(
    routes: list[dict[str, Any]] | None,
    *,
    mode: str | None,
    player: dict[str, Any] | None,
    select_route_views: Callable[[list[dict[str, Any]], dict[str, Any] | None], dict[str, Any]],
) -> dict[str, Any]:
    selection = build_route_selection_payload(routes, mode=mode)
    payload = dict(select_route_views(selection["routes"], player) or {})
    payload["primary_route"] = selection["primary_route"]
    payload["ranking_mode"] = selection["ranking_mode"]
    return payload


def build_ranked_decision_cards(
    decision_cards: dict[str, Any] | None,
    *,
    routes: list[dict[str, Any]] | None,
    loops: list[dict[str, Any]] | None,
    mode: str | None,
) -> dict[str, Any]:
    payload = dict(decision_cards or {})
    selection = build_route_selection_payload(routes, loops, mode)
    payload["primary_route"] = selection["primary_route"]
    payload["primary_loop"] = selection["primary_loop"]
    payload["ranking_mode"] = selection["ranking_mode"]
    return payload


def build_ranked_quick_trade(
    quick_trade: dict[str, Any] | None,
    *,
    routes: list[dict[str, Any]] | None,
    mode: str | None,
) -> dict[str, Any]:
    payload = dict(quick_trade or {})
    selection = build_route_selection_payload(routes, mode=mode)
    payload["best_route"] = selection["primary_route"]
    payload["ranking_mode"] = selection["ranking_mode"]
    return payload


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
