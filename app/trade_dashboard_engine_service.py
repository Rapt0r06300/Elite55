from __future__ import annotations

from typing import Any


def build_trade_dashboard(
    elite_main: Any,
    filters: Any,
    *,
    player: dict[str, Any] | None = None,
    all_rows: list[dict[str, Any]] | None = None,
    owned_permits: set[str] | None = None,
    player_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    player = player or elite_main.player_runtime_snapshot(elite_main.repo.get_all_state())
    all_rows = all_rows if all_rows is not None else elite_main.repo.filtered_trade_rows(filters)
    owned_permits = owned_permits if owned_permits is not None else elite_main.known_owned_permits()
    if player_position is None:
        player_position = elite_main.repo.system_position(player.get("current_system"))
    rows = [row for row in all_rows if elite_main.station_allowed(row, filters, owned_permits)]
    exports_by_symbol: dict[str, list[dict[str, Any]]] = {}
    imports_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = row["commodity_symbol"]
        if int(row.get("buy_price") or 0) > 0 and int(row.get("stock") or 0) > 0:
            exports_by_symbol.setdefault(symbol, []).append(row)
        if int(row.get("sell_price") or 0) > 0 and int(row.get("demand") or 0) > 0:
            imports_by_symbol.setdefault(symbol, []).append(row)

    routes = []
    best_by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for symbol, sources in exports_by_symbol.items():
        targets = imports_by_symbol.get(symbol, [])
        if not targets:
            continue
        for source in sources:
            for target in targets:
                route = elite_main.build_route_candidate(source, target, filters, player_position, owned_permits)
                if not route:
                    continue
                routes.append(route)
                key = (source["market_id"], target["market_id"])
                if key not in best_by_pair or route["trip_profit"] > best_by_pair[key]["trip_profit"]:
                    best_by_pair[key] = route

    routes.sort(key=lambda row: (row["route_score"], row["profit_per_hour"], row["trip_profit"], row["unit_profit"]), reverse=True)

    loops = []
    seen: set[tuple[int, int]] = set()
    for (a, b), outbound in best_by_pair.items():
        reverse = best_by_pair.get((b, a))
        if not reverse:
            continue
        canonical = tuple(sorted((a, b)))
        if canonical in seen:
            continue
        seen.add(canonical)
        total_profit = outbound["trip_profit"] + reverse["trip_profit"]
        total_minutes = outbound["estimated_minutes"] + reverse["estimated_minutes"]
        confidence_score = elite_main.clamp_score((outbound["confidence_score"] + reverse["confidence_score"]) / 2)
        loops.append(
            {
                "from_system": outbound["source_system"],
                "from_station": outbound["source_station"],
                "to_system": outbound["target_system"],
                "to_station": outbound["target_station"],
                "go_commodity": outbound["commodity_name"],
                "return_commodity": reverse["commodity_name"],
                "go_profit": outbound["trip_profit"],
                "return_profit": reverse["trip_profit"],
                "total_profit": total_profit,
                "profit_per_hour": round(total_profit * 60 / total_minutes, 2),
                "freshness_hours": max(outbound["freshness_hours"], reverse["freshness_hours"]),
                "confidence_score": confidence_score,
                "confidence_label": elite_main.confidence_label(confidence_score),
                "route_score": elite_main.clamp_score((outbound["route_score"] + reverse["route_score"]) / 2),
            }
        )
    loops.sort(key=lambda row: (row["route_score"], row["profit_per_hour"], row["total_profit"]), reverse=True)

    return {
        "player": player,
        "routes": routes[: filters.max_results],
        "loops": loops[: filters.max_results],
        "route_views": elite_main.select_route_views(routes, player),
        "dataset": {
            "rows": len(rows),
            "export_symbols": len(exports_by_symbol),
            "import_symbols": len(imports_by_symbol),
        },
        "decision_cards": elite_main.build_dashboard_decision_cards(rows, routes, filters, player, player_position, owned_permits),
        "watchlist": elite_main.build_watchlist(
            filters,
            all_rows=all_rows,
            player_position=player_position,
            owned_permits=owned_permits,
        ),
        "local_sync": elite_main.repo.get_state("source_local_sync_stats", {}),
        "current_market": elite_main.repo.current_market(),
        "knowledge": elite_main.repo.knowledge(),
    }


def install_trade_dashboard_engine_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_dashboard_engine_service_installed", False):
        return

    elite_main.build_trade_dashboard = lambda filters, **kwargs: build_trade_dashboard(elite_main, filters, **kwargs)
    elite_main.app.state.elite55_trade_dashboard_engine_service_installed = True
