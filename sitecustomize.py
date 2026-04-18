from __future__ import annotations

try:
    import app.main as elite_main
    from app.commodity_intel_service import install_commodity_intel_service_patches
    from app.dashboard_service import install_dashboard_service_patches
    from app.live_snapshot_backend import install_live_snapshot_backend_patches
    from app.live_snapshot_service import install_live_snapshot_service_patches
    from app.mission_intel_service import install_mission_intel_service_patches
    from app.trade_ranking import install_backend_ranking_patches
except Exception:
    elite_main = None
else:
    install_backend_ranking_patches(elite_main)
    install_live_snapshot_backend_patches(elite_main)
    install_live_snapshot_service_patches(elite_main)
    install_commodity_intel_service_patches(elite_main)
    install_mission_intel_service_patches(elite_main)
    install_dashboard_service_patches(elite_main)
