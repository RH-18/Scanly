from __future__ import annotations

"""Similarity helpers used for TMDB results."""

import logging
import re
from typing import Dict, Optional

try:  # pragma: no cover - import guard
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - fallback for constrained environments
    from difflib import SequenceMatcher

    class _FallbackFuzz:
        @staticmethod
        def token_sort_ratio(lhs: str, rhs: str) -> float:
            lhs_tokens = " ".join(sorted(lhs.split()))
            rhs_tokens = " ".join(sorted(rhs.split()))
            return SequenceMatcher(None, lhs_tokens, rhs_tokens).ratio() * 100

    fuzz = _FallbackFuzz()

logger = logging.getLogger(__name__)

THRESHOLD_STRICT = 90
THRESHOLD_LOOSE = 80


def _extract_sxxexx(text: str) -> Optional[str]:
    match = re.search(r"(S\d{1,2}E\d{1,2}|\d{1,2}x\d{1,2})", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _normalize(text: str) -> str:
    text = re.sub(r"[._\-]+", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip().lower()


def similarity_score(
    query: str,
    candidate: str,
    *,
    year_match: bool = False,
    sxxexx_match: bool = False,
    folder_context_match: bool = False,
) -> float:
    base_score = fuzz.token_sort_ratio(_normalize(query), _normalize(candidate))
    bonus = 0
    if year_match:
        bonus += 10
    if sxxexx_match:
        bonus += 10
    if folder_context_match:
        bonus += 5
    final_score = min(100, base_score + bonus)
    logger.debug(
        "🔍 Similarity(%r ↔ %r) = %.1f + %d → %.1f",
        query,
        candidate,
        base_score,
        bonus,
        final_score,
    )
    return final_score


def evaluate_match(
    query: str,
    candidate: str,
    *,
    query_year: Optional[int] = None,
    candidate_year: Optional[int] = None,
    folder_hint: Optional[str] = None,
) -> Dict[str, str | float | bool]:
    sxx_q = _extract_sxxexx(query)
    sxx_c = _extract_sxxexx(candidate)
    sxx_match = bool(sxx_q and sxx_c and sxx_q == sxx_c)
    year_match = bool(query_year and candidate_year and query_year == candidate_year)
    folder_context_match = bool(folder_hint and folder_hint.lower() in candidate.lower())
    score = similarity_score(
        query,
        candidate,
        year_match=year_match,
        sxxexx_match=sxx_match,
        folder_context_match=folder_context_match,
    )
    verdict: Dict[str, str | float | bool] = {
        "score": score,
        "accepted": False,
        "warn": False,
        "reason": "",
    }
    if score >= THRESHOLD_STRICT:
        verdict.update(accepted=True, reason="strict_accept")
    elif score >= THRESHOLD_LOOSE and year_match:
        verdict.update(accepted=True, warn=True, reason="loose_accept_year_match")
    else:
        verdict.update(accepted=False, reason="unmatched")
    return verdict


__all__ = ["evaluate_match", "similarity_score"]
