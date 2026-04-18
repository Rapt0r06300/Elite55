from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace(" ", "T")
    if normalized.endswith("+00"):
        normalized += ":00"
    if normalized.endswith("Z"):
        normalized = normalized.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def age_hours(value: str | None) -> float | None:
    parsed = parse_dt(value)
    if not parsed:
        return None
    return round((datetime.now(timezone.utc) - parsed).total_seconds() / 3600, 2)


def age_minutes(value: str | None) -> float | None:
    parsed = parse_dt(value)
    if not parsed:
        return None
    return round((datetime.now(timezone.utc) - parsed).total_seconds() / 60, 1)


def normalize_text_key(value: Any) -> str:
    text = str(value or "").strip().replace("\u00A0", " ").lower()
    if text.startswith("$") and text.endswith(";"):
        text = text[1:-1]
    return text


def strip_diacritics(value: Any) -> str:
    text = str(value or "")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_search_text(value: Any) -> str:
    text = strip_diacritics(str(value or "").replace("\u00A0", " "))
    text = text.strip().lower()
    if text.startswith("$") and text.endswith(";"):
        text = text[1:-1]
    return re.sub(r"\s+", " ", text)


def compact_search_key(value: Any) -> str:
    text = normalize_search_text(value)
    text = text.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", text)


def search_words(value: Any) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", normalize_search_text(value)) if token]


def compact_key(value: Any) -> str:
    text = normalize_text_key(value)
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def normalize_lookup_key(value: Any) -> str:
    text = normalize_text_key(value)
    text = text.replace(" ", "_")
    text = text.replace("-", "_")
    text = re.sub(r"[^a-z0-9_]+", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def normalize_category_key(value: Any) -> str:
    text = normalize_text_key(value)
    text = re.sub(r"^.*category_", "", text)
    return compact_key(text)


def normalize_commodity_symbol(raw: Any, *fallbacks: Any) -> str:
    for candidate in (raw, *fallbacks):
        text = normalize_text_key(candidate)
        if not text:
            continue
        text = re.sub(r"_name$", "", text)
        if text.startswith("market_category_"):
            continue
        symbol = compact_key(text)
        if symbol:
            return symbol
    return ""


def normalize_module_key(value: Any) -> str:
    text = normalize_text_key(value)
    return re.sub(r"_name$", "", text)


def module_family_key(value: Any) -> str:
    key = normalize_module_key(value)
    key = re.sub(r"_(fixed|gimbal|turret)_(tiny|smallfree|small|medium|large|huge)$", "", key)
    key = re.sub(r"_size\d+_class\d+$", "", key)
    key = re.sub(r"_grade\d+$", "", key)
    key = re.sub(r"_(mirrored|reactive)$", "", key)
    return key


def normalize_ship_code(value: Any) -> str:
    return normalize_lookup_key(value)


def normalize_permit_name(value: Any) -> str:
    return normalize_search_text(value)


def player_runtime_snapshot(player: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(player)
    flags = dict(enriched.get("status_flags") or {})
    current_station = enriched.get("current_station")
    current_body_name = enriched.get("current_body_name")
    destination_name = enriched.get("destination_name") or ((enriched.get("destination") or {}).get("Name"))
    if isinstance(destination_name, str) and destination_name.startswith("$"):
        destination_name = None

    if flags.get("on_foot"):
        local_mode = "À pied"
    elif flags.get("docked"):
        local_mode = "Amarré"
    elif flags.get("landed"):
        local_mode = "Posé"
    elif flags.get("supercruise"):
        local_mode = "Supercroisière"
    elif flags.get("glide_mode"):
        local_mode = "Glisse orbitale"
    elif flags.get("fsd_jumping") or flags.get("fsd_hyperdrive_charging"):
        local_mode = "Saut hyperespace"
    elif flags.get("fsd_charging"):
        local_mode = "FSD en charge"
    elif current_station:
        local_mode = "Approche station"
    else:
        local_mode = "En vol"

    if flags.get("docked") and current_station:
        station_display = current_station
    elif current_station:
        station_display = f"Approche {current_station}"
    elif current_body_name:
        station_display = current_body_name
    elif destination_name:
        station_display = f"Cap vers {destination_name}"
    else:
        station_display = "En vol"

    if flags.get("docked") and current_station and enriched.get("current_system"):
        location_line = f"{enriched['current_system']} / {current_station}"
    elif enriched.get("current_system") and destination_name:
        location_line = f"{enriched['current_system']} • destination {destination_name}"
    else:
        location_line = enriched.get("current_system") or station_display

    enriched["local_mode"] = local_mode
    enriched["station_display"] = station_display
    enriched["destination_name"] = destination_name
    enriched["location_line"] = location_line
    return enriched


def euclidean_distance(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    coords = [a.get("x"), a.get("y"), a.get("z"), b.get("x"), b.get("y"), b.get("z")]
    if any(value is None for value in coords):
        return None
    return round(
        math.sqrt(
            (a["x"] - b["x"]) ** 2
            + (a["y"] - b["y"]) ** 2
            + (a["z"] - b["z"]) ** 2
        ),
        2,
    )


def install_core_runtime_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_core_runtime_service_installed", False):
        return

    elite_main.utc_now_iso = utc_now_iso
    elite_main.parse_dt = parse_dt
    elite_main.age_hours = age_hours
    elite_main.age_minutes = age_minutes
    elite_main.normalize_text_key = normalize_text_key
    elite_main.strip_diacritics = strip_diacritics
    elite_main.normalize_search_text = normalize_search_text
    elite_main.compact_search_key = compact_search_key
    elite_main.search_words = search_words
    elite_main.compact_key = compact_key
    elite_main.normalize_lookup_key = normalize_lookup_key
    elite_main.normalize_category_key = normalize_category_key
    elite_main.normalize_commodity_symbol = normalize_commodity_symbol
    elite_main.normalize_module_key = normalize_module_key
    elite_main.module_family_key = module_family_key
    elite_main.normalize_ship_code = normalize_ship_code
    elite_main.normalize_permit_name = normalize_permit_name
    elite_main.player_runtime_snapshot = player_runtime_snapshot
    elite_main.euclidean_distance = euclidean_distance
    elite_main.app.state.elite55_core_runtime_service_installed = True
