from __future__ import annotations

from typing import Any

SCOPE_TO_ENTRY_TYPES = {
    "commodity": ["commodity"],
    "system": ["system"],
    "station": ["station"],
    "module": ["module"],
    "ship": ["ship"],
    "universal": [None],
}


def _fallback_build_suggestions(
    elite_main: Any,
    q: str,
    *,
    scope: str = "universal",
    limit: int = 8,
    system_name: str | None = None,
) -> list[dict[str, Any]]:
    query = str(q or "").strip()
    if not query:
        return []
    entry_types = SCOPE_TO_ENTRY_TYPES.get(scope, [None])
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for entry_type in entry_types:
        try:
            rows = elite_main.repo.search_name_library(query=query, entry_type=entry_type, limit=max(20, int(limit or 8) * 6))
        except Exception:
            rows = []
        for row in rows or []:
            label = row.get("display_name") or row.get("label") or row.get("name") or row.get("lookup_key")
            score, match_label, variant = elite_main.best_variant_score(
                query,
                label,
                row.get("lookup_key"),
                row.get("secondary"),
                row.get("parent_system"),
            )
            if score <= 0:
                continue
            kind = str(row.get("entry_type") or entry_type or scope or "unknown")
            entity_id = str(row.get("lookup_key") or label or "").strip()
            if not entity_id:
                continue
            dedupe_key = (kind, entity_id.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            secondary = row.get("secondary") or row.get("parent_system") or row.get("category")
            if scope == "station" and system_name and secondary and elite_main.normalize_search_text(secondary) != elite_main.normalize_search_text(system_name):
                continue
            results.append(
                {
                    "kind": kind,
                    "id": entity_id,
                    "label": label or entity_id,
                    "secondary": secondary,
                    "score": score,
                    "match_label": match_label,
                    "match_variant": variant or label or entity_id,
                }
            )
    results.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("label") or "").lower()))
    return results[: max(1, int(limit or 8))]


def build_suggestions(
    elite_main: Any,
    q: str,
    *,
    scope: str = "universal",
    limit: int = 8,
    system_name: str | None = None,
) -> list[dict[str, Any]]:
    original = getattr(elite_main, "_elite55_original_build_suggestions", None)
    if callable(original):
        result = original(q, scope=scope, limit=limit, system_name=system_name)
        if isinstance(result, list):
            return result
    return _fallback_build_suggestions(elite_main, q, scope=scope, limit=limit, system_name=system_name)


def install_suggestion_engine_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_suggestion_engine_service_installed", False):
        return

    elite_main._elite55_original_build_suggestions = getattr(elite_main, "build_suggestions", None)
    elite_main.build_suggestions = lambda q, **kwargs: build_suggestions(elite_main, q, **kwargs)
    elite_main.app.state.elite55_suggestion_engine_service_installed = True
