from __future__ import annotations

from typing import Any


def default_route_request(elite_main: Any) -> Any:
    return elite_main.RouteRequest(
        cargo_capacity=elite_main.repo.get_state("cargo_capacity_override"),
        jump_range=elite_main.repo.get_state("jump_range_override"),
        min_pad_size=elite_main.repo.get_state("preferred_pad_size", "M"),
    )


def build_filters(elite_main: Any, payload: Any) -> Any:
    cargo_capacity = payload.cargo_capacity
    if cargo_capacity is None:
        cargo_capacity = elite_main.repo.get_state("cargo_capacity_override")
    if cargo_capacity is None:
        cargo_capacity = elite_main.repo.get_state("cargo_capacity", 0)
    if not cargo_capacity:
        cargo_capacity = 100

    jump_range = payload.jump_range
    if jump_range is None:
        jump_range = elite_main.repo.get_state("jump_range_override")
    if jump_range is None:
        jump_range = elite_main.repo.get_state("jump_range", 15)

    return elite_main.TradeFilters(
        cargo_capacity=int(cargo_capacity or 0),
        jump_range=float(jump_range or 15),
        max_age_hours=payload.max_age_hours,
        max_station_distance_ls=payload.max_station_distance_ls,
        min_profit_unit=payload.min_profit_unit,
        min_buy_stock=payload.min_buy_stock,
        min_sell_demand=payload.min_sell_demand,
        min_pad_size=payload.min_pad_size,
        include_planetary=payload.include_planetary,
        include_settlements=payload.include_settlements,
        include_fleet_carriers=payload.include_fleet_carriers,
        no_surprise=payload.no_surprise,
        max_results=payload.max_results,
    )


def tracked_live_commodity_symbols(elite_main: Any) -> set[str]:
    tracked = {elite_main.normalize_commodity_symbol(symbol) for symbol in elite_main.WATCHLIST_SYMBOLS}
    focus_symbol = elite_main.normalize_commodity_symbol(elite_main.repo.get_state("focus_commodity"))
    mission_symbol = elite_main.normalize_commodity_symbol(elite_main.repo.get_state("mission_commodity"))
    if focus_symbol:
        tracked.add(focus_symbol)
    if mission_symbol:
        tracked.add(mission_symbol)
    return {symbol for symbol in tracked if symbol}


def install_trade_config_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_config_service_installed", False):
        return

    elite_main.default_route_request = lambda: default_route_request(elite_main)
    elite_main.build_filters = lambda payload: build_filters(elite_main, payload)
    elite_main.tracked_live_commodity_symbols = lambda: tracked_live_commodity_symbols(elite_main)
    elite_main.app.state.elite55_trade_config_service_installed = True
