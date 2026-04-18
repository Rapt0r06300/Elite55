from __future__ import annotations

from typing import Any

from app.api_route_patch import patch_api_route
from app.dashboard_api_service import build_dashboard_response
from app.snapshot_cache_service import build_cached_live_snapshot_response
from app.trader_context_service import (
    build_route_request_with_max_age,
    remember_commodity_lookup,
    remember_mission_result,
    set_mission_commodity_state,
)


def build_routes_response(elite_main: Any, route_request: Any | None = None) -> dict[str, Any]:
    return {"ok": True, "dashboard": build_dashboard_response(elite_main, route_request)}


def build_local_pulse_response(elite_main: Any) -> dict[str, Any]:
    builder = getattr(elite_main, "local_pulse_payload", None)
    if not callable(builder):
        raise RuntimeError("Aucun builder local pulse disponible")
    return {"ok": True, "dashboard": builder()}


def build_live_snapshot_response(elite_main: Any, payload: Any | None = None) -> dict[str, Any]:
    builder = getattr(elite_main, "build_live_snapshot_payload", None)
    if not callable(builder):
        raise RuntimeError("Aucun builder live snapshot disponible")
    return build_cached_live_snapshot_response(elite_main, payload, builder)


def build_commodity_intel_response(
    elite_main: Any,
    query: str,
    *,
    max_age_hours: float | None = None,
    origin_system: str | None = None,
    origin_station: str | None = None,
    target_system: str | None = None,
    target_station: str | None = None,
) -> dict[str, Any]:
    remember_commodity_lookup(elite_main, query)
    route_request = build_route_request_with_max_age(elite_main, max_age_hours)
    payload_builder = getattr(elite_main, "build_commodity_intel_payload", None)
    if callable(payload_builder):
        return payload_builder(
            query,
            route_request=route_request,
            origin_system=origin_system,
            origin_station=origin_station,
            target_system=target_system,
            target_station=target_station,
        )
    return elite_main.build_commodity_intel(
        query,
        elite_main.build_filters(route_request),
        origin_system=origin_system,
        origin_station=origin_station,
        target_system=target_system,
        target_station=target_station,
    )


def build_mission_intel_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    set_mission_commodity_state(elite_main, payload.commodity_query)
    route_request = build_route_request_with_max_age(elite_main, getattr(payload, "max_age_hours", None))
    payload_builder = getattr(elite_main, "build_mission_intel_payload", None)
    if callable(payload_builder):
        result = payload_builder(
            payload.commodity_query,
            payload.quantity,
            target_system=payload.target_system,
            target_station=payload.target_station,
            route_request=route_request,
        )
    else:
        result = elite_main.build_mission_intel(
            payload.commodity_query,
            payload.quantity,
            elite_main.build_filters(route_request),
            target_system=payload.target_system,
            target_station=payload.target_station,
        )
    remember_mission_result(elite_main, payload, result)
    return result


def apply_player_config_response(elite_main: Any, payload: Any) -> dict[str, Any]:
    elite_main.repo.set_states(
        {
            "cargo_capacity_override": payload.cargo_capacity_override,
            "jump_range_override": payload.jump_range_override,
            "preferred_pad_size": payload.preferred_pad_size,
        }
    )
    dashboard = build_dashboard_response(elite_main)
    elite_main.remember_ship_profile(dashboard["player"])
    return {"ok": True, "dashboard": dashboard}


def install_trader_api_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trader_api_service_installed", False):
        return

    elite_main.routes_response = lambda route_request=None: build_routes_response(elite_main, route_request)
    elite_main.local_pulse_response = lambda: build_local_pulse_response(elite_main)
    elite_main.live_snapshot_response = lambda payload=None: build_live_snapshot_response(elite_main, payload)
    elite_main.commodity_intel_response = lambda query, **kwargs: build_commodity_intel_response(elite_main, query, **kwargs)
    elite_main.mission_intel_response = lambda payload: build_mission_intel_response(elite_main, payload)
    elite_main.apply_player_config_response = lambda payload: apply_player_config_response(elite_main, payload)

    async def api_local_pulse_wrapper() -> dict[str, Any]:
        return elite_main.local_pulse_response()

    async def api_commodity_intel_wrapper(
        q: str,
        max_age_hours: float | None = None,
        origin_system: str | None = None,
        origin_station: str | None = None,
        target_system: str | None = None,
        target_station: str | None = None,
    ) -> dict[str, Any]:
        return elite_main.commodity_intel_response(
            q,
            max_age_hours=max_age_hours,
            origin_system=origin_system,
            origin_station=origin_station,
            target_system=target_system,
            target_station=target_station,
        )

    async def api_live_snapshot_wrapper(payload: Any) -> dict[str, Any]:
        return elite_main.live_snapshot_response(payload)

    async def api_mission_intel_wrapper(payload: Any) -> dict[str, Any]:
        return elite_main.mission_intel_response(payload)

    async def api_player_config_wrapper(payload: Any) -> dict[str, Any]:
        return elite_main.apply_player_config_response(payload)

    async def api_routes_wrapper(payload: Any) -> dict[str, Any]:
        return elite_main.routes_response(payload)

    patch_api_route(elite_main.app, "/api/local-pulse", {"GET"}, api_local_pulse_wrapper)
    patch_api_route(elite_main.app, "/api/commodity-intel", {"GET"}, api_commodity_intel_wrapper)
    patch_api_route(elite_main.app, "/api/live-snapshot", {"POST"}, api_live_snapshot_wrapper)
    patch_api_route(elite_main.app, "/api/mission-intel", {"POST"}, api_mission_intel_wrapper)
    patch_api_route(elite_main.app, "/api/player-config", {"POST"}, api_player_config_wrapper)
    patch_api_route(elite_main.app, "/api/routes", {"POST"}, api_routes_wrapper)

    elite_main.app.state.elite55_trader_api_service_installed = True
