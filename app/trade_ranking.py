from __future__ import annotations

import contextvars
import json
from typing import Any

RANKING_META: dict[str, dict[str, str]] = {
    "profit_total": {
        "label": "Profit brut",
        "title": "Route la plus rentable",
        "note": "Classe surtout par bénéfice total du trajet.",
    },
    "profit_hour": {
        "label": "Profit / heure",
        "title": "Route la plus rentable / h",
        "note": "Classe surtout par rendement horaire réel.",
    },
    "fast": {
        "label": "Trajet rapide",
        "title": "Route la plus rapide",
        "note": "Classe surtout par temps estimé et fluidité.",
    },
    "fresh": {
        "label": "Ultra frais",
        "title": "Route la plus fraîche",
        "note": "Classe surtout par fraîcheur et confiance des données.",
    },
}
DEFAULT_RANKING_MODE = "profit_hour"
_ranking_mode_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "elite55_ranking_mode",
    default=DEFAULT_RANKING_MODE,
)


def normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in RANKING_META else DEFAULT_RANKING_MODE


def current_ranking_mode() -> str:
    return normalize_mode(_ranking_mode_ctx.get())


def ranking_payload(mode: str | None = None) -> dict[str, str]:
    selected_mode = normalize_mode(mode or current_ranking_mode())
    meta = RANKING_META[selected_mode]
    return {
        "ranking_mode": selected_mode,
        "ranking_label": meta["label"],
        "ranking_title": meta["title"],
        "ranking_note": meta["note"],
    }


def _num(value: Any, fallback: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return numeric if numeric == numeric else float(fallback)


def route_sort_key(route: dict[str, Any], mode: str) -> tuple[float, ...]:
    freshness = _num(route.get("freshness_hours"), 999999)
    confidence = _num(route.get("confidence_score", route.get("route_score", 0)), 0)
    total_profit = _num(route.get("trip_profit"), 0)
    per_hour = _num(route.get("profit_per_hour"), 0)
    per_minute = _num(route.get("profit_per_minute"), 0)
    unit_profit = _num(route.get("unit_profit"), 0)
    minutes = _num(route.get("estimated_minutes"), 999999)
    score = _num(route.get("route_score"), 0)

    if mode == "profit_total":
        return (total_profit, unit_profit, per_hour, confidence, -freshness, score)
    if mode == "fast":
        return (-minutes, per_minute, confidence, -freshness, total_profit, score)
    if mode == "fresh":
        return (-freshness, confidence, score, per_hour, total_profit, -minutes)
    return (per_hour, per_minute, confidence, -freshness, total_profit, score)


def loop_sort_key(loop: dict[str, Any], mode: str) -> tuple[float, ...]:
    freshness = _num(loop.get("freshness_hours"), 999999)
    confidence = _num(loop.get("confidence_score", loop.get("route_score", 0)), 0)
    total_profit = _num(loop.get("total_profit"), 0)
    per_hour = _num(loop.get("profit_per_hour"), 0)
    score = _num(loop.get("route_score"), 0)

    if mode == "profit_total":
        return (total_profit, per_hour, confidence, -freshness, score)
    if mode == "fast":
        return (per_hour, confidence, -freshness, total_profit, score)
    if mode == "fresh":
        return (-freshness, confidence, score, per_hour, total_profit)
    return (per_hour, total_profit, confidence, -freshness, score)


def sort_routes_by_mode(routes: list[dict[str, Any]] | None, mode: str | None = None) -> list[dict[str, Any]]:
    selected_mode = normalize_mode(mode or current_ranking_mode())
    return sorted(list(routes or []), key=lambda row: route_sort_key(row, selected_mode), reverse=True)


def sort_loops_by_mode(loops: list[dict[str, Any]] | None, mode: str | None = None) -> list[dict[str, Any]]:
    selected_mode = normalize_mode(mode or current_ranking_mode())
    return sorted(list(loops or []), key=lambda row: loop_sort_key(row, selected_mode), reverse=True)


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
        sorted_routes = sort_routes_by_mode(routes)
        payload = original_select_route_views(sorted_routes, player)
        payload.update(ranking_payload())
        payload["primary_route"] = sorted_routes[0] if sorted_routes else None
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
        data["routes"] = sort_routes_by_mode(data.get("routes"))
        data["loops"] = sort_loops_by_mode(data.get("loops"))
        data["route_views"] = patched_select_route_views(data.get("routes") or [], data.get("player") or player)
        decision_cards = dict(data.get("decision_cards") or {})
        decision_cards.update(ranking_payload())
        decision_cards["primary_route"] = data["routes"][0] if data.get("routes") else None
        decision_cards["primary_loop"] = data["loops"][0] if data.get("loops") else None
        data["decision_cards"] = decision_cards
        data.update(ranking_payload())
        return data

    def patched_build_commodity_intel(*args: Any, **kwargs: Any) -> dict[str, Any]:
        data = original_build_commodity_intel(*args, **kwargs)
        routes = sort_routes_by_mode(data.get("best_routes"))
        data["best_routes"] = routes
        route_views = dict(data.get("route_views") or {})
        route_views.update(patched_select_route_views(routes, {
            "current_system": elite_main.repo.get_state("current_system"),
            "current_market_id": elite_main.repo.get_state("current_market_id"),
        }))
        data["route_views"] = route_views
        quick_trade = dict(data.get("quick_trade") or {})
        quick_trade["best_route"] = routes[0] if routes else None
        data["quick_trade"] = quick_trade
        decision_cards = dict(data.get("decision_cards") or {})
        decision_cards.update(ranking_payload())
        decision_cards["primary_route"] = routes[0] if routes else None
        data["decision_cards"] = decision_cards
        data.update(ranking_payload())
        return data

    def patched_build_mission_intel(*args: Any, **kwargs: Any) -> dict[str, Any]:
        data = original_build_mission_intel(*args, **kwargs)
        routes = sort_routes_by_mode(data.get("best_routes"))
        data["best_routes"] = routes
        route_views = dict(data.get("route_views") or {})
        route_views.update(patched_select_route_views(routes, {
            "current_system": elite_main.repo.get_state("current_system"),
            "current_market_id": elite_main.repo.get_state("current_market_id"),
        }))
        data["route_views"] = route_views
        data.update(ranking_payload())
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
