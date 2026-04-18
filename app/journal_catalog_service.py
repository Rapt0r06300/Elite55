from __future__ import annotations

from typing import Any


def decode_status_flags(elite_main: Any, flags: Any, flags2: Any) -> dict[str, bool]:
    flags_value = int(flags or 0)
    flags2_value = int(flags2 or 0)
    decoded = {name: bool(flags_value & mask) for name, mask in elite_main.STATUS_FLAG_BITS.items()}
    decoded.update({name: bool(flags2_value & mask) for name, mask in elite_main.STATUS_FLAG2_BITS.items()})
    return decoded


def market_file_is_fresh(elite_main: Any, path: Any, timestamp: str | None) -> bool:
    if not path.exists():
        return False
    reference_dt = elite_main.parse_dt(timestamp)
    if reference_dt:
        age = elite_main.age_minutes(timestamp)
        return age is not None and float(age or 0) <= elite_main.LOCAL_MARKET_MAX_AGE_MINUTES
    file_age_minutes = (elite_main.time.time() - path.stat().st_mtime) / 60
    return file_age_minutes <= elite_main.LOCAL_MARKET_MAX_AGE_MINUTES


def source_priority(elite_main: Any, name: str | None) -> int:
    return int((elite_main.NAME_SOURCE_PRIORITY or {}).get(name or "", 0))


def format_ship_name(elite_main: Any, code: str) -> str:
    normalized = elite_main.normalize_ship_code(code)
    if normalized in elite_main.SHIP_CODE_FALLBACKS:
        return elite_main.SHIP_CODE_FALLBACKS[normalized]
    text = normalized.replace("_", " ").title().replace("Mk Iii", "Mk III").replace("Mk Ii", "Mk II").replace("Mk Iv", "Mk IV").replace("Mk V", "Mk V")
    return text or str(code)


def derive_armour_name(elite_main: Any, module_code: str) -> str | None:
    key = elite_main.normalize_module_key(module_code)
    for suffix, label in (elite_main.ARMOUR_VARIANT_FR or {}).items():
        if key.endswith(f"_{suffix}"):
            return label
    return None


def derive_module_name_fr(elite_main: Any, module_code: str, family_map: dict[str, str]) -> str | None:
    key = elite_main.normalize_module_key(module_code)
    direct = family_map.get(key) or elite_main.MODULE_FAMILY_FR_OVERRIDES.get(key)
    if direct:
        return direct
    armour_name = derive_armour_name(elite_main, key)
    if armour_name:
        return armour_name
    family = elite_main.module_family_key(key)
    return family_map.get(family) or elite_main.MODULE_FAMILY_FR_OVERRIDES.get(family)


def better_price_candidate(elite_main: Any, candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None:
        return True
    candidate_dt = elite_main.parse_dt(candidate.get("updated_at"))
    current_dt = elite_main.parse_dt(current.get("updated_at"))
    if candidate_dt and current_dt and candidate_dt != current_dt:
        return candidate_dt > current_dt
    if candidate_dt and not current_dt:
        return True
    if not candidate_dt and current_dt:
        return False
    candidate_fields = sum(1 for field in ("buy_price", "sell_price", "demand", "stock") if int(candidate.get(field) or 0) > 0)
    current_fields = sum(1 for field in ("buy_price", "sell_price", "demand", "stock") if int(current.get(field) or 0) > 0)
    if candidate_fields != current_fields:
        return candidate_fields > current_fields
    return source_priority(elite_main, candidate.get("source")) >= source_priority(elite_main, current.get("source"))


def infer_pad_size(station_type: str | None, max_landing_pad: int | None = None) -> str:
    if max_landing_pad == 3:
        return "L"
    if max_landing_pad == 2:
        return "M"
    if max_landing_pad == 1:
        return "S"
    text = (station_type or "").lower()
    if "carrier" in text or "starport" in text or "port" in text or "megaship" in text or "drake-class" in text:
        return "L"
    if "outpost" in text or "settlement" in text:
        return "M"
    return "?"


def is_planetary(station_type: str | None) -> bool:
    text = (station_type or "").lower()
    return "planetary" in text or "surface" in text or "onfoot" in text or "settlement" in text


def is_odyssey_station(station_type: str | None) -> bool:
    text = (station_type or "").lower()
    return "onfoot" in text or "settlement" in text


def is_fleet_carrier(station_type: str | None) -> bool:
    return "carrier" in (station_type or "").lower()


def localised(event: dict[str, Any], key: str) -> Any:
    return event.get(f"{key}_Localised") or event.get(key)


def install_journal_catalog_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_journal_catalog_service_installed", False):
        return

    elite_main.decode_status_flags = lambda flags, flags2: decode_status_flags(elite_main, flags, flags2)
    elite_main.market_file_is_fresh = lambda path, timestamp=None: market_file_is_fresh(elite_main, path, timestamp)
    elite_main.source_priority = lambda name=None: source_priority(elite_main, name)
    elite_main.format_ship_name = lambda code: format_ship_name(elite_main, code)
    elite_main.derive_armour_name = lambda module_code: derive_armour_name(elite_main, module_code)
    elite_main.derive_module_name_fr = lambda module_code, family_map: derive_module_name_fr(elite_main, module_code, family_map)
    elite_main.better_price_candidate = lambda candidate, current=None: better_price_candidate(elite_main, candidate, current)
    elite_main.infer_pad_size = infer_pad_size
    elite_main.is_planetary = is_planetary
    elite_main.is_odyssey_station = is_odyssey_station
    elite_main.is_fleet_carrier = is_fleet_carrier
    elite_main.localised = localised
    elite_main.app.state.elite55_journal_catalog_service_installed = True
