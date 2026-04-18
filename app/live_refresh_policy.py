from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable


@dataclass(slots=True)
class LiveRefreshState:
    last_snapshot_started_at: float = 0.0
    cooldown_seconds: float = 0.18
    promise_active: bool = False
    snapshot_in_flight: bool = False

    def can_reuse_existing_snapshot(self, now: float, max_age_seconds: float = 15.0) -> bool:
        return self.promise_active and (now - self.last_snapshot_started_at) < max_age_seconds

    def should_pause_light_refreshes(self) -> bool:
        return self.snapshot_in_flight or self.promise_active

    def mark_snapshot_started(self, now: float | None = None) -> None:
        self.last_snapshot_started_at = monotonic() if now is None else now
        self.promise_active = True
        self.snapshot_in_flight = True

    def mark_snapshot_finished(self) -> None:
        self.snapshot_in_flight = False

    def mark_promise_released(self) -> None:
        self.promise_active = False


def active_text(value: str | None) -> str:
    return str(value or "").strip()


def has_active_commodity_query(value: str | None) -> bool:
    return bool(active_text(value))


def has_active_mission_query(commodity_query: str | None, mission_query: str | None) -> bool:
    return bool(active_text(commodity_query) or active_text(mission_query))


def build_status_message(prefix: str, subject: str | None, fallback: str) -> str:
    text = active_text(subject)
    return f"{prefix} {text}." if text else fallback


def with_snapshot_guard(state: LiveRefreshState, callback: Callable[[], object]) -> object | None:
    if state.should_pause_light_refreshes():
        return None
    return callback()
