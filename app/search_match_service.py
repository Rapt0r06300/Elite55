from __future__ import annotations

from typing import Any


def subsequence_bonus(query: str, candidate: str) -> int:
    if not query or not candidate:
        return 0
    cursor = 0
    gaps = 0
    for char in query:
        index = candidate.find(char, cursor)
        if index < 0:
            return 0
        gaps += max(0, index - cursor)
        cursor = index + 1
    return max(0, 26 - gaps - max(0, len(candidate) - len(query)))


def text_match_score(elite_main: Any, query: str, candidate: Any) -> tuple[int, str]:
    query_text = elite_main.normalize_search_text(query)
    candidate_text = elite_main.normalize_search_text(candidate)
    if not query_text or not candidate_text:
        return 0, ""
    query_compact = elite_main.compact_search_key(query_text)
    candidate_compact = elite_main.compact_search_key(candidate_text)
    query_words = elite_main.search_words(query_text)
    candidate_words = elite_main.search_words(candidate_text)
    if query_text == candidate_text or query_compact == candidate_compact:
        return 166, "Exact"
    if candidate_text.startswith(query_text) or candidate_compact.startswith(query_compact):
        return 132 + min(24, len(query_compact) * 6), "Préfixe"
    if query_words and any(word.startswith(query_words[0]) for word in candidate_words):
        return 118 + min(18, len(query_compact) * 4), "Mot-clé"
    if query_text in candidate_text or query_compact in candidate_compact:
        return 98 + min(14, len(query_compact) * 3), "Contient"
    fuzzy = subsequence_bonus(query_compact, candidate_compact)
    if fuzzy > 0:
        return 72 + fuzzy, "Fuzzy"
    return 0, ""


def best_variant_score(elite_main: Any, query: str, *variants: Any) -> tuple[int, str, str]:
    best_score = 0
    best_label = ""
    best_variant = ""
    for variant in variants:
        if not variant:
            continue
        score, label = text_match_score(elite_main, query, variant)
        if score > best_score:
            best_score = score
            best_label = label
            best_variant = str(variant)
    return best_score, best_label, best_variant


def install_search_match_service_patches(elite_main: Any) -> None:
    if getattr(elite_main.app.state, "elite55_search_match_service_installed", False):
        return

    elite_main.subsequence_bonus = subsequence_bonus
    elite_main.text_match_score = lambda query, candidate: text_match_score(elite_main, query, candidate)
    elite_main.best_variant_score = lambda query, *variants: best_variant_score(elite_main, query, *variants)
    elite_main.app.state.elite55_search_match_service_installed = True
