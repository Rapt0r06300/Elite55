from __future__ import annotations

from typing import Any

from app.api_route_patch import patch_api_route
from app.lookup_context_service import (
    build_names_payload,
    build_refresh_names_payload,
    build_suggest_payload,
    build_trader_memory_payload,
    toggle_trader_favorite,
    track_trader_memory,
)


def build_suggest_response(
    elite_main: Any,
    q: str,
    *,
    scope: str = "universal",
    limit: int = 8,
    system_name: str | None = None,
) -> dict[str, Any]:
    return build_suggest_payload(
        elite_main,
        q,
        scope=scope,
        limit=limit,
        system_name=system_name,
    )


def build_trader_memory_response(elite_main: Any) -> dict[str, Any]:
    return build_trader_memory_payload(elite_main)


def track_trader_memory_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    return track_trader_memory(elite_main, payload)


def toggle_trader_favorite_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    return toggle_trader_favorite(elite_main, payload)


def build_refresh_names_response(elite_main: Any) -> dict[str, Any]:
    return build_refresh_names_payload(elite_main)


def build_names_response(
    elite_main: Any,
    *,
    q: str = "",
    entry_type: str | None = None,
    limit: int = 60,
) -> dict[str, Any]:
    return build_names_payload(elite_main, q=q, entry_type=entry_type, limit=limit)


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
