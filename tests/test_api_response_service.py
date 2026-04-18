from __future__ import annotations

import unittest

from app.api_response_service import ok_dashboard, ok_health, ok_stats_dashboard, ok_status


class ApiResponseServiceTests(unittest.TestCase):
    def test_ok_dashboard(self) -> None:
        result = ok_dashboard({"routes": []})
        self.assertTrue(result["ok"])
        self.assertIn("dashboard", result)

    def test_ok_stats_dashboard(self) -> None:
        result = ok_stats_dashboard({"rows": 5}, {"routes": []})
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"]["rows"], 5)

    def test_ok_status(self) -> None:
        result = ok_status({"running": True})
        self.assertTrue(result["ok"])
        self.assertTrue(result["status"]["running"])

    def test_ok_health(self) -> None:
        result = ok_health(
            build_token="token",
            engine_status={"phase": "ready"},
            market_rows=42,
            name_library_total=12,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["market_rows"], 42)
        self.assertEqual(result["name_library_total"], 12)


if __name__ == "__main__":
    unittest.main()
