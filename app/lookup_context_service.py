from __future__ import annotations

from typing import Any


def build_suggest_payload(
    elite_main: Any,
    q: str,
    *,
    scope: str = "universal",
    limit: int = 8,
    system_name: str | None = None,
) -> dict[str, Any]:
    return {
        "query": q,
        "scope": scope,
        "results": elite_main.build_suggestions(q, scope=scope, limit=limit, system_name=system_name),
        "engine_status": elite_main.build_engine_status(),
    }


def build_trader_memory_payload(elite_main: Any) -> dict[str, Any]:
    return elite_main.trader_memory_snapshot()


def track_trader_memory(elite_main: Any, payload: Any) -> dict[str, Any]:
    elite_main.remember_trader_selection(
        payload.kind,
        payload.entity_id,
        payload.label,
        secondary=getattr(payload, "secondary", None),
        extra=getattr(payload, "extra", None),
    )
    return elite_main.trader_memory_snapshot()


def toggle_trader_favorite(elite_main: Any, payload: Any) -> dict[str, Any]:
    return elite_main.toggle_trader_favorite(
        payload.kind,
        payload.entity_id,
        payload.label,
        secondary=getattr(payload, "secondary", None),
        extra=getattr(payload, "extra", None),
    )


def build_refresh_names_payload(elite_main: Any) -> dict[str, Any]:
    stats = elite_main.name_library_service.refresh()
    return {
        "ok": True,
        "stats": stats,
        "summary": elite_main.repo.name_library_summary(),
        "results": elite_main.repo.search_name_library(limit=40),
    }


def build_names_payload(
    elite_main: Any,
    *,
    q: str = "",
    entry_type: str | None = None,
    limit: int = 60,
) -> dict[str, Any]:
    return {
        "summary": elite_main.repo.name_library_summary(),
        "results": elite_main.repo.search_name_library(query=q, entry_type=entry_type, limit=limit),
    }
