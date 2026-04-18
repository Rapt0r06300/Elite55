from __future__ import annotations

from typing import Any, Literal


def trader_memory_defaults() -> dict[str, Any]:
    return {
        "recent": {
            "commodity": [],
            "system": [],
            "station": [],
            "module": [],
            "query": [],
        },
        "favorites": {
            "commodity": [],
            "system": [],
            "station": [],
            "module": [],
        },
        "missions": [],
        "ship_profiles": [],
    }


def _normalize_memory_items(elite_main: Any, items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    limit = int(getattr(elite_main, "TRADER_MEMORY_LIMIT", 18) or 18)
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        entity_id = str(raw.get("id") or "").strip()
        if not entity_id:
            continue
        normalized.append(
            {
                "id": entity_id,
                "label": str(raw.get("label") or entity_id),
                "secondary": raw.get("secondary"),
                "updated_at": raw.get("updated_at") or elite_main.utc_now_iso(),
                "count": max(1, int(raw.get("count") or 1)),
                "extra": raw.get("extra") if isinstance(raw.get("extra"), dict) else {},
            }
        )
    return normalized[:limit]


def get_trader_memory(elite_main: Any) -> dict[str, Any]:
    stored = elite_main.repo.get_state("trader_memory", {})
    memory = trader_memory_defaults()
    if not isinstance(stored, dict):
        return memory
    for section in ("recent", "favorites"):
        current = stored.get(section, {})
        if not isinstance(current, dict):
            continue
        for kind in memory[section]:
            memory[section][kind] = _normalize_memory_items(elite_main, current.get(kind, []))
    memory["missions"] = _normalize_memory_items(elite_main, stored.get("missions", []))
    memory["ship_profiles"] = _normalize_memory_items(elite_main, stored.get("ship_profiles", []))
    return memory


def save_trader_memory(elite_main: Any, memory: dict[str, Any]) -> dict[str, Any]:
    elite_main.repo.set_state("trader_memory", memory)
    return memory


def _memory_upsert(
    elite_main: Any,
    items: list[dict[str, Any]],
    entity_id: str,
    label: str,
    *,
    secondary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized_id = str(entity_id).strip()
    if not normalized_id:
        return items
    now = elite_main.utc_now_iso()
    updated: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    limit = int(getattr(elite_main, "TRADER_MEMORY_LIMIT", 18) or 18)
    for item in items:
        if str(item.get("id") or "").strip().lower() == normalized_id.lower():
            previous = item
            continue
        updated.append(item)
    updated.insert(
        0,
        {
            "id": normalized_id,
            "label": label or normalized_id,
            "secondary": secondary,
            "updated_at": now,
            "count": max(1, int((previous or {}).get("count") or 0) + 1),
            "extra": extra or (previous or {}).get("extra") or {},
        },
    )
    return updated[:limit]


def trader_memory_snapshot(elite_main: Any) -> dict[str, Any]:
    memory = get_trader_memory(elite_main)
    return {
        "favorites": memory["favorites"],
        "recents": memory["recent"],
        "last_missions": memory["missions"][:6],
        "last_commodities": memory["recent"]["commodity"][:6],
        "last_systems": memory["recent"]["system"][:6],
        "last_stations": memory["recent"]["station"][:6],
        "ship_profiles": memory["ship_profiles"][:4],
    }


def remember_trader_selection(
    elite_main: Any,
    kind: Literal["commodity", "system", "station", "module", "query"],
    entity_id: str,
    label: str,
    *,
    secondary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = get_trader_memory(elite_main)
    if kind in memory["recent"]:
        memory["recent"][kind] = _memory_upsert(elite_main, memory["recent"][kind], entity_id, label, secondary=secondary, extra=extra)
    return save_trader_memory(elite_main, memory)


def toggle_trader_favorite(
    elite_main: Any,
    kind: Literal["commodity", "system", "station", "module"],
    entity_id: str,
    label: str,
    *,
    secondary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = get_trader_memory(elite_main)
    items = list(memory["favorites"].get(kind, []))
    normalized_id = str(entity_id).strip().lower()
    exists = any(str(item.get("id") or "").strip().lower() == normalized_id for item in items)
    if exists:
        items = [item for item in items if str(item.get("id") or "").strip().lower() != normalized_id]
    else:
        items = _memory_upsert(elite_main, items, entity_id, label, secondary=secondary, extra=extra)
    memory["favorites"][kind] = items[: int(getattr(elite_main, "TRADER_MEMORY_LIMIT", 18) or 18)]
    save_trader_memory(elite_main, memory)
    return trader_memory_snapshot(elite_main)


def remember_trader_query(elite_main: Any, query: str) -> dict[str, Any]:
    clean = str(query or "").strip()
    if not clean:
        return get_trader_memory(elite_main)
    return remember_trader_selection(elite_main, "query", clean, clean)


def remember_mission_plan(
    elite_main: Any,
    commodity_query: str,
    quantity: int,
    *,
    commodity_name: str | None = None,
    target_system: str | None = None,
    target_station: str | None = None,
) -> dict[str, Any]:
    memory = get_trader_memory(elite_main)
    label = commodity_name or commodity_query or "Mission"
    target_label = " / ".join(part for part in [target_system, target_station] if part)
    entry_id = "|".join(
        [
            elite_main.normalize_lookup_key(commodity_query),
            str(max(1, int(quantity or 1))),
            elite_main.normalize_lookup_key(target_system),
            elite_main.normalize_lookup_key(target_station),
        ]
    )
    extra = {
        "commodity_query": commodity_query,
        "commodity_name": commodity_name,
        "quantity": max(1, int(quantity or 1)),
        "target_system": target_system,
        "target_station": target_station,
    }
    memory["missions"] = _memory_upsert(
        elite_main,
        memory["missions"],
        entry_id,
        label,
        secondary=target_label or None,
        extra=extra,
    )
    save_trader_memory(elite_main, memory)
    return trader_memory_snapshot(elite_main)


def remember_ship_profile(elite_main: Any, player: dict[str, Any]) -> dict[str, Any]:
    ship_code = elite_main.normalize_lookup_key(player.get("current_ship_code") or player.get("current_ship_name"))
    if not ship_code:
        return trader_memory_snapshot(elite_main)
    cargo_capacity = int(player.get("cargo_capacity_override") or player.get("cargo_capacity") or 0)
    jump_range = float(player.get("jump_range_override") or player.get("jump_range") or 0.0)
    preferred_pad_size = str(player.get("preferred_pad_size") or elite_main.repo.get_state("preferred_pad_size", "M"))
    label = player.get("current_ship_name") or player.get("current_ship_code") or ship_code
    extra = {
        "ship_code": ship_code,
        "cargo_capacity": cargo_capacity,
        "jump_range": jump_range,
        "preferred_pad_size": preferred_pad_size,
        "system_name": player.get("current_system"),
    }
    memory = get_trader_memory(elite_main)
    memory["ship_profiles"] = _memory_upsert(
        elite_main,
        memory["ship_profiles"],
        ship_code,
        label,
        secondary=player.get("current_system"),
        extra=extra,
    )[:6]
    save_trader_memory(elite_main, memory)
    return trader_memory_snapshot(elite_main)


def memory_flags(elite_main: Any, memory: dict[str, Any], kind: str, entity_id: str) -> tuple[bool, bool, int]:
    normalized_id = str(entity_id or "").strip().lower()
    favorite_items = memory.get("favorites", {}).get(kind, [])
    recent_items = memory.get("recent", {}).get(kind, [])
    favorite = any(str(item.get("id") or "").strip().lower() == normalized_id for item in favorite_items)
    recent = False
    usage_count = 0
    for item in recent_items:
        if str(item.get("id") or "").strip().lower() != normalized_id:
            continue
        recent = True
        usage_count = int(item.get("count") or 0)
        break
    return favorite, recent, usage_count


def install_trader_memory_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trader_memory_service_installed", False):
        return

    elite_main.trader_memory_defaults = lambda: trader_memory_defaults()
    elite_main.get_trader_memory = lambda: get_trader_memory(elite_main)
    elite_main.save_trader_memory = lambda memory: save_trader_memory(elite_main, memory)
    elite_main.trader_memory_snapshot = lambda: trader_memory_snapshot(elite_main)
    elite_main.remember_trader_selection = lambda kind, entity_id, label, **kwargs: remember_trader_selection(
        elite_main,
        kind,
        entity_id,
        label,
        **kwargs,
    )
    elite_main.toggle_trader_favorite = lambda kind, entity_id, label, **kwargs: toggle_trader_favorite(
        elite_main,
        kind,
        entity_id,
        label,
        **kwargs,
    )
    elite_main.remember_trader_query = lambda query: remember_trader_query(elite_main, query)
    elite_main.remember_mission_plan = lambda commodity_query, quantity, **kwargs: remember_mission_plan(
        elite_main,
        commodity_query,
        quantity,
        **kwargs,
    )
    elite_main.remember_ship_profile = lambda player: remember_ship_profile(elite_main, player)
    elite_main.memory_flags = lambda memory, kind, entity_id: memory_flags(elite_main, memory, kind, entity_id)
    elite_main.app.state.elite55_trader_memory_service_installed = True
