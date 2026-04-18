from __future__ import annotations

import importlib
import sys
import traceback
from typing import Any, Callable


def _log_bootstrap_error(step: str, error: BaseException) -> None:
    print(
        f"[Elite55 bootstrap] Echec pendant l'étape '{step}': {error}",
        file=sys.stderr,
    )
    traceback.print_exc()


def _install_step(step: str, installer_path: str, elite_main: Any) -> None:
    try:
        module_name, function_name = installer_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        installer: Callable[[Any], None] = getattr(module, function_name)
        installer(elite_main)
        print(f"[Elite55 bootstrap] OK: {step}", file=sys.stderr)
    except Exception as error:
        _log_bootstrap_error(step, error)


try:
    import app.main as elite_main
except Exception as error:
    elite_main = None
    _log_bootstrap_error("import app.main", error)
else:
    _install_step("helpers coeur", "app.core_runtime_service.install_core_runtime_service_patches", elite_main)
    _install_step("correspondance texte", "app.search_match_service.install_search_match_service_patches", elite_main)
    _install_step("moteur suggestions", "app.suggestion_engine_service.install_suggestion_engine_service_patches", elite_main)
    _install_step("config trader", "app.trade_config_service.install_trade_config_service_patches", elite_main)
    _install_step("moteur de routes", "app.route_engine.install_route_engine_patches", elite_main)
    _install_step("memoire trader", "app.trader_memory_service.install_trader_memory_service_patches", elite_main)
    _install_step("permis et acces", "app.permit_access_service.install_permit_access_service_patches", elite_main)
    _install_step("navigation et combat", "app.nav_combat_service.install_nav_combat_service_patches", elite_main)
    _install_step("service etat", "app.engine_state_service.install_engine_state_service_patches", elite_main)
    _install_step("lignes trader", "app.trade_rows_service.install_trade_rows_service_patches", elite_main)
    _install_step("flux trader", "app.trade_flow_service.install_trade_flow_service_patches", elite_main)
    _install_step("scoring trader", "app.trade_scoring_service.install_trade_scoring_service_patches", elite_main)
    _install_step("recommandations trader", "app.trade_recommendation_service.install_trade_recommendation_service_patches", elite_main)
    _install_step("classement backend", "app.trade_ranking.install_backend_ranking_patches", elite_main)
    _install_step("cache live", "app.live_snapshot_backend.install_live_snapshot_backend_patches", elite_main)
    _install_step("service live", "app.live_snapshot_service.install_live_snapshot_service_patches", elite_main)
    _install_step("analyse marchandise", "app.commodity_intel_service.install_commodity_intel_service_patches", elite_main)
    _install_step("analyse mission", "app.mission_intel_service.install_mission_intel_service_patches", elite_main)
    _install_step("tableau de bord commerce", "app.dashboard_service.install_dashboard_service_patches", elite_main)
    _install_step("contexte dashboard", "app.pulse_context_service.install_pulse_context_service_patches", elite_main)
    _install_step("forme des réponses", "app.payload_shape_service.install_payload_shape_service_patches", elite_main)
    _install_step("API dashboard", "app.dashboard_api_service.install_dashboard_api_service_patches", elite_main)
    _install_step("API trader", "app.trader_api_service.install_trader_api_service_patches", elite_main)
    _install_step("API sources", "app.source_api_service.install_source_api_service_patches", elite_main)
    _install_step("API recherche", "app.lookup_api_service.install_lookup_api_service_patches", elite_main)
    _install_step("API runtime", "app.runtime_api_service.install_runtime_api_service_patches", elite_main)
