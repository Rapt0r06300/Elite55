from __future__ import annotations

from typing import Any


def sources_payload(elite_main: Any) -> dict[str, Any]:
    repo = elite_main.repo
    return {
        "journal_last_import": repo.get_state("source_journal_last_import"),
        "ardent_last_sync": repo.get_state("source_ardent_last_sync"),
        "spansh_last_refresh": repo.get_state("source_spansh_last_refresh"),
        "edsm_last_refresh": repo.get_state("source_edsm_last_refresh"),
        "eddn_last_refresh": repo.get_state("source_eddn_last_refresh"),
        "edsm_access_last_refresh": repo.get_state("source_edsm_access_last_refresh"),
        "local_last_poll": repo.get_state("source_local_last_poll"),
        "local_last_event": repo.get_state("source_local_last_event"),
    }


def build_engine_status_from_values(
    elite_main: Any,
    rows: int,
    name_summary: dict[str, Any],
    local_status: dict[str, Any],
    current_market: dict[str, Any],
    current_system: str | None,
) -> dict[str, Any]:
    if rows < 500:
        phase = "bootstrapping"
        message = "Base locale en constitution"
    elif not local_status.get("running"):
        phase = "degraded"
        message = "Surveillance locale inactive"
    elif not current_system:
        phase = "waiting_position"
        message = "Position locale encore inconnue"
    elif not current_market.get("station_name"):
        phase = "waiting_market"
        message = "Marché courant en attente"
    else:
        phase = "ready"
        message = "Moteur trader prêt"
    return {
        "phase": phase,
        "ready": phase == "ready",
        "message": message,
        "market_rows": rows,
        "name_library_total": name_summary.get("total", 0),
        "current_system": current_system,
        "current_market": current_market.get("station_name"),
        "local_sync": local_status,
        "remote_seed_running": bool((getattr(elite_main, "background_flags", {}) or {}).get("remote_seed_running")),
    }


def build_engine_status(elite_main: Any) -> dict[str, Any]:
    rows = elite_main.repo.commodity_price_count()
    name_summary = elite_main.repo.name_library_summary()
    local_status = elite_main.local_sync_service.status() if hasattr(elite_main, "local_sync_service") else {"running": False}
    current_market = elite_main.repo.current_market()
    current_system = elite_main.repo.get_state("current_system")
    return build_engine_status_from_values(elite_main, rows, name_summary, local_status, current_market, current_system)


def install_engine_state_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_engine_state_service_installed", False):
        return

    elite_main.sources_payload = lambda: sources_payload(elite_main)
    elite_main.build_engine_status_from_values = lambda rows, name_summary, local_status, current_market, current_system: build_engine_status_from_values(
        elite_main,
        rows,
        name_summary,
        local_status,
        current_market,
        current_system,
    )
    elite_main.build_engine_status = lambda: build_engine_status(elite_main)
    elite_main.app.state.elite55_engine_state_service_installed = True
