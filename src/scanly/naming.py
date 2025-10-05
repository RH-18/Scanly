"""Name analysis and destination planning for Scanly."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Config
from .tmdb import TMDBClient, TMDBResult

logger = logging.getLogger(__name__)

EPISODE_PATTERN = re.compile(r"(?P<season>\d{1,2})x(?P<episode>\d{2})", re.IGNORECASE)
SXXE_PATTERN = re.compile(r"s(?P<season>\d{1,2})e(?P<episode>\d{2})", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(19\d{2}|20\d{2}|21\d{2})")
INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def _safe_component(text: str) -> str:
    cleaned = INVALID_CHARS.sub("", text)
    return cleaned.rstrip(" .")


@dataclass
class MediaCandidate:
    media_type: str  # "movie" or "show"
    query: str
    year_hint: Optional[int]
    season: Optional[int] = None
    episode: Optional[int] = None


@dataclass
class DestinationPlan:
    source: Path
    destination: Path
    title: str
    year: Optional[int]
    media_type: str
    season: Optional[int] = None
    episode: Optional[int] = None


def _extract_year(text: str) -> Optional[int]:
    match = YEAR_PATTERN.search(text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _clean_title(stem: str, config: Config) -> str:
    cleaned = config.apply_replacements(stem)
    cleaned = config.strip_release_tags(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def analyse_filename(path: Path, config: Config) -> Optional[MediaCandidate]:
    stem = path.stem
    normalized = re.sub(r"[._-]+", " ", stem)
    year_hint = _extract_year(normalized)

    sxxe_match = SXXE_PATTERN.search(normalized)
    episode_match = sxxe_match or EPISODE_PATTERN.search(normalized)

    if episode_match:
        season = int(episode_match.group("season"))
        episode = int(episode_match.group("episode"))
        title_part = normalized[: episode_match.start()].strip()
        cleaned_title = _clean_title(title_part or normalized, config)
        if not cleaned_title:
            cleaned_title = title_part or normalized
        return MediaCandidate(
            media_type="show",
            query=cleaned_title,
            year_hint=year_hint,
            season=season,
            episode=episode,
        )

    cleaned_title = _clean_title(normalized, config)
    if not cleaned_title:
        return None
    return MediaCandidate(media_type="movie", query=cleaned_title, year_hint=year_hint)


def resolve_metadata(candidate: MediaCandidate, tmdb: TMDBClient) -> TMDBResult:
    if candidate.media_type == "show":
        result = tmdb.search_show(candidate.query, candidate.year_hint)
    else:
        result = tmdb.search_movie(candidate.query, candidate.year_hint)

    if result:
        return result

    logger.info("Falling back to local metadata for %s", candidate.query)
    return TMDBResult(title=candidate.query, year=candidate.year_hint)


def build_destination(
    source: Path,
    candidate: MediaCandidate,
    metadata: TMDBResult,
    config: Config,
) -> DestinationPlan:
    extension = source.suffix
    title = metadata.title or candidate.query
    year = metadata.year or candidate.year_hint

    safe_title = _safe_component(title or candidate.query) or "Unknown Title"

    if candidate.media_type == "movie":
        year_suffix = f" ({year})" if year else ""
        folder_name = _safe_component(f"{safe_title}{year_suffix}") or safe_title
        file_base = folder_name
        folder = config.movies_dir / folder_name
        destination = folder / f"{file_base}{extension}"
        return DestinationPlan(
            source=source,
            destination=destination,
            title=safe_title,
            year=year,
            media_type="movie",
        )

    # Shows
    season = candidate.season or 1
    episode = candidate.episode or 1
    series_folder = _safe_component(safe_title) or safe_title
    season_folder = config.shows_dir / series_folder / f"Season {season:02d}"
    year_suffix = f" ({year})" if year else ""
    episode_name = _safe_component(f"{safe_title} (S{season:02d}E{episode:02d}){year_suffix}") or safe_title
    destination = season_folder / f"{episode_name}{extension}"
    return DestinationPlan(
        source=source,
        destination=destination,
        title=safe_title,
        year=year,
        media_type="show",
        season=season,
        episode=episode,
    )


__all__ = [
    "MediaCandidate",
    "DestinationPlan",
    "analyse_filename",
    "resolve_metadata",
    "build_destination",
]
