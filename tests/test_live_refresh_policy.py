from __future__ import annotations

import unittest

from app.live_refresh_policy import (
    LiveRefreshState,
    active_text,
    build_status_message,
    has_active_commodity_query,
    has_active_mission_query,
)


class LiveRefreshPolicyTests(unittest.TestCase):
    def test_active_text_trims_values(self) -> None:
        self.assertEqual(active_text("  Gold  "), "Gold")
        self.assertEqual(active_text(None), "")

    def test_state_reuses_recent_snapshot(self) -> None:
        state = LiveRefreshState(last_snapshot_started_at=10.0, promise_active=True)
        self.assertTrue(state.can_reuse_existing_snapshot(12.0, max_age_seconds=15.0))
        self.assertFalse(state.can_reuse_existing_snapshot(30.5, max_age_seconds=15.0))

    def test_state_pause_light_refreshes_when_busy(self) -> None:
        state = LiveRefreshState(promise_active=False, snapshot_in_flight=False)
        self.assertFalse(state.should_pause_light_refreshes())
        state.snapshot_in_flight = True
        self.assertTrue(state.should_pause_light_refreshes())
        state.snapshot_in_flight = False
        state.promise_active = True
        self.assertTrue(state.should_pause_light_refreshes())

    def test_mark_snapshot_lifecycle(self) -> None:
        state = LiveRefreshState()
        state.mark_snapshot_started(now=42.0)
        self.assertEqual(state.last_snapshot_started_at, 42.0)
        self.assertTrue(state.promise_active)
        self.assertTrue(state.snapshot_in_flight)

        state.mark_snapshot_finished()
        self.assertFalse(state.snapshot_in_flight)
        self.assertTrue(state.promise_active)

        state.mark_promise_released()
        self.assertFalse(state.promise_active)

    def test_query_helpers_detect_context(self) -> None:
        self.assertTrue(has_active_commodity_query("Silver"))
        self.assertFalse(has_active_commodity_query("   "))
        self.assertTrue(has_active_mission_query("", "Tritium"))
        self.assertTrue(has_active_mission_query("Gold", ""))
        self.assertFalse(has_active_mission_query("  ", None))

    def test_build_status_message_uses_subject_when_available(self) -> None:
        self.assertEqual(
            build_status_message("Analyse", "Argent", "Analyse prête."),
            "Analyse Argent.",
        )
        self.assertEqual(
            build_status_message("Analyse", "", "Analyse prête."),
            "Analyse prête.",
        )


if __name__ == "__main__":
    unittest.main()
