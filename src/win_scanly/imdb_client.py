from __future__ import annotations

"""Local IMDb cache client for offline-first lookups."""

import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency
    import numpy as _np
except ImportError:  # pragma: no cover - degrade gracefully
    _np = None

if _np is not None:  # pragma: no cover - typing helper
    NDArray = _np.ndarray
else:  # pragma: no cover - typing helper
    NDArray = Any  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - degrade gracefully
    SentenceTransformer = None  # type: ignore[assignment]

from .similarity import evaluate_match

logger = logging.getLogger(__name__)

_SHOW_TYPES = (
    "tvSeries",
    "tvMiniSeries",
    "tvEpisode",
    "tvShort",
    "tvMovie",
)
_MOVIE_TYPES = ("movie", "short", "video", "tvMovie")


@dataclass
class IMDbResult:
    id: str
    title: str
    year: Optional[int]
    media_type: str
    score: float


class IMDbClient:
    """Wrapper around the cached IMDb SQLite database."""

    def __init__(
        self,
        db_path: Path,
        *,
        embedding_enabled: bool = True,
        embedding_model: Optional[str] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.embedding_enabled = embedding_enabled
        self._connection_kwargs: Dict[str, object] = {"timeout": 1.0}
        self._embedder = None
        self._embedding_cache: Dict[str, NDArray] = {}
        if not self.db_path.exists():
            logger.warning("⚠️ IMDb database not found at %s", self.db_path)
        if self.embedding_enabled and SentenceTransformer and _np is not None:
            model_name = embedding_model or os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            try:
                self._embedder = SentenceTransformer(model_name)
                logger.debug("🧠 Loaded embedding model %s for IMDb scoring", model_name)
            except Exception as exc:  # pragma: no cover - model load failure
                logger.warning("⚠️ Failed to load embedding model '%s': %s", model_name, exc)
                self.embedding_enabled = False
        else:
            self.embedding_enabled = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, **self._connection_kwargs)
        conn.row_factory = sqlite3.Row
        return conn

    def search_title(self, clean_title: str, year: Optional[int] = None) -> Optional[IMDbResult]:
        """Search for a title regardless of media type."""

        if not clean_title:
            return None
        logger.info("🔍 IMDb lookup for \"%s\"", clean_title)
        candidates = self.search_candidates(clean_title, year=year)
        best = candidates[0] if candidates else None
        if best:
            logger.info("✅ IMDb match: %s (%s) [%s]", best.title, best.year or "n/a", best.id)
        return best

    def search_show(self, clean_title: str, season: Optional[int] = None) -> Optional[IMDbResult]:
        """Search for a TV/anime title."""

        if not clean_title:
            return None
        candidates = self.search_candidates(clean_title, media_filter=_SHOW_TYPES)
        if season and candidates:
            # Slightly boost candidates with matching season metadata if available.
            for candidate in candidates:
                if candidate.media_type == "show":
                    candidate.score += 1
        return candidates[0] if candidates else None

    def search_candidates(
        self,
        clean_title: str,
        *,
        year: Optional[int] = None,
        media_filter: Optional[Sequence[str]] = None,
        limit: int = 40,
    ) -> List[IMDbResult]:
        """Return ranked candidates for the given clean title."""

        if not clean_title:
            return []

        query = [
            "SELECT tconst, primaryTitle, originalTitle, startYear, titleType",
            "FROM titles",
            "WHERE (primaryTitle LIKE ? OR originalTitle LIKE ?)",
        ]
        params: List[object] = [f"%{clean_title}%", f"%{clean_title}%"]
        if media_filter:
            placeholders = ",".join(["?"] * len(media_filter))
            query.append(f"AND titleType IN ({placeholders})")
            params.extend(media_filter)
        query.append("AND (isAdult IS NULL OR isAdult = 0)")
        if year:
            query.append("ORDER BY ABS(CAST(startYear AS INTEGER) - ?) ASC")
            params.append(year)
        else:
            query.append("ORDER BY startYear DESC")
        query.append("LIMIT ?")
        params.append(limit)
        sql = " ".join(query)

        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            logger.error("⚠️ IMDb query failed for '%s': %s", clean_title, exc)
            return []

        candidates: List[IMDbResult] = []
        for row in rows:
            primary = row["primaryTitle"] or ""
            original = row["originalTitle"] or ""
            start_year = self._coerce_year(row["startYear"])
            title, score = self._score_best_title(
                clean_title,
                (primary, original),
                year,
                start_year,
            )
            if not title:
                continue
            media_type = self._map_media_type(row["titleType"])
            candidates.append(
                IMDbResult(
                    id=row["tconst"],
                    title=title,
                    year=start_year,
                    media_type=media_type,
                    score=score,
                )
            )

        candidates.sort(key=lambda result: result.score, reverse=True)
        return candidates

    @staticmethod
    def _map_media_type(title_type: Optional[str]) -> str:
        if not title_type:
            return "movie"
        if title_type in _SHOW_TYPES:
            return "show"
        if title_type in _MOVIE_TYPES:
            return "movie"
        return "movie"

    @staticmethod
    def _coerce_year(value: Optional[str]) -> Optional[int]:
        if value in (None, "\\N"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _score_best_title(
        self,
        clean_title: str,
        candidates: Iterable[str],
        query_year: Optional[int],
        candidate_year: Optional[int],
    ) -> Tuple[str, float]:
        best_title = ""
        best_score = 0.0
        for candidate in candidates:
            candidate = (candidate or "").strip()
            if not candidate:
                continue
            similarity = evaluate_match(
                clean_title,
                candidate,
                query_year=query_year,
                candidate_year=candidate_year or self._extract_year(candidate),
            )
            score = similarity["score"]
            if self.embedding_enabled and self._embedder and _np is not None:
                emb_score = self._embedding_similarity(clean_title, candidate)
                if emb_score:
                    score = max(score, emb_score * 100)
            if score > best_score:
                best_title = candidate
                best_score = score
        return best_title, best_score

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        match_year = re.search(r"\b(19|20)\d{2}\b", text)
        if match_year:
            return int(match_year.group(0))
        return None

    def _embedding_similarity(self, query: str, candidate: str) -> float:
        if not self._embedder or _np is None:
            return 0.0
        query_vec = self._get_vector(query)
        candidate_vec = self._get_vector(candidate)
        if query_vec is None or candidate_vec is None:
            return 0.0
        denom = float(_np.linalg.norm(query_vec) * _np.linalg.norm(candidate_vec))
        if denom == 0:
            return 0.0
        return float(_np.dot(query_vec, candidate_vec) / denom)

    def _get_vector(self, text: str) -> Optional[_np.ndarray]:
        if not self._embedder or _np is None:
            return None
        text = text.strip()
        if not text:
            return None
        cached = self._embedding_cache.get(text)
        if cached is not None:
            return cached
        try:
            vector = self._embedder.encode(text)
            if isinstance(vector, list):  # sentence-transformers may return list
                vector = _np.array(vector)
            self._embedding_cache[text] = vector
            return vector
        except Exception as exc:  # pragma: no cover - embedding failure
            logger.debug("⚠️ Embedding failed for '%s': %s", text, exc)
            return None


__all__ = ["IMDbClient", "IMDbResult"]
