from __future__ import annotations

import math
from typing import Any


def station_allowed(elite_main: Any, row: dict[str, Any], filters: Any, owned_permits: set[str] | None = None) -> bool:
    if not elite_main.station_accessible(row, owned_permits):
        return False
    if elite_main.PAD_RANK.get(row.get("landing_pad") or "?", 0) < elite_main.PAD_RANK.get(filters.min_pad_size, 0):
        return False
    if not filters.include_planetary and row.get("is_planetary"):
        return False
    if not filters.include_settlements and row.get("is_odyssey") and "settlement" in str(row.get("station_type") or "").lower():
        return False
    if not filters.include_fleet_carriers and row.get("is_fleet_carrier"):
        return False
    if row.get("distance_to_arrival") and float(row["distance_to_arrival"]) > filters.max_station_distance_ls:
        return False
    freshness = elite_main.age_hours(row.get("price_updated_at"))
    if freshness is None or freshness > filters.max_age_hours:
        return False
    if filters.no_surprise:
        if elite_main.PAD_RANK.get(row.get("landing_pad") or "?", 0) <= 0:
            return False
        if row.get("distance_to_arrival") and float(row["distance_to_arrival"]) > min(filters.max_station_distance_ls, 2500):
            return False
        if freshness > min(filters.max_age_hours, 24):
            return False
    return True


def minimum_trade_units(filters: Any) -> int:
    cargo_capacity = max(int(filters.cargo_capacity or 0), 1)
    return max(4, min(32, math.ceil(cargo_capacity * 0.10)))


def minimum_buy_stock(filters: Any) -> int:
    return max(minimum_trade_units(filters), int(filters.min_buy_stock or 0))


def minimum_sell_demand(filters: Any) -> int:
    return max(minimum_trade_units(filters), int(filters.min_sell_demand or 0))


def relaxed_trade_filters(elite_main: Any, filters: Any) -> Any:
    return elite_main.TradeFilters(
        cargo_capacity=filters.cargo_capacity,
        jump_range=filters.jump_range,
        max_age_hours=max(float(filters.max_age_hours or 0), 96.0),
        max_station_distance_ls=max(int(filters.max_station_distance_ls or 0), 20000),
        min_profit_unit=0,
        min_buy_stock=max(0, int(filters.min_buy_stock or 0) // 2),
        min_sell_demand=max(0, int(filters.min_sell_demand or 0) // 2),
        min_pad_size=filters.min_pad_size,
        include_planetary=filters.include_planetary,
        include_settlements=filters.include_settlements,
        include_fleet_carriers=filters.include_fleet_carriers,
        no_surprise=False,
        max_results=max(int(filters.max_results or 0), 40),
    )


def commodity_price_filters(elite_main: Any, filters: Any) -> Any:
    return elite_main.replace(
        filters,
        max_station_distance_ls=elite_main.NO_DISTANCE_LIMIT_LS,
        min_profit_unit=0,
        no_surprise=False,
        max_results=max(int(filters.max_results or 0), 40),
    )


def resolve_trade_context(elite_main: Any, system_name: str | None = None, station_name: str | None = None) -> dict[str, Any]:
    resolved_system = elite_main.repo.resolve_system(system_name) if system_name else None
    normalized_system_name = str((resolved_system or {}).get("name") or (system_name or "")).strip() or None
    resolved_station = elite_main.repo.resolve_station(station_name, system_name=normalized_system_name) if station_name else None
    if station_name and not resolved_station:
        resolved_station = elite_main.repo.resolve_station(station_name)
    normalized_station_name = str((resolved_station or {}).get("station_name") or (station_name or "")).strip() or None
    market_id = int(resolved_station["market_id"]) if resolved_station and resolved_station.get("market_id") else None
    if normalized_system_name is None and resolved_station and resolved_station.get("system_name"):
        normalized_system_name = str(resolved_station["system_name"]).strip()
    elif resolved_station and resolved_station.get("system_name"):
        normalized_system_name = str(resolved_station["system_name"]).strip()
    return {
        "system_name": normalized_system_name,
        "station_name": normalized_station_name,
        "market_id": market_id,
    }


def filter_trade_rows_by_context(
    elite_main: Any,
    rows: list[dict[str, Any]],
    *,
    system_name: str | None = None,
    market_id: int | None = None,
) -> list[dict[str, Any]]:
    filtered = rows
    if system_name:
        normalized_system = elite_main.normalize_search_text(system_name)
        filtered = [row for row in filtered if elite_main.normalize_search_text(row.get("system_name")) == normalized_system]
    if market_id is not None:
        filtered = [row for row in filtered if int(row.get("market_id") or 0) == int(market_id)]
    return filtered


def rows_for_symbol_with_fallback(
    elite_main: Any,
    symbol: str,
    filters: Any,
    permits: set[str] | None,
    *,
    all_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    base_rows = all_rows if all_rows is not None else elite_main.repo.filtered_trade_rows(filters, commodity_symbols=[symbol])
    rows = [row for row in base_rows if row["commodity_symbol"] == symbol and station_allowed(elite_main, row, filters, permits)]
    if elite_main.meaningful_buy_rows(rows, filters) and elite_main.meaningful_sell_rows(rows, filters):
        return rows, False

    fallback_filters = relaxed_trade_filters(elite_main, filters)
    fallback_base_rows = elite_main.repo.filtered_trade_rows(fallback_filters, commodity_symbols=[symbol])
    fallback_rows = [
        row
        for row in fallback_base_rows
        if row["commodity_symbol"] == symbol and station_allowed(elite_main, row, fallback_filters, permits)
    ]
    if not fallback_rows:
        return rows, False

    merged: dict[tuple[int, str], dict[str, Any]] = {
        (int(row["market_id"]), row["commodity_symbol"]): row
        for row in rows
    }
    for row in fallback_rows:
        merged[(int(row["market_id"]), row["commodity_symbol"])] = row
    return list(merged.values()), True


def install_trade_flow_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_flow_service_installed", False):
        return

    elite_main.station_allowed = lambda row, filters, owned_permits=None: station_allowed(elite_main, row, filters, owned_permits)
    elite_main.minimum_trade_units = minimum_trade_units
    elite_main.minimum_buy_stock = minimum_buy_stock
    elite_main.minimum_sell_demand = minimum_sell_demand
    elite_main.relaxed_trade_filters = lambda filters: relaxed_trade_filters(elite_main, filters)
    elite_main.commodity_price_filters = lambda filters: commodity_price_filters(elite_main, filters)
    elite_main.resolve_trade_context = lambda system_name=None, station_name=None: resolve_trade_context(elite_main, system_name, station_name)
    elite_main.filter_trade_rows_by_context = lambda rows, **kwargs: filter_trade_rows_by_context(elite_main, rows, **kwargs)
    elite_main.rows_for_symbol_with_fallback = lambda symbol, filters, permits, **kwargs: rows_for_symbol_with_fallback(
        elite_main,
        symbol,
        filters,
        permits,
        **kwargs,
    )
    elite_main.app.state.elite55_trade_flow_service_installed = True
