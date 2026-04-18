from __future__ import annotations

from typing import Any

from app.api_route_patch import patch_api_route


def build_suggest_response(
    elite_main: Any,
    q: str,
    *,
    scope: str = "universal",
    limit: int = 8,
    system_name: str | None = None,
) -> dict[str, Any]:
    return {
        "query": q,
        "scope": scope,
        "results": elite_main.build_suggestions(q, scope=scope, limit=limit, system_name=system_name),
        "engine_status": elite_main.build_engine_status(),
    }


def build_trader_memory_response(elite_main: Any) -> dict[str, Any]:
    return elite_main.trader_memory_snapshot()


def track_trader_memory_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    elite_main.remember_trader_selection(
        payload.kind,
        payload.entity_id,
        payload.label,
        secondary=getattr(payload, "secondary", None),
        extra=getattr(payload, "extra", None),
    )
    return elite_main.trader_memory_snapshot()


def toggle_trader_favorite_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    return elite_main.toggle_trader_favorite(
        payload.kind,
        payload.entity_id,
        payload.label,
        secondary=getattr(payload, "secondary", None),
        extra=getattr(payload, "extra", None),
    )


def build_refresh_names_response(elite_main: Any) -> dict[str, Any]:
    stats = elite_main.name_library_service.refresh()
    return {
        "ok": True,
        "stats": stats,
        "summary": elite_main.repo.name_library_summary(),
        "results": elite_main.repo.search_name_library(limit=40),
    }


def build_names_response(
    elite_main: Any,
    *,
    q: str = "",
    entry_type: str | None = None,
    limit: int = 60,
) -> dict[str, Any]:
    return {
        "summary": elite_main.repo.name_library_summary(),
        "results": elite_main.repo.search_name_library(query=q, entry_type=entry_type, limit=limit),
    }


def install_lookup_api_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_lookup_api_service_installed", False):
        return

    elite_main.suggest_response = lambda q, **kwargs: build_suggest_response(elite_main, q, **kwargs)
    elite_main.trader_memory_response = lambda: build_trader_memory_response(elite_main)
    elite_main.track_trader_memory_response = lambda payload: track_trader_memory_response(elite_main, payload)
    elite_main.toggle_trader_favorite_response = lambda payload: toggle_trader_favorite_response(elite_main, payload)
    elite_main.refresh_names_response = lambda: build_refresh_names_response(elite_main)
    elite_main.names_response = lambda **kwargs: build_names_response(elite_main, **kwargs)

    async def api_suggest_wrapper(
        q: str,
        scope: str = "universal",
        limit: int = 8,
        system_name: str | None = None,
    ) -> dict[str, Any]:
        return elite_main.suggest_response(q, scope=scope, limit=limit, system_name=system_name)

    async def api_trader_memory_wrapper() -> dict[str, Any]:
        return elite_main.trader_memory_response()

    async def api_trader_memory_track_wrapper(payload: Any) -> dict[str, Any]:
        return elite_main.track_trader_memory_response(payload)

    async def api_trader_toggle_favorite_wrapper(payload: Any) -> dict[str, Any]:
        return elite_main.toggle_trader_favorite_response(payload)

    async def api_refresh_names_wrapper() -> dict[str, Any]:
        return elite_main.refresh_names_response()

    async def api_names_wrapper(q: str = "", entry_type: str | None = None, limit: int = 60) -> dict[str, Any]:
        return elite_main.names_response(q=q, entry_type=entry_type, limit=limit)

    patch_api_route(elite_main.app, "/api/suggest", {"GET"}, api_suggest_wrapper)
    patch_api_route(elite_main.app, "/api/trader-memory", {"GET"}, api_trader_memory_wrapper)
    patch_api_route(elite_main.app, "/api/trader-memory/track", {"POST"}, api_trader_memory_track_wrapper)
    patch_api_route(elite_main.app, "/api/trader-memory/toggle-favorite", {"POST"}, api_trader_toggle_favorite_wrapper)
    patch_api_route(elite_main.app, "/api/names/refresh", {"POST"}, api_refresh_names_wrapper)
    patch_api_route(elite_main.app, "/api/names", {"GET"}, api_names_wrapper)

    elite_main.app.state.elite55_lookup_api_service_installed = True
