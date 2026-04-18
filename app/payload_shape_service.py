from __future__ import annotations

from typing import Any

from app.route_engine import ranking_payload as route_ranking_payload


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {})


def normalize_route_views(payload: dict[str, Any] | None, mode: str | None = None) -> dict[str, Any]:
    data = _as_dict(payload)
    data.setdefault("primary_route", None)
    data.update(route_ranking_payload(data.get("ranking_mode") or mode))
    return data


def normalize_decision_cards(payload: dict[str, Any] | None, mode: str | None = None) -> dict[str, Any]:
    data = _as_dict(payload)
    data.setdefault("primary_route", None)
    data.setdefault("primary_loop", None)
    data.update(route_ranking_payload(data.get("ranking_mode") or mode))
    return data


def normalize_quick_trade(payload: dict[str, Any] | None, mode: str | None = None) -> dict[str, Any]:
    data = _as_dict(payload)
    data.setdefault("best_route", None)
    data.update(route_ranking_payload(data.get("ranking_mode") or mode))
    return data


def normalize_dashboard_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    mode = data.get("ranking_mode")
    data.setdefault("routes", [])
    data.setdefault("loops", [])
    data["route_views"] = normalize_route_views(data.get("route_views"), mode)
    data["decision_cards"] = normalize_decision_cards(data.get("decision_cards"), mode)
    data.setdefault("defaults", {})
    data.setdefault("sources", {})
    data.setdefault("engine_status", {})
    data.setdefault("trader_memory", {})
    data.update(route_ranking_payload(mode))
    return data


def normalize_commodity_intel_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    mode = data.get("ranking_mode")
    data.setdefault("best_routes", [])
    data["route_views"] = normalize_route_views(data.get("route_views"), mode)
    data["decision_cards"] = normalize_decision_cards(data.get("decision_cards"), mode)
    data["quick_trade"] = normalize_quick_trade(data.get("quick_trade"), mode)
    data.setdefault("resolved", False)
    data.setdefault("commodity_name", None)
    data.setdefault("symbol", None)
    data.update(route_ranking_payload(mode))
    return data


def normalize_mission_intel_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    mode = data.get("ranking_mode")
    data.setdefault("best_routes", [])
    data["route_views"] = normalize_route_views(data.get("route_views"), mode)
    data["decision_cards"] = normalize_decision_cards(data.get("decision_cards"), mode)
    data.setdefault("resolved", False)
    data.setdefault("commodity_name", None)
    data.setdefault("symbol", None)
    data.update(route_ranking_payload(mode))
    return data


def normalize_local_pulse_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    data.setdefault("player", {})
    data.setdefault("current_market", {})
    data.setdefault("local_sync", {})
    data.setdefault("eddn", {})
    data.setdefault("name_library", {})
    data.setdefault("engine_status", {})
    data.setdefault("sources", {})
    data.setdefault("nav_route", {})
    data.setdefault("combat_support", {})
    data.setdefault("owned_permits", [])
    data.setdefault("owned_permit_labels", [])
    dataset = _as_dict(data.get("dataset"))
    dataset.setdefault("rows", 0)
    data["dataset"] = dataset
    return data


def normalize_live_snapshot_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    data["dashboard"] = normalize_dashboard_payload(data.get("dashboard"))
    data["commodity_intel"] = normalize_commodity_intel_payload(data.get("commodity_intel"))
    data["mission_intel"] = normalize_mission_intel_payload(data.get("mission_intel"))
    return data


def install_payload_shape_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_payload_shape_service_installed", False):
        return

    original_dashboard = getattr(elite_main, "build_dashboard_payload", None)
    original_commodity = getattr(elite_main, "build_commodity_intel_payload", None)
    original_mission = getattr(elite_main, "build_mission_intel_payload", None)
    original_local_pulse = getattr(elite_main, "local_pulse_payload", None)
    original_live_snapshot = getattr(elite_main, "build_live_snapshot_payload", None)

    if callable(original_dashboard):
        elite_main.build_dashboard_payload = lambda *args, **kwargs: normalize_dashboard_payload(original_dashboard(*args, **kwargs))
    if callable(original_commodity):
        elite_main.build_commodity_intel_payload = lambda *args, **kwargs: normalize_commodity_intel_payload(original_commodity(*args, **kwargs))
    if callable(original_mission):
        elite_main.build_mission_intel_payload = lambda *args, **kwargs: normalize_mission_intel_payload(original_mission(*args, **kwargs))
    if callable(original_local_pulse):
        elite_main.local_pulse_payload = lambda *args, **kwargs: normalize_local_pulse_payload(original_local_pulse(*args, **kwargs))
    if callable(original_live_snapshot):
        elite_main.build_live_snapshot_payload = lambda *args, **kwargs: normalize_live_snapshot_payload(original_live_snapshot(*args, **kwargs))

    elite_main.app.state.elite55_payload_shape_service_installed = True
