from __future__ import annotations

import types
import unittest

from app.permit_access_service import (
    install_permit_access_service_patches,
    known_owned_permit_labels,
    known_owned_permits,
    station_accessibility_label,
    station_accessible,
)


class _FakeRepo:
    def __init__(self) -> None:
        self.state = {"owned_permits": ["sol", "achenar"]}

    def get_state(self, key, default=None):
        return self.state.get(key, default)


class PermitAccessServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.repo = _FakeRepo()
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_known_owned_permits_reads_repo_values(self) -> None:
        elite = self._elite()
        result = known_owned_permits(elite)
        self.assertEqual(result, {"sol", "achenar"})

    def test_known_owned_permit_labels_returns_labels(self) -> None:
        elite = self._elite()
        result = known_owned_permit_labels(elite)
        self.assertIn("Sol", result)

    def test_station_accessible_without_permit_requirement(self) -> None:
        elite = self._elite()
        row = {"requires_permit": 0, "permit_name": None}
        self.assertTrue(station_accessible(elite, row))

    def test_station_accessible_with_matching_permit(self) -> None:
        elite = self._elite()
        row = {"requires_permit": 1, "permit_name": "sol"}
        self.assertTrue(station_accessible(elite, row))

    def test_station_accessibility_label_returns_restricted_message(self) -> None:
        elite = self._elite()
        row = {"requires_permit": 1, "permit_name": "alioth"}
        result = station_accessibility_label(elite, row)
        self.assertIn("Permit requis", result)

    def test_install_permit_access_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_permit_access_service_patches(elite)
        self.assertEqual(elite.known_owned_permits(), {"sol", "achenar"})
        self.assertTrue(elite.station_accessible({"requires_permit": 0, "permit_name": None}))


if __name__ == "__main__":
    unittest.main()
