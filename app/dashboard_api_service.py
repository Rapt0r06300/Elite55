from __future__ import annotations

from typing import Any

from app.api_route_patch import patch_api_route


def build_dashboard_response(elite_main: Any, route_request: Any | None = None) -> dict[str, Any]:
    builder = getattr(elite_main, "build_dashboard_payload", None)
    if callable(builder):
        return builder(route_request)
    fallback = getattr(elite_main, "dashboard_payload", None)
    if callable(fallback):
        return fallback(route_request)
    raise RuntimeError("Aucun builder de dashboard disponible")


def install_dashboard_api_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_dashboard_api_service_installed", False):
        return

    def patched_dashboard_payload(route_request: Any | None = None) -> dict[str, Any]:
        return build_dashboard_response(elite_main, route_request)

    async def api_dashboard_wrapper() -> dict[str, Any]:
        return build_dashboard_response(elite_main)

    elite_main.dashboard_payload = patched_dashboard_payload
    patch_api_route(elite_main.app, "/api/dashboard", {"GET"}, api_dashboard_wrapper)
    elite_main.app.state.elite55_dashboard_api_service_installed = True
