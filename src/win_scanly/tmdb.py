from __future__ import annotations

"""Minimal TMDB client used by the Windows pipeline."""

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import requests

from .similarity import evaluate_match

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
HEADERS = {"Accept": "application/json"}


@dataclass
class TMDBResult:
    id: int
    title: str
    year: Optional[int]
    media_type: str
    overview: Optional[str]
    similarity_score: Optional[float] = None
    release_date: Optional[str] = None
    extra: Dict[str, Any] | None = None


class TMDBClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or TMDB_API_KEY
        if not self.api_key:
            logger.warning("⚠️ TMDB API key missing — searches will fail.")

    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch data from TMDB with simple memoisation.

        ``functools.lru_cache`` requires hashable arguments, but ``dict``
        instances are not hashable.  The Windows scanner previously attempted to
        decorate this method directly which resulted in ``TypeError: unhashable
        type: 'dict'`` when processing files.  To retain caching we normalise
        the parameters into a tuple before delegating to the cached helper.
        """

        params = dict(params)
        params["api_key"] = self.api_key
        cache_key: Tuple[str, Tuple[Tuple[str, Any], ...]] = (
            endpoint,
            tuple(sorted(params.items())),
        )
        return self._cached_get(cache_key)

    @lru_cache(maxsize=256)
    def _cached_get(
        self, cache_key: Tuple[str, Tuple[Tuple[str, Any], ...]]
    ) -> Dict[str, Any]:
        endpoint, params_items = cache_key
        params = dict(params_items)
        try:
            response = requests.get(
                f"{TMDB_BASE_URL}/{endpoint}",
                params=params,
                headers=HEADERS,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("TMDB request failed: %s", exc)
            return {}

    def search_movie(self, query: str, year_hint: Optional[int] = None) -> Optional[TMDBResult]:
        params = {
            "query": query,
            "include_adult": False,
            "language": "en-US",
            "page": 1,
        }
        if year_hint:
            params["year"] = year_hint
        data = self._get("search/movie", params)
        results = data.get("results") or []
        return self._rank_candidates(query, results, "movie")

    def search_show(self, query: str, year_hint: Optional[int] = None) -> Optional[TMDBResult]:
        params = {
            "query": query,
            "include_adult": False,
            "language": "en-US",
            "page": 1,
        }
        if year_hint:
            params["first_air_date_year"] = year_hint
        data = self._get("search/tv", params)
        results = data.get("results") or []
        return self._rank_candidates(query, results, "tv")

    def _rank_candidates(
        self, query: str, results: List[Dict[str, Any]], media_type: str
    ) -> Optional[TMDBResult]:
        if not results:
            return None
        ranked: List[Dict[str, Any]] = []
        for result in results:
            title = self._safe_str(result.get("title") or result.get("name") or "")
            year = self._extract_year(
                result.get("release_date") or result.get("first_air_date")
            )
            similarity = evaluate_match(
                self._safe_str(query),
                title,
                query_year=year,
                candidate_year=year,
            )
            ranked.append(
                {
                    "id": result.get("id"),
                    "title": title,
                    "year": year,
                    "media_type": media_type,
                    "overview": result.get("overview"),
                    "similarity_score": similarity["score"],
                    "release_date": result.get("release_date")
                    or result.get("first_air_date"),
                    "extra": {"popularity": result.get("popularity", 0)},
                }
            )
        ranked.sort(key=lambda item: (item["similarity_score"], item["extra"]["popularity"]), reverse=True)
        top = ranked[0]
        logger.debug(
            "TMDB best %s match for '%s' → %s (%s) [score=%.1f]",
            media_type.upper(),
            query,
            top["title"],
            top.get("year"),
            top["similarity_score"],
        )
        return TMDBResult(**top)

    def search_candidates(self, query: str, year_hint: Optional[int] = None) -> List[TMDBResult]:
        movie_data = self._get("search/movie", {"query": query, "include_adult": False})
        tv_data = self._get("search/tv", {"query": query, "include_adult": False})
        combined: List[TMDBResult] = []
        for media_type, dataset in (("movie", movie_data), ("tv", tv_data)):
            for result in dataset.get("results", []):
                title = self._safe_str(result.get("title") or result.get("name") or "")
                year = self._extract_year(
                    result.get("release_date") or result.get("first_air_date")
                )
                similarity = evaluate_match(
                    self._safe_str(query),
                    title,
                    query_year=year_hint,
                    candidate_year=year,
                )
                combined.append(
                    TMDBResult(
                        id=result.get("id"),
                        title=title,
                        year=year,
                        media_type=media_type,
                        overview=result.get("overview"),
                        similarity_score=similarity["score"],
                        release_date=result.get("release_date")
                        or result.get("first_air_date"),
                        extra={"popularity": result.get("popularity", 0)},
                    )
                )
        combined.sort(
            key=lambda candidate: (
                candidate.similarity_score or 0,
                candidate.extra.get("popularity", 0) if candidate.extra else 0,
            ),
            reverse=True,
        )
        return combined[:10]

    @staticmethod
    def _safe_str(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value) if value is not None else ""

    @staticmethod
    def _extract_year(date_str: Optional[str]) -> Optional[int]:
        if not date_str:
            return None
        try:
            return int(date_str.split("-")[0])
        except Exception:
            return None


__all__ = ["TMDBClient", "TMDBResult"]
