from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path

from app.nav_combat_service import build_combat_support_payload, build_nav_route_payload, install_nav_combat_service_patches


class _FakeRepo:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.state = {"current_system": "Sol", "preferred_pad_size": "M"}

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def system_position(self, system_name):
        if system_name == "Sol":
            return {"x": 0, "y": 0, "z": 0}
        if system_name == "Achenar":
            return {"x": 10, "y": 0, "z": 0}
        return None

    def connect(self):
        rows = self.rows

        class _Conn:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                return False

            def execute(self_inner, sql):
                return types.SimpleNamespace(fetchall=lambda: rows)

        return _Conn()


class NavCombatServiceTests(unittest.TestCase):
    def _elite_for_nav(self, journal_dir: Path):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.JOURNAL_DIR = journal_dir
        elite.age_minutes = lambda value: 5.0 if value else None
        elite.euclidean_distance = lambda a, b: round((((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2) ** 0.5), 2)
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def _elite_for_combat(self, rows):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo(rows)
        elite.PAD_RANK = {"?": 0, "S": 1, "M": 2, "L": 3}
        elite.normalize_search_text = lambda value: str(value or "").strip().lower()
        elite.known_owned_permits = lambda: set()
        elite.station_accessible = lambda row, permits=None: True
        elite.station_accessibility_label = lambda row, permits=None: "Acces direct"
        elite.euclidean_distance = lambda row, pos: 0.0 if row.get("system_name") == "Sol" else 12.0
        elite.age_hours = lambda value: 1.0 if value else None
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_build_nav_route_payload_reads_route_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal_dir = Path(tmp)
            (journal_dir / "NavRoute.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-01-01T00:00:00Z",
                        "Route": [
                            {"StarSystem": "Sol", "StarClass": "G", "StarPos": [0, 0, 0]},
                            {"StarSystem": "Achenar", "StarClass": "B", "StarPos": [10, 0, 0]},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            elite = self._elite_for_nav(journal_dir)
            result = build_nav_route_payload(elite)
            self.assertTrue(result["available"])
            self.assertEqual(result["destination_system"], "Achenar")
            self.assertEqual(result["direct_distance_ly"], 10.0)

    def test_build_combat_support_payload_returns_best_station(self) -> None:
        rows = [
            {
                "market_id": 1,
                "system_name": "Sol",
                "station_name": "Galileo",
                "station_type": "Starport",
                "distance_to_arrival": 500,
                "landing_pad": "M",
                "has_market": 1,
                "is_planetary": 0,
                "is_odyssey": 0,
                "is_fleet_carrier": 0,
                "services_json": json.dumps(["restock", "repair", "refuel"]),
                "updated_at": "2026-01-01T00:00:00Z",
                "x": 0,
                "y": 0,
                "z": 0,
                "requires_permit": 0,
                "permit_name": None,
            },
            {
                "market_id": 2,
                "system_name": "Achenar",
                "station_name": "Dawes Hub",
                "station_type": "Starport",
                "distance_to_arrival": 800,
                "landing_pad": "L",
                "has_market": 1,
                "is_planetary": 0,
                "is_odyssey": 0,
                "is_fleet_carrier": 0,
                "services_json": json.dumps(["repair"]),
                "updated_at": "2026-01-01T00:00:00Z",
                "x": 10,
                "y": 0,
                "z": 0,
                "requires_permit": 0,
                "permit_name": None,
            },
        ]
        elite = self._elite_for_combat(rows)
        result = build_combat_support_payload(elite)
        self.assertEqual(result["best_restock"]["station_name"], "Galileo")
        self.assertEqual(result["best_repair"]["station_name"], "Galileo")
        self.assertTrue(result["stations"])

    def test_install_nav_combat_service_patches_exposes_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal_dir = Path(tmp)
            elite = self._elite_for_nav(journal_dir)
            elite.combat_support_payload = lambda limit=10: {"stations": []}
            install_nav_combat_service_patches(elite)
            self.assertIn("available", elite.nav_route_payload())


if __name__ == "__main__":
    unittest.main()
