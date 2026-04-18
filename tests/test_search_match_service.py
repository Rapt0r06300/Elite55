from __future__ import annotations

import types
import unittest

from app.search_match_service import best_variant_score, install_search_match_service_patches, subsequence_bonus, text_match_score


class SearchMatchServiceTests(unittest.TestCase):
    def _elite(self):
        elite = types.SimpleNamespace()
        elite.normalize_search_text = lambda value: str(value or "").strip().lower()
        elite.compact_search_key = lambda value: str(value or "").strip().lower().replace(" ", "")
        elite.search_words = lambda value: [part for part in str(value or "").strip().lower().split(" ") if part]
        elite.app = types.SimpleNamespace(state=types.SimpleNamespace())
        return elite

    def test_subsequence_bonus_returns_positive_for_close_match(self) -> None:
        self.assertGreater(subsequence_bonus("gld", "gold"), 0)

    def test_text_match_score_detects_exact_and_contains(self) -> None:
        elite = self._elite()
        exact_score, exact_label = text_match_score(elite, "gold", "gold")
        contains_score, contains_label = text_match_score(elite, "gold", "raw gold")
        self.assertGreater(exact_score, contains_score)
        self.assertEqual(exact_label, "Exact")
        self.assertEqual(contains_label, "Contient")

    def test_best_variant_score_picks_best_candidate(self) -> None:
        elite = self._elite()
        score, label, variant = best_variant_score(elite, "python", "vulture", "python mk ii", "cobra")
        self.assertGreater(score, 0)
        self.assertEqual(variant, "python mk ii")
        self.assertTrue(label)

    def test_install_search_match_service_patches_exposes_helpers(self) -> None:
        elite = self._elite()
        install_search_match_service_patches(elite)
        score, label = elite.text_match_score("gold", "gold")
        self.assertGreater(score, 0)
        self.assertEqual(label, "Exact")


if __name__ == "__main__":
    unittest.main()
