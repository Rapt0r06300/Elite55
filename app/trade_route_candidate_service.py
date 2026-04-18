from __future__ import annotations

from typing import Any


def build_route_candidate(
    elite_main: Any,
    source: dict[str, Any],
    target: dict[str, Any],
    filters: Any,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    if source["market_id"] == target["market_id"]:
        return None
    unit_profit = int(target["sell_price"]) - int(source["buy_price"])
    if unit_profit < filters.min_profit_unit:
        return None
    units = min(
        filters.cargo_capacity,
        int(source.get("stock") or filters.cargo_capacity),
        int(target.get("demand") or filters.cargo_capacity),
    )
    if units <= 0:
        return None
    if units < elite_main.minimum_trade_units(filters):
        return None
    route_distance = elite_main.euclidean_distance(source, target)
    minutes = elite_main.estimate_minutes(route_distance, source.get("distance_to_arrival"), target.get("distance_to_arrival"), filters.jump_range)
    trip_profit = unit_profit * units
    freshness = max(elite_main.age_hours(source.get("price_updated_at")) or 0, elite_main.age_hours(target.get("price_updated_at")) or 0)
    player_distance = elite_main.euclidean_distance(source, player_position) if player_position else None
    source_conf = elite_main.row_confidence(source, filters, owned_permits)
    target_conf = elite_main.row_confidence(target, filters, owned_permits)
    confidence = elite_main.clamp_score((source_conf + target_conf) / 2)
    profit_per_hour = round(trip_profit * 60 / minutes, 2)
    profit_per_minute = round(trip_profit / max(minutes, 1), 2)
    profit_score = elite_main.clamp_score(elite_main.math.log10(max(profit_per_hour, 1)) * 18)
    trip_score = elite_main.clamp_score(elite_main.math.log10(max(trip_profit, 1)) * 18)
    travel_score = elite_main.clamp_score(100 - min(minutes, 35) * 2.2)
    freshness_score = elite_main.freshness_confidence(freshness, filters.max_age_hours)
    route_score = elite_main.clamp_score(
        profit_score * 0.32
        + trip_score * 0.18
        + confidence * 0.26
        + freshness_score * 0.14
        + travel_score * 0.10
    )
    return {
        "commodity_symbol": source["commodity_symbol"],
        "commodity_name": source.get("commodity_name_fr") or source.get("commodity_name"),
        "source_market_id": source["market_id"],
        "source_system": source["system_name"],
        "source_station": source["station_name"],
        "source_buy_price": source["buy_price"],
        "source_stock": source["stock"],
        "source_distance_ls": source.get("distance_to_arrival"),
        "target_market_id": target["market_id"],
        "target_system": target["system_name"],
        "target_station": target["station_name"],
        "target_sell_price": target["sell_price"],
        "target_demand": target["demand"],
        "target_distance_ls": target.get("distance_to_arrival"),
        "route_distance_ly": route_distance,
        "distance_from_player_ly": player_distance,
        "units": units,
        "unit_profit": unit_profit,
        "trip_profit": trip_profit,
        "estimated_minutes": round(minutes, 1),
        "profit_per_hour": profit_per_hour,
        "profit_per_minute": profit_per_minute,
        "freshness_hours": round(freshness, 2),
        "confidence_score": confidence,
        "confidence_label": elite_main.confidence_label(confidence),
        "route_score": route_score,
        "source_confidence_score": source_conf,
        "target_confidence_score": target_conf,
        "source_badges": elite_main.station_badges(source, owned_permits),
        "target_badges": elite_main.station_badges(target, owned_permits),
        "accessibility": f"{elite_main.station_accessibility_label(source, owned_permits)} -> {elite_main.station_accessibility_label(target, owned_permits)}",
    }


def install_trade_route_candidate_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_route_candidate_service_installed", False):
        return

    elite_main.build_route_candidate = lambda source, target, filters, player_position=None, owned_permits=None: build_route_candidate(
        elite_main,
        source,
        target,
        filters,
        player_position,
        owned_permits,
    )
    elite_main.app.state.elite55_trade_route_candidate_service_installed = True
