from __future__ import annotations

try:
    import app.main as elite_main
    from app.trade_ranking import install_backend_ranking_patches
except Exception:
    elite_main = None
else:
    install_backend_ranking_patches(elite_main)
