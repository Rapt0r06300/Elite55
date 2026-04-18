from __future__ import annotations

import asyncio
import os
from typing import Any

from app.api_route_patch import patch_api_route
from app.app_event_patch import patch_app_event_handler


def build_health_response(elite_main: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "build_token": os.environ.get("ELITE55_BUILD_TOKEN"),
        "engine_status": elite_main.build_engine_status(),
        "market_rows": elite_main.repo.commodity_price_count(),
        "name_library_total": elite_main.repo.name_library_summary().get("total", 0),
    }


def build_eddn_start_response(elite_main: Any) -> dict[str, Any]:
    return {"ok": True, "status": elite_main.eddn_listener.start()}


def build_eddn_stop_response(elite_main: Any) -> dict[str, Any]:
    return {"ok": True, "status": elite_main.eddn_listener.stop()}


async def run_startup_runtime(elite_main: Any) -> None:
    try:
        await asyncio.to_thread(elite_main.local_sync_service.bootstrap)
    except Exception:
        elite_main.logger.exception("Initial local bootstrap failed")
    await elite_main.local_sync_service.start()
    if elite_main.repo.name_library_summary().get("total", 0) == 0:
        asyncio.create_task(asyncio.to_thread(elite_main.name_library_service.refresh))
    asyncio.create_task(elite_main.delayed_background_startup())


async def run_shutdown_runtime(elite_main: Any) -> None:
    await elite_main.local_sync_service.stop()
    elite_main.eddn_listener.stop()


def install_runtime_api_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_runtime_api_service_installed", False):
        return

    elite_main.health_response = lambda: build_health_response(elite_main)
    elite_main.eddn_start_response = lambda: build_eddn_start_response(elite_main)
    elite_main.eddn_stop_response = lambda: build_eddn_stop_response(elite_main)
    elite_main.runtime_startup = lambda: run_startup_runtime(elite_main)
    elite_main.runtime_shutdown = lambda: run_shutdown_runtime(elite_main)

    async def api_health_wrapper() -> dict[str, Any]:
        return elite_main.health_response()

    async def api_eddn_start_wrapper() -> dict[str, Any]:
        return elite_main.eddn_start_response()

    async def api_eddn_stop_wrapper() -> dict[str, Any]:
        return elite_main.eddn_stop_response()

    async def startup_event_wrapper() -> None:
        await elite_main.runtime_startup()

    async def shutdown_event_wrapper() -> None:
        await elite_main.runtime_shutdown()

    patch_api_route(elite_main.app, "/api/health", {"GET"}, api_health_wrapper)
    patch_api_route(elite_main.app, "/api/eddn/start", {"POST"}, api_eddn_start_wrapper)
    patch_api_route(elite_main.app, "/api/eddn/stop", {"POST"}, api_eddn_stop_wrapper)
    patch_app_event_handler(elite_main.app, "startup", "startup_event", startup_event_wrapper)
    patch_app_event_handler(elite_main.app, "shutdown", "shutdown_event", shutdown_event_wrapper)

    elite_main.app.state.elite55_runtime_api_service_installed = True
