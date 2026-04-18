from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def build_nav_route_payload(elite_main: Any) -> dict[str, Any]:
    path = elite_main.JOURNAL_DIR / "NavRoute.json"
    empty = {
        "available": False,
        "updated_at": None,
        "age_minutes": None,
        "current_system": elite_main.repo.get_state("current_system"),
        "first_system": None,
        "destination_system": None,
        "step_count": 0,
        "hops": 0,
        "direct_distance_ly": None,
        "route_preview": [],
        "truncated": False,
    }
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return empty

    raw_steps = data.get("Route") or data.get("route") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        return empty

    steps: list[dict[str, Any]] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue
        system_name = str(raw_step.get("StarSystem") or "").strip()
        if not system_name:
            continue
        coords = raw_step.get("StarPos") or raw_step.get("Starpos") or []
        steps.append(
            {
                "system_name": system_name,
                "star_class": raw_step.get("StarClass"),
                "x": coords[0] if len(coords) > 0 else None,
                "y": coords[1] if len(coords) > 1 else None,
                "z": coords[2] if len(coords) > 2 else None,
            }
        )
    if not steps:
        return empty

    updated_at = data.get("timestamp")
    if not updated_at:
        try:
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            updated_at = None

    current_system = str(elite_main.repo.get_state("current_system") or "").strip() or None
    current_position = elite_main.repo.system_position(current_system) if current_system else None
    first = steps[0]
    destination = steps[-1]
    origin_position = current_position or {
        "x": first.get("x"),
        "y": first.get("y"),
        "z": first.get("z"),
    }
    destination_position = {
        "x": destination.get("x"),
        "y": destination.get("y"),
        "z": destination.get("z"),
    }
    if any(value is None for value in destination_position.values()):
        destination_position = elite_main.repo.system_position(destination["system_name"]) or destination_position

    direct_distance = None
    if origin_position and destination_position and not any(value is None for value in destination_position.values()):
        direct_distance = elite_main.euclidean_distance(origin_position, destination_position)

    preview = [
        {
            "system_name": row["system_name"],
            "star_class": row.get("star_class"),
        }
        for row in steps[:10]
    ]
    return {
        "available": True,
        "updated_at": updated_at,
        "age_minutes": elite_main.age_minutes(updated_at),
        "current_system": current_system,
        "first_system": first["system_name"],
        "destination_system": destination["system_name"],
        "step_count": len(steps),
        "hops": max(0, len(steps) - 1),
        "direct_distance_ly": direct_distance,
        "route_preview": preview,
        "truncated": len(steps) > len(preview),
    }


def station_services(row: dict[str, Any]) -> set[str]:
    raw = row.get("services_json")
    if not raw:
        return set()
    if isinstance(raw, list):
        return {str(item).strip().lower() for item in raw if str(item).strip()}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item).strip().lower() for item in data if str(item).strip()}


def combat_station_sort_key(elite_main: Any, row: dict[str, Any], current_system: str | None = None) -> tuple[int, float, float, float]:
    same_system = (
        0
        if current_system
        and elite_main.normalize_search_text(row.get("system_name")) == elite_main.normalize_search_text(current_system)
        else 1
    )
    distance_ly = float(row.get("distance_ly")) if row.get("distance_ly") is not None else 999999.0
    distance_ls = float(row.get("distance_ls")) if row.get("distance_ls") is not None else 999999999.0
    freshness = float(row.get("freshness_hours")) if row.get("freshness_hours") is not None else 999999.0
    return (same_system, distance_ly, distance_ls, freshness)


def build_combat_support_payload(elite_main: Any, limit: int = 10) -> dict[str, Any]:
    current_system = str(elite_main.repo.get_state("current_system") or "").strip() or None
    player_position = elite_main.repo.system_position(current_system) if current_system else None
    preferred_pad = str(elite_main.repo.get_state("preferred_pad_size", "M") or "M").upper()
    permits = elite_main.known_owned_permits()
    with elite_main.repo.connect() as conn:
        rows = conn.execute(
            """
            SELECT
                st.market_id,
                st.system_name,
                st.name AS station_name,
                st.type AS station_type,
                st.distance_to_arrival,
                st.landing_pad,
                st.has_market,
                st.is_planetary,
                st.is_odyssey,
                st.is_fleet_carrier,
                st.services_json,
                st.updated_at,
                sy.x,
                sy.y,
                sy.z,
                sy.requires_permit,
                sy.permit_name
            FROM stations st
            LEFT JOIN systems sy ON sy.name = st.system_name
            ORDER BY st.updated_at DESC, st.name COLLATE NOCASE ASC
            """
        ).fetchall()

    candidates: list[dict[str, Any]] = []
    for raw_row in rows:
        row = dict(raw_row)
        if elite_main.PAD_RANK.get(row.get("landing_pad") or "?", 0) < elite_main.PAD_RANK.get(preferred_pad, 0):
            continue
        if not elite_main.station_accessible(row, permits):
            continue
        services = station_services(row)
        has_restock = "restock" in services
        has_repair = "repair" in services
        has_refuel = "refuel" in services
        if not any([has_restock, has_repair, has_refuel]):
            continue
        distance_ly = elite_main.euclidean_distance(row, player_position) if player_position else None
        badges = [f"Pad {row.get('landing_pad') or '?'}"]
        if has_restock:
            badges.append("Munitions")
        if has_repair:
            badges.append("Reparation")
        if has_refuel:
            badges.append("Refuel")
        candidates.append(
            {
                "market_id": row.get("market_id"),
                "system_name": row.get("system_name"),
                "station_name": row.get("station_name"),
                "station_type": row.get("station_type"),
                "distance_ly": distance_ly,
                "distance_ls": row.get("distance_to_arrival"),
                "same_system": bool(
                    current_system
                    and elite_main.normalize_search_text(row.get("system_name")) == elite_main.normalize_search_text(current_system)
                ),
                "landing_pad": row.get("landing_pad"),
                "has_restock": has_restock,
                "has_repair": has_repair,
                "has_refuel": has_refuel,
                "services": sorted(services),
                "badges": badges,
                "updated_at": row.get("updated_at"),
                "freshness_hours": elite_main.age_hours(row.get("updated_at")),
                "accessibility": elite_main.station_accessibility_label(row, permits),
            }
        )

    candidates.sort(key=lambda row: combat_station_sort_key(elite_main, row, current_system))

    def nearest_for(service_key: str) -> dict[str, Any] | None:
        service_rows = [row for row in candidates if row.get(service_key)]
        if not service_rows:
            return None
        service_rows.sort(key=lambda row: combat_station_sort_key(elite_main, row, current_system))
        return service_rows[0]

    return {
        "current_system": current_system,
        "preferred_pad_size": preferred_pad,
        "best_restock": nearest_for("has_restock"),
        "best_repair": nearest_for("has_repair"),
        "best_refuel": nearest_for("has_refuel"),
        "stations": candidates[: max(3, min(int(limit or 10), 20))],
    }


def install_nav_combat_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_nav_combat_service_installed", False):
        return

    elite_main.nav_route_payload = lambda: build_nav_route_payload(elite_main)
    elite_main.combat_support_payload = lambda limit=10: build_combat_support_payload(elite_main, limit)
    elite_main.app.state.elite55_nav_combat_service_installed = True
