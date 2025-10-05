"""Lightweight TMDB API client for Scanly."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class TMDBResult:
    title: str
    year: Optional[int]


class TMDBClient:
    """Very small helper around TMDB's search endpoints."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._session = requests.Session()

    def _request(self, path: str, *, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"api_key": self.api_key, **params}
        response = self._session.get(f"{self.BASE_URL}{path}", params=payload, timeout=15)
        response.raise_for_status()
        return response.json()

    def search_movie(self, query: str, year: Optional[int]) -> Optional[TMDBResult]:
        params: Dict[str, Any] = {"query": query}
        if year:
            params["year"] = year
        try:
            data = self._request("/search/movie", params=params)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("TMDB movie search failed for %s: %s", query, exc)
            return None
        results = data.get("results", [])
        if not results:
            return None
        best = results[0]
        release_date = best.get("release_date")
        year_value = int(release_date[:4]) if release_date else year
        return TMDBResult(title=best.get("title") or query, year=year_value)

    def search_show(self, query: str, first_air_year: Optional[int]) -> Optional[TMDBResult]:
        params: Dict[str, Any] = {"query": query}
        if first_air_year:
            params["first_air_date_year"] = first_air_year
        try:
            data = self._request("/search/tv", params=params)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("TMDB TV search failed for %s: %s", query, exc)
            return None
        results = data.get("results", [])
        if not results:
            return None
        best = results[0]
        first_air_date = best.get("first_air_date")
        year_value = int(first_air_date[:4]) if first_air_date else first_air_year
        return TMDBResult(title=best.get("name") or query, year=year_value)


__all__ = ["TMDBClient", "TMDBResult"]
