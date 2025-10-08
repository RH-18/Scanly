from __future__ import annotations

"""Destination planning helpers for matched media."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MediaCandidate:
    media_type: str
    query: str
    year_hint: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None


@dataclass
class DestinationPlan:
    source: Path
    destination: Path
    canonical_name: str
    media_type: str


def _safe_component(text: str) -> str:
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1F]", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _format_season(season: Optional[int]) -> str:
    return f"Season {season:02d}" if season else "Season 01"


def _format_episode(season: Optional[int], episode: Optional[int]) -> str:
    if season is None or episode is None:
        return ""
    return f"S{season:02d}E{episode:02d}"


def build_destination(source: Path, candidate: MediaCandidate, tmdb_data, config) -> DestinationPlan:
    """Map a media candidate to its final destination."""

    title = getattr(tmdb_data, "title", None) or candidate.query or source.stem
    year = getattr(tmdb_data, "year", None) or candidate.year_hint
    clean_title = _safe_component(title)

    if not getattr(tmdb_data, "title", None):
        unmatched_dir = getattr(config, "unmatched_dir", Path.cwd() / "_Unmatched")
        destination = unmatched_dir / source.name
        logger.warning("⚠️ Unmatched canonical name, using fallback path for %s", source.name)
        return DestinationPlan(
            source=source,
            destination=destination,
            canonical_name=source.stem,
            media_type="unmatched",
        )

    if candidate.media_type == "movie":
        folder_name = f"{clean_title} ({year})" if year else clean_title
        file_name = f"{folder_name}{source.suffix}"
        dest_dir = config.movies_dir / folder_name
        destination = dest_dir / file_name
        canonical = folder_name
    elif candidate.media_type in {"show", "anime"}:
        season_dir = _format_season(candidate.season)
        sxxexx = _format_episode(candidate.season, candidate.episode)
        base_name = f"{clean_title} ({year})" if year else clean_title
        file_name = f"{clean_title} - {sxxexx}" if sxxexx else clean_title
        file_name = f"{file_name}{source.suffix}"
        dest_dir = config.shows_dir / base_name / season_dir
        destination = dest_dir / file_name
        canonical = f"{base_name}/{season_dir}/{file_name}"
    else:
        unmatched_dir = getattr(config, "unmatched_dir", Path.cwd() / "_Unmatched")
        destination = unmatched_dir / source.name
        canonical = source.stem

    logger.debug("🏗️ Canonical path for %s: %s", candidate.media_type, destination)
    return DestinationPlan(
        source=source,
        destination=destination,
        canonical_name=canonical,
        media_type=candidate.media_type,
    )


__all__ = ["MediaCandidate", "DestinationPlan", "build_destination"]
