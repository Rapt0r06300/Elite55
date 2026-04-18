from __future__ import annotations

import contextvars
import json
from typing import Any

from app.route_engine import (
    build_ranked_analysis_payload,
    build_route_view_player,
    normalize_sort_mode,
    ranking_payload as engine_ranking_payload,
    sort_loops_by_mode as engine_sort_loops_by_mode,
    sort_routes_by_mode as engine_sort_routes_by_mode,
)

DEFAULT_RANKING_MODE = "profit_hour"
_ranking_mode_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "elite55_ranking_mode",
    default=DEFAULT_RANKING_MODE,
)


def normalize_mode(value: Any) -> str:
    return normalize_sort_mode(value)


def current_ranking_mode() -> str:
    return normalize_mode(_ranking_mode_ctx.get())


def ranking_payload(mode: str | None = None) -> dict[str, str]:
    return engine_ranking_payload(mode or current_ranking_mode())


def sort_routes_by_mode(routes: list[dict[str, Any]] | None, mode: str | None = None) -> list[dict[str, Any]]:
    return engine_sort_routes_by_mode(routes, mode or current_ranking_mode())


def sort_loops_by_mode(loops: list[dict[str, Any]] | None, mode: str | None = None) -> list[dict[str, Any]]:
    return engine_sort_loops_by_mode(loops, mode or current_ranking_mode())


def extract_ranking_mode_from_request(request: Any) -> str | None:
    mode = request.query_params.get("ranking_mode")
    if mode:
        return mode
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return None
    content_type = str(request.headers.get("content-type") or "").lower()
    if "application/json" not in content_type:
        return None
    return None


async def read_ranking_mode_from_json_request(request: Any) -> str | None:
    mode = request.query_params.get("ranking_mode")
    if mode:
        return mode
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return None
    content_type = str(request.headers.get("content-type") or "").lower()
    if "application/json" not in content_type:
        return None
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body.decode("utf-8") or "{}") if raw_body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return None
    mode = payload.get("ranking_mode")
    if not mode and isinstance(payload.get("route"), dict):
        mode = payload["route"].get("ranking_mode")
    if not mode and isinstance(payload.get("mission"), dict):
        mode = payload["mission"].get("ranking_mode")
    return mode


def install_backend_ranking_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_backend_ranking_installed", False):
        return

    original_select_route_views = elite_main.select_route_views
    original_build_trade_dashboard = elite_main.build_trade_dashboard
    original_build_commodity_intel = elite_main.build_commodity_intel
    original_build_mission_intel = elite_main.build_mission_intel
    original_enrich_dashboard_payload = elite_main.enrich_dashboard_payload

    def patched_select_route_views(routes: list[dict[str, Any]], player: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = build_ranked_analysis_payload(
            routes=routes,
            loops=None,
            mode=current_ranking_mode(),
            player=player,
            select_route_views=original_select_route_views,
        )["route_views"]
        return payload

    def patched_build_trade_dashboard(
        filters: Any,
        *,
        player: dict[str, Any] | None = None,
        all_rows: list[dict[str, Any]] | None = None,
        owned_permits: set[str] | None = None,
        player_position: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = original_build_trade_dashboard(
            filters,
            player=player,
            all_rows=all_rows,
            owned_permits=owned_permits,
            player_position=player_position,
        )
        ranked = build_ranked_analysis_payload(
            routes=data.get("routes"),
            loops=data.get("loops"),
            mode=current_ranking_mode(),
            player=data.get("player") or player,
            select_route_views=original_select_route_views,
            decision_cards=data.get("decision_cards"),
        )
        data["routes"] = ranked["routes"]
        data["loops"] = ranked["loops"]
        data["route_views"] = ranked["route_views"]
        data["decision_cards"] = ranked["decision_cards"]
        data.update(ranking_payload(ranked.get("ranking_mode")))
        return data

    def patched_build_commodity_intel(*args: Any, **kwargs: Any) -> dict[str, Any]:
        data = original_build_commodity_intel(*args, **kwargs)
        ranked = build_ranked_analysis_payload(
            routes=data.get("best_routes"),
            loops=None,
            mode=current_ranking_mode(),
            player=build_route_view_player(
                elite_main.repo.get_state("current_system"),
                elite_main.repo.get_state("current_market_id"),
            ),
            select_route_views=original_select_route_views,
            decision_cards=data.get("decision_cards"),
            quick_trade=data.get("quick_trade"),
        )
        data["best_routes"] = ranked["routes"]
        data["route_views"] = ranked["route_views"]
        data["quick_trade"] = ranked["quick_trade"]
        data["decision_cards"] = ranked["decision_cards"]
        data.update(ranking_payload(ranked.get("ranking_mode")))
        return data

    def patched_build_mission_intel(*args: Any, **kwargs: Any) -> dict[str, Any]:
        data = original_build_mission_intel(*args, **kwargs)
        ranked = build_ranked_analysis_payload(
            routes=data.get("best_routes"),
            loops=None,
            mode=current_ranking_mode(),
            player=build_route_view_player(
                elite_main.repo.get_state("current_system"),
                elite_main.repo.get_state("current_market_id"),
            ),
            select_route_views=original_select_route_views,
        )
        data["best_routes"] = ranked["routes"]
        data["route_views"] = ranked["route_views"]
        data.update(ranking_payload(ranked.get("ranking_mode")))
        return data

    def patched_enrich_dashboard_payload(data: dict[str, Any], route_request: Any, owned_permits: set[str] | None = None) -> dict[str, Any]:
        enriched = original_enrich_dashboard_payload(data, route_request, owned_permits)
        enriched.update(ranking_payload())
        return enriched

    elite_main.select_route_views = patched_select_route_views
    elite_main.build_trade_dashboard = patched_build_trade_dashboard
    elite_main.build_commodity_intel = patched_build_commodity_intel
    elite_main.build_mission_intel = patched_build_mission_intel
    elite_main.enrich_dashboard_payload = patched_enrich_dashboard_payload

    @elite_main.app.middleware("http")
    async def elite55_ranking_mode_middleware(request: Any, call_next: Any) -> Any:
        selected_mode = normalize_mode(await read_ranking_mode_from_json_request(request))
        token = _ranking_mode_ctx.set(selected_mode)
        try:
            response = await call_next(request)
        finally:
            _ranking_mode_ctx.reset(token)
        try:
            response.headers["X-Elite55-Ranking-Mode"] = selected_mode
        except Exception:
            pass
        return response

    elite_main.app.state.elite55_backend_ranking_installed = True
