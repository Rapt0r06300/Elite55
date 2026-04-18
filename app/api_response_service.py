from __future__ import annotations

from typing import Any


def ok_dashboard(dashboard: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "dashboard": dashboard,
    }


def ok_stats_dashboard(stats: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "stats": stats,
        "dashboard": dashboard,
    }


def ok_status(status: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "status": status,
    }


def ok_health(*, build_token: str | None, engine_status: dict[str, Any], market_rows: int, name_library_total: int) -> dict[str, Any]:
    return {
        "ok": True,
        "build_token": build_token,
        "engine_status": engine_status,
        "market_rows": market_rows,
        "name_library_total": name_library_total,
    }
