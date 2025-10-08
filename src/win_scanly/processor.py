from __future__ import annotations

"""Main processing loop for the Windows pipeline."""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional

from .config import Config, get_config
from .filename_cleaner import ParsedFilename, clean_filename
from .imdb_client import IMDbClient
from .naming import DestinationPlan, MediaCandidate, build_destination
from .scanner import iter_media_files
from .similarity import evaluate_match
from .symlink import create_symlink
from .tmdb import TMDBClient

logger = logging.getLogger(__name__)


def _safe_str(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value is not None else ""


def load_state(path: Path) -> Dict[str, float]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(key): float(value) for key, value in data.items() if isinstance(value, (float, int))}
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("⚠️ Failed to load state: %s", exc)
        return {}


def save_state(path: Path, state: Dict[str, float]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(state, handle)
        temp.replace(path)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("⚠️ Failed to save state: %s", exc)


def process_file(
    entry: Dict,
    tmdb: TMDBClient,
    imdb: IMDbClient,
    state: Dict[str, float],
    config: Config,
    *,
    dry_run: bool = False,
) -> Optional[str]:
    path = entry["path"]
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None

    if state.get(key) == mtime:
        logger.debug("⏭️ Skipping unchanged file: %s", path.name)
        return None

    if not config.is_supported(path):
        logger.debug("⏭️ Skipping unsupported file: %s", path.name)
        state[key] = mtime
        return None

    parsed: ParsedFilename = clean_filename(path, parent_hint=path.parent.name)
    ai_data = parsed.ai_data

    search_query = parsed.clean_title or parsed.normalized_title or path.stem
    imdb_result = imdb.search_title(search_query, parsed.year)
    if not imdb_result and parsed.normalized_title and parsed.normalized_title != search_query:
        candidates = imdb.search_candidates(
            parsed.normalized_title,
            year=parsed.year,
        )
        imdb_result = candidates[0] if candidates else None
    if not imdb_result and parsed.media_type in {"show", "anime"}:
        imdb_result = imdb.search_show(parsed.clean_title or parsed.normalized_title, parsed.season)

    imdb_match = imdb_result if imdb_result and imdb_result.score >= 70 else None
    movie_result = None
    show_result = None
    if not imdb_match:
        logger.info("🌐 TMDB fallback for %s", search_query)
        movie_result = tmdb.search_movie(search_query, parsed.year)
        show_query = parsed.clean_title or parsed.normalized_title or search_query
        show_result = tmdb.search_show(show_query, parsed.year)
    best_result = None
    best_type = None
    similarity_info = None

    if imdb_match:
        best_result, best_type = imdb_match, imdb_match.media_type
        similarity_info = {
            "score": imdb_match.score,
            "accepted": True,
            "warn": imdb_match.score < 80,
            "reason": "imdb_direct",
        }
    elif movie_result and show_result:
        sim_movie = evaluate_match(
            search_query,
            _safe_str(movie_result.title),
            query_year=parsed.year,
            candidate_year=movie_result.year,
        )
        sim_show = evaluate_match(
            parsed.normalized_title,
            _safe_str(show_result.title),
            query_year=parsed.year,
            candidate_year=show_result.year,
            folder_hint=_safe_str(parsed.folder_hint),
        )
        if sim_movie["score"] >= sim_show["score"]:
            best_result, best_type, similarity_info = movie_result, "movie", sim_movie
        else:
            best_result, best_type, similarity_info = show_result, "show", sim_show
    elif movie_result:
        best_result, best_type = movie_result, "movie"
        similarity_info = evaluate_match(
            search_query,
            _safe_str(movie_result.title),
            query_year=parsed.year,
            candidate_year=movie_result.year,
        )
    elif show_result:
        best_result, best_type = show_result, "show"
        similarity_info = evaluate_match(
            parsed.normalized_title,
            _safe_str(show_result.title),
            query_year=parsed.year,
            candidate_year=show_result.year,
            folder_hint=_safe_str(parsed.folder_hint),
        )

    if not best_result or not similarity_info or not similarity_info["accepted"]:
        logger.warning("⚠️ Unmatched file: %s", path.name)
        config.unmatched_dir.mkdir(parents=True, exist_ok=True)
        json_path = config.unmatched_dir / f"{path.stem}.json"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "file": str(path),
                    "ai": ai_data,
                    "imdb": getattr(imdb_result, "__dict__", {}),
                    "movie": getattr(movie_result, "__dict__", {}),
                    "show": getattr(show_result, "__dict__", {}),
                    "similarity": similarity_info,
                },
                handle,
                indent=2,
            )
        state[key] = mtime
        return None

    candidate = MediaCandidate(
        media_type=best_type,
        query=_safe_str(best_result.title),
        year_hint=best_result.year,
        season=parsed.season,
        episode=parsed.episode,
    )
    plan: DestinationPlan = build_destination(path, candidate, best_result, config)
    if not dry_run:
        ok = create_symlink(plan.source, plan.destination)
        if ok:
            logger.info("✅ Linked %s: %s", best_type.title(), plan.destination)
    else:
        logger.info("🧪 Dry-run: would link %s → %s", path.name, plan.destination)

    state[key] = mtime
    return str(plan.destination)


def process_once(
    tmdb_api_key: str,
    *,
    config: Optional[Config] = None,
    dry_run: bool = False,
) -> None:
    config = config or get_config()
    tmdb = TMDBClient(tmdb_api_key)
    imdb_client = IMDbClient(
        config.imdb_db_path,
        embedding_enabled=config.embedding_enabled,
    )
    state = load_state(config.state_file)
    config.ensure_directories()
    logger.info("🧭 Starting single scan across source directories…")
    processed = 0
    for entry in iter_media_files(config=config):
        try:
            dest = process_file(entry, tmdb, imdb_client, state, config, dry_run=dry_run)
            if dest:
                processed += 1
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("💥 Error processing %s: %s", entry["path"], exc)
    save_state(config.state_file, state)
    logger.info("📦 Scan complete — %d processed, %d total tracked.", processed, len(state))


def run_forever(
    tmdb_api_key: str,
    *,
    config: Optional[Config] = None,
    interval: int = 60,
) -> None:
    config = config or get_config()
    logger.info("🟢 Continuous watcher started (interval=%ds)…", interval)
    while True:
        try:
            process_once(tmdb_api_key, config=config, dry_run=False)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("💥 Error during run cycle: %s", exc)
        time.sleep(interval)


__all__ = [
    "process_once",
    "run_forever",
    "process_file",
    "load_state",
    "save_state",
]
