from __future__ import annotations

"""Filename cleaning pipeline for the Windows scanner."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .ai_parser import ai_parse_filename

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_SXXEYY_RE = re.compile(r"S(?P<season>\d{1,2})E(?P<episode>\d{1,2})", re.IGNORECASE)
_EPISODE_RE = re.compile(r"\bE(?P<episode>\d{1,2})\b", re.IGNORECASE)
_SEASON_RE = re.compile(r"\bS(?P<season>\d{1,2})\b", re.IGNORECASE)
_SEASON_WORD_RE = re.compile(r"\bseason\s*(?P<season>\d{1,2})\b", re.IGNORECASE)
_EPISODE_WORD_RE = re.compile(r"\bepisode\s*(?P<episode>\d{1,3})\b", re.IGNORECASE)
_RANGE_RE = re.compile(r"(?P<season>\d{1,2})x(?P<episode>\d{1,2})", re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[._\s\-\[\]\(\){}]+")

_STOPWORDS = {
    "aac",
    "ac3",
    "aim",
    "amzn",
    "atmos",
    "bd",
    "bdrip",
    "blu",
    "bluray",
    "brrip",
    "bray",
    "cam",
    "collection",
    "complete",
    "criterion",
    "dts",
    "dual",
    "dual-audio",
    "dubbed",
    "dvd",
    "dvdrip",
    "dz",
    "eac3",
    "eztv",
    "fra",
    "framestor",
    "french",
    "gdrives",
    "ger",
    "hdr",
    "hdr10",
    "hdrip",
    "hevc",
    "hmax",
    "hulu",
    "imax",
    "internal",
    "ita",
    "jpn",
    "lat",
    "latino",
    "limited",
    "multi",
    "multisubs",
    "netflix",
    "nf",
    "prime",
    "proper",
    "psa",
    "rartv",
    "remastered",
    "remux",
    "repack",
    "rip",
    "rus",
    "sd",
    "sub",
    "subs",
    "subfrench",
    "subita",
    "tgx",
    "truefrench",
    "truehd",
    "uhd",
    "unrated",
    "web",
    "webdl",
    "webrip",
    "x264",
    "x265",
    "xvid",
    "yify",
    "yts",
}

_LANGUAGE_TOKENS = {
    "eng",
    "english",
    "ita",
    "italian",
    "spa",
    "spanish",
    "lat",
    "latino",
    "rus",
    "russian",
    "jpn",
    "japanese",
    "kor",
    "korean",
    "fra",
    "french",
    "ger",
    "german",
    "multi",
    "dual",
}

_ANIME_HINTS = {"anime", "ova", "ona"}


@dataclass
class ParsedFilename:
    """Result of the multi-stage filename cleaning pipeline."""

    original: str
    clean_title: str
    normalized_title: str
    year: Optional[int]
    season: Optional[int]
    episode: Optional[int]
    media_type: str
    tokens: List[str]
    folder_hint: str
    ai_data: Dict[str, object]


def _extract_year(text: str) -> Optional[int]:
    match = _YEAR_RE.search(text)
    if match:
        return int(match.group(0))
    return None


def _extract_season_episode(text: str) -> tuple[Optional[int], Optional[int]]:
    season: Optional[int] = None
    episode: Optional[int] = None

    match = _SXXEYY_RE.search(text)
    if match:
        season = int(match.group("season"))
        episode = int(match.group("episode"))
        return season, episode

    match = _RANGE_RE.search(text)
    if match:
        season = int(match.group("season"))
        episode = int(match.group("episode"))

    if season is None:
        match = _SEASON_RE.search(text)
        if match:
            season = int(match.group("season"))
        else:
            match = _SEASON_WORD_RE.search(text)
            if match:
                season = int(match.group("season"))

    if episode is None:
        match = _EPISODE_RE.search(text)
        if match:
            episode = int(match.group("episode"))
        else:
            match = _EPISODE_WORD_RE.search(text)
            if match:
                episode = int(match.group("episode"))

    return season, episode


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _title_tokens(tokens: Iterable[str]) -> List[str]:
    collected: List[str] = []
    for token in tokens:
        if not token:
            continue
        lower = token.lower()
        if lower in {"season", "episode", "part", "disc"}:
            break
        if token.isdigit():
            break
        if _YEAR_RE.fullmatch(token):
            break
        if _SXXEYY_RE.fullmatch(token):
            break
        if _SEASON_RE.fullmatch(token):
            break
        if _EPISODE_RE.fullmatch(token):
            break
        collected.append(token)
    return collected


def _clean_tokens(raw_name: str) -> List[str]:
    tokens = []
    for token in _TOKEN_SPLIT_RE.split(raw_name):
        token = token.strip()
        if not token:
            continue
        lower = token.lower()
        if lower in _STOPWORDS:
            continue
        if lower in _LANGUAGE_TOKENS:
            continue
        if _YEAR_RE.fullmatch(token):
            continue
        if _SXXEYY_RE.fullmatch(token):
            continue
        if _SEASON_RE.fullmatch(token):
            continue
        if _EPISODE_RE.fullmatch(token):
            continue
        if _RANGE_RE.fullmatch(token):
            continue
        if re.fullmatch(r"\d{3,4}p", lower):
            continue
        if re.fullmatch(r"\d+(?:bit|ch)", lower):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", lower):
            continue
        tokens.append(token)
    return tokens


def _infer_media_type(base_text: str, season: Optional[int], episode: Optional[int]) -> str:
    lowered = base_text.lower()
    if season or episode:
        return "show"
    if any(hint in lowered for hint in _ANIME_HINTS):
        return "anime"
    if "s0" in lowered and "e0" in lowered:
        return "show"
    return "movie"


def _apply_ai_normalisation(
    clean_title: str,
    ai_data: Optional[Dict[str, object]],
) -> tuple[str, Optional[int], Optional[int], Optional[int]]:
    if not ai_data:
        return clean_title, None, None, None

    def _safe_int(value: object) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    sanitised = ai_data.get("sanitised_guess") if isinstance(ai_data, dict) else None
    normalised = _normalize_whitespace(str(sanitised)) if sanitised else ""
    if not normalised:
        tokens = ai_data.get("title_tokens") if isinstance(ai_data, dict) else None
        if isinstance(tokens, list):
            for token in tokens:
                if isinstance(token, str) and token.strip():
                    normalised = _normalize_whitespace(token)
                    if normalised:
                        break
    if not normalised:
        normalised = clean_title

    year_hint = _safe_int(ai_data.get("year_hint")) if isinstance(ai_data, dict) else None
    season_hint = _safe_int(ai_data.get("season_hint")) if isinstance(ai_data, dict) else None
    episode_hint = _safe_int(ai_data.get("episode_hint")) if isinstance(ai_data, dict) else None

    return normalised, year_hint, season_hint, episode_hint


def clean_filename(path: Path, *, parent_hint: Optional[str] = None) -> ParsedFilename:
    """Clean a noisy filename and extract structured hints."""

    original = path.name
    raw_name = path.stem
    parent_hint = parent_hint or path.parent.name
    folder_hint = _normalize_whitespace(parent_hint)

    base_text = _normalize_whitespace(original)
    year = _extract_year(base_text)
    season, episode = _extract_season_episode(base_text)
    media_type = _infer_media_type(base_text, season, episode)

    tokens = _clean_tokens(raw_name)
    title_tokens = _title_tokens(tokens)
    clean_title = " ".join(title_tokens) if title_tokens else _normalize_whitespace(raw_name)

    ai_data = ai_parse_filename(original, parent_hint)
    normalized_title, year_hint, season_hint, episode_hint = _apply_ai_normalisation(clean_title, ai_data)

    if not year and year_hint:
        year = year_hint
    if season_hint and not season:
        season = season_hint
    if episode_hint and not episode:
        episode = episode_hint

    if media_type != "show" and any(hint in normalized_title.lower() for hint in _ANIME_HINTS):
        media_type = "anime"
    if media_type == "movie" and (season or episode):
        media_type = "show"

    logger.debug(
        "🧹 Cleaned filename '%s' → title='%s', year=%s, season=%s, episode=%s",  # noqa: TRY400
        original,
        clean_title,
        year,
        season,
        episode,
    )

    return ParsedFilename(
        original=original,
        clean_title=clean_title,
        normalized_title=normalized_title,
        year=year,
        season=season,
        episode=episode,
        media_type=media_type,
        tokens=tokens,
        folder_hint=folder_hint,
        ai_data=ai_data or {},
    )


__all__ = ["ParsedFilename", "clean_filename"]
