from __future__ import annotations

import tempfile
import time
import types
import unittest
from pathlib import Path

from app.journal_catalog_service import (
    better_price_candidate,
    decode_status_flags,
    derive_module_name_fr,
    format_ship_name,
    infer_pad_size,
    install_journal_catalog_service_patches,
    is_fleet_carrier,
    is_odyssey_station,
    is_planetary,
    localised,
    market_file_is_fresh,
    source_priority,
)


class JournalCatalogServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.STATUS_FLAG_BITS = {"docked": 1 << 0}
        elite.STATUS_FLAG2_BITS = {"on_foot": 1 << 0}
        elite.LOCAL_MARKET_MAX_AGE_MINUTES = 20
        elite.NAME_SOURCE_PRIORITY = {"frontier_market": 100, "catalogue_derive": 72}
        elite.SHIP_CODE_FALLBACKS = {"python": "Python"}
        elite.ARMOUR_VARIANT_FR = {"grade1": "Blindage léger"}
        elite.MODULE_FAMILY_FR_OVERRIDES = {"int_hyperdrive": "FSD"}
        elite.normalize_ship_code = lambda value: str(value or "").strip().lower()
        elite.normalize_module_key = lambda value: str(value or "").strip().lower()
        elite.module_family_key = lambda value: str(value or "").strip().lower().replace("_grade1", "")
        elite.parse_dt = lambda value: __import__("datetime").datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
        elite.age_minutes = lambda value: 5.0 if value else None
        elite.time = time
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_basic_helpers_return_expected_values(self) -> None:
        elite = self._elite()
        flags = decode_status_flags(elite, 1, 1)
        self.assertTrue(flags["docked"])
        self.assertTrue(flags["on_foot"])
        self.assertEqual(source_priority(elite, "frontier_market"), 100)
        self.assertEqual(format_ship_name(elite, "python"), "Python")
        self.assertEqual(derive_module_name_fr(elite, "int_hyperdrive_grade1", {}), "FSD")
        self.assertEqual(infer_pad_size("Starport"), "L")
        self.assertTrue(is_planetary("Planetary Port"))
        self.assertTrue(is_odyssey_station("Settlement"))
        self.assertTrue(is_fleet_carrier("Fleet Carrier"))
        self.assertEqual(localised({"Ship_Localised": "Python"}, "Ship"), "Python")

    def test_market_file_is_fresh_and_price_candidate_work(self) -> None:
        elite = self._elite()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Market.json"
            path.write_text("{}", encoding="utf-8")
            self.assertTrue(market_file_is_fresh(elite, path, "2026-01-01T00:00:00Z"))
        newer = {"updated_at": "2026-01-02T00:00:00Z", "buy_price": 100, "sell_price": 0, "demand": 0, "stock": 10, "source": "frontier_market"}
        older = {"updated_at": "2026-01-01T00:00:00Z", "buy_price": 100, "sell_price": 0, "demand": 0, "stock": 10, "source": "catalogue_derive"}
        self.assertTrue(better_price_candidate(elite, newer, older))

    def test_install_journal_catalog_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_journal_catalog_service_patches(elite)
        self.assertEqual(elite.format_ship_name("python"), "Python")
        self.assertTrue(elite.is_planetary("Surface Port"))


if __name__ == "__main__":
    unittest.main()
