from __future__ import annotations

from typing import Any, Literal


def summarize_market_offer(
    elite_main: Any,
    row: dict[str, Any],
    player_position: dict[str, Any] | None,
    *,
    mode: Literal["buy", "sell"],
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    freshness = round(elite_main.age_hours(row.get("price_updated_at")) or 0, 2)
    confidence = elite_main.row_confidence(row, elite_main.DEFAULT_CONFIDENCE_FILTERS, owned_permits)
    return {
        "commodity_symbol": row["commodity_symbol"],
        "commodity_name": row.get("commodity_name_fr") or row.get("commodity_name"),
        "system_name": row["system_name"],
        "station_name": row["station_name"],
        "market_id": row["market_id"],
        "distance_ls": row.get("distance_to_arrival"),
        "landing_pad": row.get("landing_pad"),
        "price": row["buy_price"] if mode == "buy" else row["sell_price"],
        "stock": row.get("stock"),
        "demand": row.get("demand"),
        "freshness_hours": freshness,
        "distance_from_player_ly": elite_main.euclidean_distance(row, player_position) if player_position else None,
        "confidence_score": confidence,
        "confidence_label": elite_main.confidence_label(confidence),
        "source_name": row.get("price_source") or row.get("source"),
        "badges": elite_main.station_badges(row, owned_permits),
        "accessibility": elite_main.station_accessibility_label(row, owned_permits),
        "updated_at": row.get("price_updated_at"),
    }


def select_best_local_buy(
    elite_main: Any,
    rows: list[dict[str, Any]],
    filters: Any,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    prices = [int(row.get("buy_price") or 0) for row in rows]
    price_min = min(prices)
    price_max = max(prices)
    best_offer: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        distance_from_player = elite_main.euclidean_distance(row, player_position) if player_position else None
        deal_score = elite_main.clamp_score(
            elite_main.relative_value_score(int(row.get("buy_price") or 0), price_min, price_max, higher_is_better=False) * 0.46
            + elite_main.player_distance_confidence(distance_from_player) * 0.24
            + elite_main.ls_confidence(row.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.12
            + elite_main.freshness_confidence(elite_main.age_hours(row.get("price_updated_at")), filters.max_age_hours) * 0.08
            + elite_main.row_confidence(row, filters, owned_permits) * 0.10
        )
        if deal_score <= best_score:
            continue
        offer = summarize_market_offer(elite_main, row, player_position, mode="buy", owned_permits=owned_permits)
        offer["deal_score"] = deal_score
        offer["deal_label"] = "Prix bas + proche"
        best_offer = offer
        best_score = deal_score
    return best_offer


def select_best_local_sell(
    elite_main: Any,
    rows: list[dict[str, Any]],
    filters: Any,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    prices = [int(row.get("sell_price") or 0) for row in rows]
    price_min = min(prices)
    price_max = max(prices)
    best_offer: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        distance_from_player = elite_main.euclidean_distance(row, player_position) if player_position else None
        deal_score = elite_main.clamp_score(
            elite_main.relative_value_score(int(row.get("sell_price") or 0), price_min, price_max, higher_is_better=True) * 0.48
            + elite_main.player_distance_confidence(distance_from_player) * 0.22
            + elite_main.freshness_confidence(elite_main.age_hours(row.get("price_updated_at")), filters.max_age_hours) * 0.12
            + elite_main.ls_confidence(row.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.08
            + elite_main.row_confidence(row, filters, owned_permits) * 0.10
        )
        if deal_score <= best_score:
            continue
        offer = summarize_market_offer(elite_main, row, player_position, mode="sell", owned_permits=owned_permits)
        offer["deal_score"] = deal_score
        offer["deal_label"] = "Prix haut + exécution rapide"
        best_offer = offer
        best_score = deal_score
    return best_offer


def summarize_purchase_plan(
    elite_main: Any,
    row: dict[str, Any],
    quantity: int,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    available = max(0, int(row.get("stock") or 0))
    units = min(quantity, available)
    price = int(row.get("buy_price") or 0)
    confidence = elite_main.row_confidence(row, elite_main.DEFAULT_CONFIDENCE_FILTERS, owned_permits)
    return {
        "commodity_symbol": row["commodity_symbol"],
        "commodity_name": row.get("commodity_name_fr") or row.get("commodity_name"),
        "system_name": row["system_name"],
        "station_name": row["station_name"],
        "market_id": row["market_id"],
        "landing_pad": row.get("landing_pad"),
        "distance_ls": row.get("distance_to_arrival"),
        "price": price,
        "available_units": available,
        "requested_units": quantity,
        "units_covered": units,
        "units_missing": max(0, quantity - units),
        "coverage_percent": elite_main.clamp_score((units / max(quantity, 1)) * 100),
        "total_cost": price * units,
        "freshness_hours": round(elite_main.age_hours(row.get("price_updated_at")) or 0, 2),
        "distance_from_player_ly": elite_main.euclidean_distance(row, player_position) if player_position else None,
        "confidence_score": confidence,
        "confidence_label": elite_main.confidence_label(confidence),
        "badges": elite_main.station_badges(row, owned_permits),
        "accessibility": elite_main.station_accessibility_label(row, owned_permits),
    }


def build_mission_delivery_candidate(
    elite_main: Any,
    source: dict[str, Any],
    destination: dict[str, Any],
    quantity: int,
    filters: Any,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    available = max(0, int(source.get("stock") or 0))
    units = min(quantity, available)
    if units <= 0:
        return None
    route_distance = elite_main.euclidean_distance(source, destination)
    minutes = elite_main.estimate_minutes(route_distance, source.get("distance_to_arrival"), destination.get("distance_to_arrival"), filters.jump_range)
    source_conf = elite_main.row_confidence(source, filters, owned_permits)
    destination_conf = elite_main.clamp_score(
        elite_main.ls_confidence(destination.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.45
        + elite_main.pad_confidence(destination, filters.min_pad_size) * 0.35
        + (100 if elite_main.station_accessible(destination, owned_permits) else 0) * 0.20
    )
    confidence = elite_main.clamp_score((source_conf + destination_conf) / 2)
    target_sell_price = int(destination.get("sell_price") or 0)
    source_buy_price = int(source.get("buy_price") or 0)
    margin_per_unit = target_sell_price - source_buy_price if target_sell_price > 0 else None
    return {
        "commodity_symbol": source["commodity_symbol"],
        "commodity_name": source.get("commodity_name_fr") or source.get("commodity_name"),
        "source_system": source["system_name"],
        "source_station": source["station_name"],
        "source_market_id": source["market_id"],
        "source_buy_price": source_buy_price,
        "source_stock": available,
        "source_distance_ls": source.get("distance_to_arrival"),
        "target_system": destination.get("system_name"),
        "target_station": destination.get("station_name"),
        "target_market_id": destination.get("market_id"),
        "target_distance_ls": destination.get("distance_to_arrival"),
        "target_sell_price": target_sell_price if target_sell_price > 0 else None,
        "route_distance_ly": route_distance,
        "distance_from_player_ly": elite_main.euclidean_distance(source, player_position) if player_position else None,
        "units": units,
        "total_cost": source_buy_price * units,
        "margin_per_unit": margin_per_unit,
        "estimated_minutes": round(minutes, 1),
        "profit_per_minute": round(((margin_per_unit or 0) * units) / max(minutes, 1), 2) if margin_per_unit is not None else 0,
        "freshness_hours": round(elite_main.age_hours(source.get("price_updated_at")) or 0, 2),
        "confidence_score": confidence,
        "confidence_label": elite_main.confidence_label(confidence),
        "route_score": elite_main.clamp_score(
            confidence * 0.42
            + elite_main.freshness_confidence(elite_main.age_hours(source.get("price_updated_at")), filters.max_age_hours) * 0.18
            + elite_main.clamp_score(100 - min(minutes, 35) * 2.0) * 0.22
            + elite_main.clamp_score((units / max(quantity, 1)) * 100) * 0.18
        ),
        "source_badges": elite_main.station_badges(source, owned_permits),
        "target_badges": elite_main.station_badges(destination, owned_permits),
        "accessibility": f"{elite_main.station_accessibility_label(source, owned_permits)} -> {elite_main.station_accessibility_label(destination, owned_permits)}",
    }


def select_route_views(elite_main: Any, routes: list[dict[str, Any]], player: dict[str, Any] | None = None) -> dict[str, Any]:
    if not routes:
        return {
            "best_margin": None,
            "best_margin_per_minute": None,
            "best_trip_profit": None,
            "best_safe_route": None,
            "best_from_current_system": None,
            "best_from_current_station": None,
        }
    current_system = str((player or {}).get("current_system") or "").strip()
    current_market_id = (player or {}).get("current_market_id")
    safe_routes = [row for row in routes if row.get("confidence_score", 0) >= 82 and row.get("freshness_hours", 999) <= 24]
    current_system_routes = [row for row in routes if current_system and row.get("source_system") == current_system]
    current_station_routes = [row for row in routes if current_market_id and row.get("source_market_id") == current_market_id]
    return {
        "best_margin": max(routes, key=lambda row: (row.get("unit_profit", 0), row.get("trip_profit", 0), row.get("route_score", 0))),
        "best_margin_per_minute": max(routes, key=lambda row: (row.get("profit_per_minute", 0), row.get("profit_per_hour", 0), row.get("route_score", 0))),
        "best_trip_profit": max(routes, key=lambda row: (row.get("trip_profit", 0), row.get("profit_per_hour", 0), row.get("route_score", 0))),
        "best_safe_route": max(safe_routes, key=lambda row: (row.get("route_score", 0), row.get("confidence_score", 0), row.get("trip_profit", 0))) if safe_routes else routes[0],
        "best_from_current_system": max(current_system_routes, key=lambda row: (row.get("route_score", 0), row.get("trip_profit", 0))) if current_system_routes else None,
        "best_from_current_station": max(current_station_routes, key=lambda row: (row.get("route_score", 0), row.get("trip_profit", 0))) if current_station_routes else None,
    }


def build_dashboard_decision_cards(
    elite_main: Any,
    rows: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    filters: Any,
    player: dict[str, Any],
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    buy_rows = elite_main.meaningful_buy_rows(rows, filters)
    sell_rows = elite_main.meaningful_sell_rows(rows, filters)
    buy_rows.sort(key=lambda row: (int(row.get("buy_price") or 0), elite_main.age_hours(row.get("price_updated_at")) or 9999))
    sell_rows.sort(key=lambda row: (-int(row.get("sell_price") or 0), -int(row.get("demand") or 0), elite_main.age_hours(row.get("price_updated_at")) or 9999))
    best_buy_row = buy_rows[0] if buy_rows else None
    alternate_sell_rows = [row for row in sell_rows if not best_buy_row or row.get("market_id") != best_buy_row.get("market_id")]
    best_sell_row = alternate_sell_rows[0] if alternate_sell_rows else (sell_rows[0] if sell_rows else None)
    route_views = select_route_views(elite_main, routes, player)
    return {
        "cheapest_buy": summarize_market_offer(elite_main, best_buy_row, player_position, mode="buy", owned_permits=owned_permits) if best_buy_row else None,
        "nearest_buy": select_best_local_buy(elite_main, buy_rows[:40], filters, player_position, owned_permits) if buy_rows else None,
        "highest_sell": summarize_market_offer(elite_main, best_sell_row, player_position, mode="sell", owned_permits=owned_permits) if best_sell_row else None,
        "live_sell": select_best_local_sell(elite_main, sell_rows[:40], filters, player_position, owned_permits) if sell_rows else None,
        **route_views,
    }


def build_watchlist(
    elite_main: Any,
    filters: Any,
    *,
    all_rows: list[dict[str, Any]] | None = None,
    player_position: dict[str, Any] | None = None,
    owned_permits: set[str] | None = None,
) -> list[dict[str, Any]]:
    memory = elite_main.trader_memory_snapshot()
    favorite_symbols = [elite_main.normalize_commodity_symbol(item.get("id")) for item in memory.get("favorites", {}).get("commodity", [])]
    recent_symbols = [elite_main.normalize_commodity_symbol(item.get("id")) for item in memory.get("recents", {}).get("commodity", [])]
    symbols: list[str] = []
    for symbol in [*favorite_symbols, *recent_symbols, *elite_main.WATCHLIST_SYMBOLS]:
        normalized = elite_main.normalize_commodity_symbol(symbol)
        if normalized and normalized not in symbols:
            symbols.append(normalized)
    entries = []
    for symbol in symbols[:8]:
        intel = elite_main.build_commodity_intel(
            symbol,
            filters,
            all_rows=all_rows,
            player_position=player_position,
            owned_permits=owned_permits,
        )
        if not intel.get("resolved"):
            continue
        best_buy = intel["best_buys"][0] if intel.get("best_buys") else None
        best_sell = intel["best_sells"][0] if intel.get("best_sells") else None
        best_route = intel["best_routes"][0] if intel.get("best_routes") else None
        entries.append(
            {
                "symbol": intel["symbol"],
                "commodity_name": intel["commodity_name"],
                "best_buy": best_buy,
                "best_sell": best_sell,
                "best_route": best_route,
                "spread": (intel.get("quick_trade") or {}).get("spread"),
                "favorite": any(item.get("id") == intel["symbol"] for item in memory.get("favorites", {}).get("commodity", [])),
            }
        )
    return entries


def install_trade_recommendation_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_recommendation_service_installed", False):
        return

    elite_main.summarize_market_offer = lambda row, player_position=None, mode="buy", owned_permits=None: summarize_market_offer(
        elite_main,
        row,
        player_position,
        mode=mode,
        owned_permits=owned_permits,
    )
    elite_main.select_best_local_buy = lambda rows, filters, player_position=None, owned_permits=None: select_best_local_buy(
        elite_main,
        rows,
        filters,
        player_position,
        owned_permits,
    )
    elite_main.select_best_local_sell = lambda rows, filters, player_position=None, owned_permits=None: select_best_local_sell(
        elite_main,
        rows,
        filters,
        player_position,
        owned_permits,
    )
    elite_main.summarize_purchase_plan = lambda row, quantity, player_position=None, owned_permits=None: summarize_purchase_plan(
        elite_main,
        row,
        quantity,
        player_position,
        owned_permits,
    )
    elite_main.build_mission_delivery_candidate = lambda source, destination, quantity, filters, player_position=None, owned_permits=None: build_mission_delivery_candidate(
        elite_main,
        source,
        destination,
        quantity,
        filters,
        player_position,
        owned_permits,
    )
    elite_main.select_route_views = lambda routes, player=None: select_route_views(elite_main, routes, player)
    elite_main.build_dashboard_decision_cards = lambda rows, routes, filters, player, player_position=None, owned_permits=None: build_dashboard_decision_cards(
        elite_main,
        rows,
        routes,
        filters,
        player,
        player_position,
        owned_permits,
    )
    elite_main.build_watchlist = lambda filters, **kwargs: build_watchlist(elite_main, filters, **kwargs)
    elite_main.app.state.elite55_trade_recommendation_service_installed = True
