from __future__ import annotations

from typing import Any


DEFAULT_PERMIT_LABELS = {
    "sol": "Sol",
    "permit": "Permit requis",
}


def _normalize_permit_name(value: Any) -> str:
    return str(value or "").strip().lower()


def known_owned_permits(elite_main: Any) -> set[str]:
    original = getattr(elite_main, "_elite55_original_known_owned_permits", None)
    if callable(original):
        result = original()
        return {item for item in (str(value).strip().lower() for value in (result or [])) if item}
    raw = elite_main.repo.get_state("owned_permits", [])
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    return {item for item in (_normalize_permit_name(value) for value in (raw or [])) if item}


def known_owned_permit_labels(elite_main: Any) -> list[str]:
    original = getattr(elite_main, "_elite55_original_known_owned_permit_labels", None)
    if callable(original):
        result = [str(value).strip() for value in (original() or []) if str(value).strip()]
        if result:
            return result
    permits = sorted(known_owned_permits(elite_main))
    return [DEFAULT_PERMIT_LABELS.get(value, value.title()) for value in permits]


def station_accessible(elite_main: Any, row: dict[str, Any], permits: set[str] | None = None) -> bool:
    original = getattr(elite_main, "_elite55_original_station_accessible", None)
    if callable(original):
        return bool(original(row, permits))
    current_permits = permits if permits is not None else known_owned_permits(elite_main)
    requires_permit = row.get("requires_permit")
    permit_name = _normalize_permit_name(row.get("permit_name"))
    if not requires_permit and not permit_name:
        return True
    if not permit_name:
        permit_name = "permit"
    return permit_name in current_permits


def station_accessibility_label(elite_main: Any, row: dict[str, Any], permits: set[str] | None = None) -> str:
    original = getattr(elite_main, "_elite55_original_station_accessibility_label", None)
    if callable(original):
        result = str(original(row, permits) or "").strip()
        if result:
            return result
    if station_accessible(elite_main, row, permits):
        return "Acces direct"
    permit_name = _normalize_permit_name(row.get("permit_name"))
    if permit_name:
        return f"Permit requis: {permit_name.title()}"
    return "Acces restreint"


def install_permit_access_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_permit_access_service_installed", False):
        return

    elite_main._elite55_original_known_owned_permits = getattr(elite_main, "known_owned_permits", None)
    elite_main._elite55_original_known_owned_permit_labels = getattr(elite_main, "known_owned_permit_labels", None)
    elite_main._elite55_original_station_accessible = getattr(elite_main, "station_accessible", None)
    elite_main._elite55_original_station_accessibility_label = getattr(elite_main, "station_accessibility_label", None)

    elite_main.known_owned_permits = lambda: known_owned_permits(elite_main)
    elite_main.known_owned_permit_labels = lambda: known_owned_permit_labels(elite_main)
    elite_main.station_accessible = lambda row, permits=None: station_accessible(elite_main, row, permits)
    elite_main.station_accessibility_label = lambda row, permits=None: station_accessibility_label(elite_main, row, permits)
    elite_main.app.state.elite55_permit_access_service_installed = True
