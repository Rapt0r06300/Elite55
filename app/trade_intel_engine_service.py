from __future__ import annotations

from typing import Any


def build_commodity_intel(
    elite_main: Any,
    query: str | None,
    filters: Any,
    *,
    origin_system: str | None = None,
    origin_station: str | None = None,
    target_system: str | None = None,
    target_station: str | None = None,
    all_rows: list[dict[str, Any]] | None = None,
    player_position: dict[str, Any] | None = None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    resolved = elite_main.repo.resolve_commodity(query)
    origin_context = elite_main.resolve_trade_context(origin_system, origin_station)
    target_context = elite_main.resolve_trade_context(target_system, target_station)
    if not resolved:
        return {
            "query": query,
            "resolved": False,
            "symbol": None,
            "commodity_name": None,
            "selection_context": {"origin": origin_context, "target": target_context},
            "best_buys": [],
            "best_sells": [],
            "best_routes": [],
            "history": [],
            "quick_trade": None,
            "decision_cards": {},
            "route_views": {},
        }

    permits = owned_permits if owned_permits is not None else elite_main.known_owned_permits()
    if player_position is None:
        player_position = elite_main.repo.system_position(elite_main.repo.get_state("current_system"))
    market_filters = elite_main.commodity_price_filters(filters)
    strict_base_rows = elite_main.repo.filtered_trade_rows(market_filters, commodity_symbols=[resolved["symbol"]])
    strict_rows = [
        row
        for row in strict_base_rows
        if row["commodity_symbol"] == resolved["symbol"] and elite_main.station_allowed(row, market_filters, permits)
    ]
    strict_buy_rows = elite_main.meaningful_buy_rows(
        elite_main.filter_trade_rows_by_context(
            strict_rows,
            system_name=origin_context.get("system_name"),
            market_id=origin_context.get("market_id"),
        ),
        market_filters,
    )
    strict_sell_rows = elite_main.meaningful_sell_rows(
        elite_main.filter_trade_rows_by_context(
            strict_rows,
            system_name=target_context.get("system_name"),
            market_id=target_context.get("market_id"),
        ),
        market_filters,
    )

    fallback_used = False
    fallback_buy_used = False
    fallback_sell_used = False
    buy_rows = list(strict_buy_rows)
    sell_rows = list(strict_sell_rows)

    if not strict_buy_rows or not strict_sell_rows:
        relaxed_filters = elite_main.relaxed_trade_filters(market_filters)
        fallback_base_rows = elite_main.repo.filtered_trade_rows(relaxed_filters, commodity_symbols=[resolved["symbol"]])
        fallback_rows = [
            row
            for row in fallback_base_rows
            if row["commodity_symbol"] == resolved["symbol"] and elite_main.station_allowed(row, relaxed_filters, permits)
        ]
        fallback_buy_rows = elite_main.meaningful_buy_rows(
            elite_main.filter_trade_rows_by_context(
                fallback_rows,
                system_name=origin_context.get("system_name"),
                market_id=origin_context.get("market_id"),
            ),
            relaxed_filters,
        )
        fallback_sell_rows = elite_main.meaningful_sell_rows(
            elite_main.filter_trade_rows_by_context(
                fallback_rows,
                system_name=target_context.get("system_name"),
                market_id=target_context.get("market_id"),
            ),
            relaxed_filters,
        )
        if not strict_buy_rows and fallback_buy_rows:
            buy_rows = fallback_buy_rows
            fallback_buy_used = True
            fallback_used = True
        if not strict_sell_rows and fallback_sell_rows:
            sell_rows = fallback_sell_rows
            fallback_sell_used = True
            fallback_used = True

    buy_rows.sort(key=lambda row: (int(row["buy_price"]), elite_main.age_hours(row.get("price_updated_at")) or 9999, -int(row.get("stock") or 0)))
    sell_rows.sort(key=lambda row: (-int(row["sell_price"]), -int(row.get("demand") or 0), elite_main.age_hours(row.get("price_updated_at")) or 9999))

    routes = []
    for source in buy_rows[:16]:
        for target in sell_rows[:16]:
            candidate = elite_main.build_route_candidate(source, target, market_filters, player_position, permits)
            if candidate:
                routes.append(candidate)
    routes.sort(key=lambda row: (row["route_score"], row["profit_per_hour"], row["trip_profit"], row["unit_profit"]), reverse=True)
    history = elite_main.repo.commodity_history(resolved["symbol"], limit=32)
    best_buy = elite_main.summarize_market_offer(buy_rows[0], player_position, mode="buy", owned_permits=permits) if buy_rows else None
    alternate_sell_rows = [row for row in sell_rows if not best_buy or row.get("market_id") != best_buy.get("market_id")]
    top_sell_rows = alternate_sell_rows
    best_sell = elite_main.summarize_market_offer(top_sell_rows[0], player_position, mode="sell", owned_permits=permits) if top_sell_rows else None
    best_near_buy = elite_main.select_best_local_buy(buy_rows[:20], market_filters, player_position, permits) if buy_rows else None
    best_live_sell = elite_main.select_best_local_sell(top_sell_rows[:20], market_filters, player_position, permits) if top_sell_rows else None
    best_route = routes[0] if routes else None
    route_views = elite_main.select_route_views(routes, {"current_system": elite_main.repo.get_state("current_system"), "current_market_id": elite_main.repo.get_state("current_market_id")})

    return {
        "query": query,
        "resolved": True,
        "symbol": resolved["symbol"],
        "commodity_name": resolved["commodity_name"],
        "selection_context": {"origin": origin_context, "target": target_context},
        "best_buys": [elite_main.summarize_market_offer(row, player_position, mode="buy", owned_permits=permits) for row in buy_rows[:8]],
        "best_sells": [elite_main.summarize_market_offer(row, player_position, mode="sell", owned_permits=permits) for row in top_sell_rows[:8]],
        "best_routes": routes[:8],
        "history": history,
        "fallback_used": fallback_used,
        "fallback_buy_used": fallback_buy_used,
        "fallback_sell_used": fallback_sell_used,
        "sell_same_market_only": bool(sell_rows) and not bool(top_sell_rows),
        "route_views": route_views,
        "decision_cards": {
            "cheapest_buy": best_buy,
            "nearest_buy": best_near_buy,
            "highest_sell": best_sell,
            "live_sell": best_live_sell,
            **route_views,
        },
        "quick_trade": {
            "best_buy": best_buy,
            "best_near_buy": best_near_buy,
            "best_sell": best_sell,
            "best_live_sell": best_live_sell,
            "best_route": best_route,
            "spread": (int(best_sell["price"]) - int(best_buy["price"])) if best_buy and best_sell else None,
            "history_points": len(history),
        },
    }


def build_mission_intel(
    elite_main: Any,
    commodity_query: str | None,
    quantity: int,
    filters: Any,
    *,
    target_system: str | None = None,
    target_station: str | None = None,
    all_rows: list[dict[str, Any]] | None = None,
    player_position: dict[str, Any] | None = None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    requested_quantity = max(1, int(quantity or 1))
    resolved = elite_main.repo.resolve_commodity(commodity_query)
    if not resolved:
        return {
            "query": commodity_query,
            "resolved": False,
            "commodity_name": None,
            "quantity": requested_quantity,
            "target_system": target_system,
            "target_station": target_station,
            "best_sources": [],
            "best_routes": [],
            "target": None,
            "history": [],
            "alternatives": [],
            "stock_status": None,
            "route_views": {},
        }

    if player_position is None:
        player_position = elite_main.repo.system_position(elite_main.repo.get_state("current_system"))
    permits = owned_permits if owned_permits is not None else elite_main.known_owned_permits()
    rows, fallback_used = elite_main.rows_for_symbol_with_fallback(resolved["symbol"], filters, permits, all_rows=all_rows)
    buy_rows = elite_main.meaningful_buy_rows(rows, filters)
    sell_rows = elite_main.meaningful_sell_rows(rows, filters)
    buy_rows.sort(key=lambda row: (int(row.get("buy_price") or 0), -(int(row.get("stock") or 0)), elite_main.age_hours(row.get("price_updated_at")) or 9999))
    sell_rows.sort(key=lambda row: (-int(row.get("sell_price") or 0), -(int(row.get("demand") or 0)), elite_main.age_hours(row.get("price_updated_at")) or 9999))

    resolved_target_system = elite_main.repo.resolve_system(target_system) if target_system else None
    target_system_name = resolved_target_system.get("name") if resolved_target_system else target_system
    target = elite_main.repo.find_station(system_name=target_system_name, station_name=target_station)
    if target is None and target_station:
        target = elite_main.repo.resolve_station(target_station, system_name=target_system_name)
    if target is None and target_system:
        position = elite_main.repo.system_position(target_system_name)
        if position:
            target = {
                "market_id": None,
                "system_name": target_system_name,
                "station_name": target_station or "Destination mission",
                "distance_to_arrival": None,
                "landing_pad": filters.min_pad_size,
                "has_market": 1,
                "is_planetary": 0,
                "is_odyssey": 0,
                "is_fleet_carrier": 0,
                "requires_permit": 0,
                "permit_name": None,
                "x": position.get("x"),
                "y": position.get("y"),
                "z": position.get("z"),
                "sell_price": 0,
            }

    sources = [elite_main.summarize_purchase_plan(row, requested_quantity, player_position, owned_permits=permits) for row in buy_rows[:12]]
    routes: list[dict[str, Any]] = []
    if target is not None:
        for source in buy_rows[:20]:
            candidate = elite_main.build_mission_delivery_candidate(source, target, requested_quantity, filters, player_position, permits)
            if candidate:
                routes.append(candidate)
    else:
        mission_filters = elite_main.TradeFilters(
            cargo_capacity=requested_quantity,
            jump_range=filters.jump_range,
            max_age_hours=filters.max_age_hours,
            max_station_distance_ls=filters.max_station_distance_ls,
            min_profit_unit=0,
            min_buy_stock=filters.min_buy_stock,
            min_sell_demand=filters.min_sell_demand,
            min_pad_size=filters.min_pad_size,
            include_planetary=filters.include_planetary,
            include_settlements=filters.include_settlements,
            include_fleet_carriers=filters.include_fleet_carriers,
            no_surprise=filters.no_surprise,
            max_results=filters.max_results,
        )
        for source in buy_rows[:16]:
            for target_row in sell_rows[:16]:
                candidate = elite_main.build_route_candidate(source, target_row, mission_filters, player_position, permits)
                if candidate:
                    candidate["units"] = min(candidate["units"], requested_quantity)
                    candidate["trip_profit"] = candidate["unit_profit"] * candidate["units"]
                    candidate["profit_per_hour"] = round(candidate["trip_profit"] * 60 / max(candidate["estimated_minutes"], 1), 2)
                    candidate["profit_per_minute"] = round(candidate["trip_profit"] / max(candidate["estimated_minutes"], 1), 2)
                    candidate["total_cost"] = int(candidate["source_buy_price"] or 0) * candidate["units"]
                    routes.append(candidate)
    routes.sort(key=lambda row: (row.get("route_score", 0), row.get("trip_profit", 0), -row.get("estimated_minutes", 0)), reverse=True)
    best_covered = max((item.get("units_covered", 0) for item in sources), default=0)
    stock_status = {
        "requested_units": requested_quantity,
        "max_covered_units": best_covered,
        "shortfall_units": max(0, requested_quantity - best_covered),
        "coverage_percent": elite_main.clamp_score((best_covered / max(requested_quantity, 1)) * 100),
        "full_coverage": best_covered >= requested_quantity,
    }

    return {
        "query": commodity_query,
        "resolved": True,
        "symbol": resolved["symbol"],
        "commodity_name": resolved["commodity_name"],
        "quantity": requested_quantity,
        "target_system": target_system_name,
        "target_station": target_station,
        "target": target,
        "best_sources": sources[:8],
        "best_routes": routes[:8],
        "history": elite_main.repo.commodity_history(resolved["symbol"], limit=24),
        "alternatives": [item for item in sources[1:8] if item.get("units_covered", 0) > 0],
        "fallback_used": fallback_used,
        "stock_status": stock_status,
        "route_views": elite_main.select_route_views(routes, {"current_system": elite_main.repo.get_state("current_system"), "current_market_id": elite_main.repo.get_state("current_market_id")}),
    }


def install_trade_intel_engine_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_intel_engine_service_installed", False):
        return

    elite_main.build_commodity_intel = lambda query, filters, **kwargs: build_commodity_intel(elite_main, query, filters, **kwargs)
    elite_main.build_mission_intel = lambda commodity_query, quantity, filters, **kwargs: build_mission_intel(
        elite_main,
        commodity_query,
        quantity,
        filters,
        **kwargs,
    )
    elite_main.app.state.elite55_trade_intel_engine_service_installed = True
