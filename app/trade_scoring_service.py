from __future__ import annotations

import math
from typing import Any


def clamp_score(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, int(round(value))))


def source_confidence(elite_main: Any, source: str | None) -> int:
    mapping = getattr(elite_main, "SOURCE_CONFIDENCE", {}) or {}
    return int(mapping.get(str(source or "").strip().lower(), 72))


def freshness_confidence(freshness_hours: float | None, max_age_hours: float) -> int:
    if freshness_hours is None:
        return 18
    if max_age_hours <= 0:
        return 100
    ratio = min(max(float(freshness_hours) / max_age_hours, 0.0), 1.4)
    return clamp_score(100 - (ratio * 55))


def ls_confidence(distance_ls: float | None, max_station_distance_ls: int) -> int:
    if distance_ls is None:
        return 62
    if max_station_distance_ls <= 0:
        return 100
    ratio = min(max(float(distance_ls) / max_station_distance_ls, 0.0), 1.5)
    return clamp_score(100 - (ratio * 45))


def pad_confidence(elite_main: Any, row: dict[str, Any], min_pad_size: str) -> int:
    actual = elite_main.PAD_RANK.get(row.get("landing_pad") or "?", 0)
    minimum = elite_main.PAD_RANK.get(min_pad_size, 0)
    if actual <= 0:
        return 55
    if actual < minimum:
        return 0
    return 100 if actual == minimum else 92


def row_confidence(elite_main: Any, row: dict[str, Any], filters: Any, owned_permits: set[str] | None = None) -> int:
    freshness = elite_main.age_hours(row.get("price_updated_at"))
    score = (
        source_confidence(elite_main, row.get("price_source") or row.get("source")) * 0.34
        + freshness_confidence(freshness, filters.max_age_hours) * 0.28
        + ls_confidence(row.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.18
        + pad_confidence(elite_main, row, filters.min_pad_size) * 0.12
        + (100 if elite_main.station_accessible(row, owned_permits) else 0) * 0.08
    )
    return clamp_score(score)


def confidence_label(score: int) -> str:
    if score >= 90:
        return "Très haute"
    if score >= 78:
        return "Haute"
    if score >= 64:
        return "Bonne"
    if score >= 48:
        return "Moyenne"
    return "Prudence"


def estimate_minutes(route_distance_ly: float | None, source_ls: float | None, target_ls: float | None, jump_range: float) -> float:
    jumps = 1
    if route_distance_ly and jump_range > 0:
        jumps = max(1, math.ceil(route_distance_ly / max(jump_range * 0.9, 1)))
    supercruise = ((source_ls or 0) + (target_ls or 0)) / 900
    return max(5.0, jumps * 1.6 + supercruise + 2.2)


def player_distance_confidence(distance_ly: float | None) -> int:
    if distance_ly is None:
        return 58
    return clamp_score(100 - min(float(distance_ly), 120.0) * 0.75)


def relative_value_score(value: int | float, minimum: int | float, maximum: int | float, *, higher_is_better: bool) -> int:
    if maximum <= minimum:
        return 100
    ratio = (float(value) - float(minimum)) / max(float(maximum) - float(minimum), 1.0)
    ratio = min(max(ratio, 0.0), 1.0)
    if higher_is_better:
        return clamp_score(ratio * 100)
    return clamp_score((1.0 - ratio) * 100)


def install_trade_scoring_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_trade_scoring_service_installed", False):
        return

    elite_main.clamp_score = clamp_score
    elite_main.source_confidence = lambda source=None: source_confidence(elite_main, source)
    elite_main.freshness_confidence = freshness_confidence
    elite_main.ls_confidence = ls_confidence
    elite_main.pad_confidence = lambda row, min_pad_size: pad_confidence(elite_main, row, min_pad_size)
    elite_main.row_confidence = lambda row, filters, owned_permits=None: row_confidence(elite_main, row, filters, owned_permits)
    elite_main.confidence_label = confidence_label
    elite_main.estimate_minutes = estimate_minutes
    elite_main.player_distance_confidence = player_distance_confidence
    elite_main.relative_value_score = relative_value_score
    elite_main.app.state.elite55_trade_scoring_service_installed = True
