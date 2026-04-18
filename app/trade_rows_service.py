from __future__ import annotations

from typing import Any


def build_default_confidence_filters(elite_main: Any) -> Any:
    request = elite_main.default_route_request()
    return elite_main.build_filters(request)


def station_badges(elite_main: Any, row: dict[str, Any], owned_permits: set[str] | None = None) -> list[str]:
    original = getattr(elite_main, "_elite55_original_station_badges", None)
    if callable(original):
        result = original(row, owned_permits)
        if isinstance(result, list) and result:
            return result
    badges: list[str] = []
    landing_pad = str(row.get("landing_pad") or "?").upper()
    if landing_pad and landing_pad != "?":
        badges.append(f"Pad {landing_pad}")
    if row.get("is_planetary"):
        badges.append("Planétaire")
    if row.get("is_odyssey"):
        badges.append("Odyssey")
    if row.get("is_fleet_carrier"):
        badges.append("Carrier")
    if row.get("has_market"):
        badges.append("Marché")
    source_name = str(row.get("price_source") or row.get("source") or "").strip().lower()
    if source_name == "journal_market":
        badges.append("Live")
    elif source_name:
        badges.append(source_name.replace("_", " ").title())
    if not elite_main.station_accessible(row, owned_permits):
        badges.append("Permit")
    seen: set[str] = set()
    unique: list[str] = []
    for badge in badges:
        if badge in seen:
            continue
        seen.add(badge)
        unique.append(badge)
    return unique


def meaningful_buy_rows(elite_main: Any, rows: list[dict[str, Any]], filters: Any) -> list[dict[str, Any]]:
    original = getattr(elite_main, "_elite55_original_meaningful_buy_rows", None)
    if callable(original):
        result = original(rows, filters)
        if isinstance(result, list):
            return result
    filtered: list[dict[str, Any]] = []
    minimum_stock = max(0, int(getattr(filters, "min_buy_stock", 0) or 0))
    minimum_pad = getattr(filters, "min_pad_size", "M")
    permits = elite_main.known_owned_permits()
    for row in rows or []:
        if int(row.get("buy_price") or 0) <= 0:
            continue
        if int(row.get("stock") or 0) < minimum_stock:
            continue
        if elite_main.pad_confidence(row, minimum_pad) <= 0:
            continue
        if not elite_main.station_accessible(row, permits):
            continue
        filtered.append(row)
    return filtered


def meaningful_sell_rows(elite_main: Any, rows: list[dict[str, Any]], filters: Any) -> list[dict[str, Any]]:
    original = getattr(elite_main, "_elite55_original_meaningful_sell_rows", None)
    if callable(original):
        result = original(rows, filters)
        if isinstance(result, list):
            return result
    filtered: list[dict[str, Any]] = []
    minimum_demand = max(0, int(getattr(filters, "min_sell_demand", 0) or 0))
    minimum_pad = getattr(filters, "min_pad_size", "M")
    permits = elite_main.known_owned_permits()
    for row in rows or []:
        if int(row.get("sell_price") or 0) <= 0:
            continue
        if int(row.get("demand") or 0) < minimum_demand:
            continue
        if elite_main.pad_confidence(row, minimum_pad) <= 0:
            continue
        if not elite_main.station_accessible(row, permits):
            continue
        filtered.append(row)
    return filtered


def install_trade_rows_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_rows_service_installed", False):
        return

    elite_main._elite55_original_station_badges = getattr(elite_main, "station_badges", None)
    elite_main._elite55_original_meaningful_buy_rows = getattr(elite_main, "meaningful_buy_rows", None)
    elite_main._elite55_original_meaningful_sell_rows = getattr(elite_main, "meaningful_sell_rows", None)

    elite_main.station_badges = lambda row, owned_permits=None: station_badges(elite_main, row, owned_permits)
    elite_main.meaningful_buy_rows = lambda rows, filters: meaningful_buy_rows(elite_main, rows, filters)
    elite_main.meaningful_sell_rows = lambda rows, filters: meaningful_sell_rows(elite_main, rows, filters)
    elite_main.DEFAULT_CONFIDENCE_FILTERS = build_default_confidence_filters(elite_main)
    elite_main.app.state.elite55_trade_rows_service_installed = True
