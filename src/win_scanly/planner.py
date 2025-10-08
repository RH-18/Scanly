from __future__ import annotations

"""Dry-run planner for the Windows pipeline."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config, get_config
from .filename_cleaner import ParsedFilename, clean_filename
from .imdb_client import IMDbClient
from .naming import DestinationPlan, MediaCandidate, build_destination
from .scanner import iter_media_files
from .similarity import evaluate_match
from .symlink import create_symlink
from .tmdb import TMDBClient

logger = logging.getLogger(__name__)

PLAN_FILE = Path("scanly_plan.jsonl")
SUMMARY_FILE = Path("summary.json")


def _safe_str(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value is not None else ""


def _write_jsonl(record: Dict[str, Any]) -> None:
    PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PLAN_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_unmatched(
    config: Config,
    file_path: Path,
    ai_result: Dict[str, Any],
    *,
    imdb_candidates: List[Dict[str, Any]],
    tmdb_candidates: List[Dict[str, Any]],
) -> None:
    config.unmatched_dir.mkdir(parents=True, exist_ok=True)
    sidecar = config.unmatched_dir / f"{file_path.stem}.json"
    payload = {
        "file": str(file_path),
        "ai_parse": ai_result,
        "imdb_candidates": imdb_candidates,
        "tmdb_candidates": tmdb_candidates,
        "timestamp": datetime.now().isoformat(),
    }
    with sidecar.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def run_plan(
    tmdb_api_key: str,
    *,
    config: Optional[Config] = None,
    dry_run: bool = True,
) -> Dict[str, int]:
    config = config or get_config()
    PLAN_FILE.unlink(missing_ok=True)
    summary = {
        "scanned": 0,
        "skipped_small": 0,
        "skipped_short": 0,
        "matched_movies": 0,
        "matched_shows": 0,
        "unmatched": 0,
    }
    tmdb = TMDBClient(tmdb_api_key)
    imdb_client = IMDbClient(
        config.imdb_db_path,
        embedding_enabled=config.embedding_enabled,
    )
    logger.info("🚀 Starting Scanly Windows pipeline…")
    for entry in iter_media_files(config=config):
        path: Path = entry["path"]
        summary["scanned"] += 1
        parsed: ParsedFilename = clean_filename(path, parent_hint=path.parent.name)
        ai_data = parsed.ai_data
        search_query = parsed.clean_title or parsed.normalized_title or path.stem

        imdb_candidates_objs = []
        imdb_result = imdb_client.search_title(search_query, parsed.year)
        if imdb_result:
            imdb_candidates_objs.append(imdb_result)

        primary_candidates = imdb_client.search_candidates(search_query, year=parsed.year)
        for candidate in primary_candidates:
            if not any(existing.id == candidate.id for existing in imdb_candidates_objs):
                imdb_candidates_objs.append(candidate)

        if parsed.normalized_title and parsed.normalized_title != search_query:
            alt_candidates = imdb_client.search_candidates(parsed.normalized_title, year=parsed.year)
            if not imdb_result and alt_candidates:
                imdb_result = alt_candidates[0]
            for candidate in alt_candidates:
                if not any(existing.id == candidate.id for existing in imdb_candidates_objs):
                    imdb_candidates_objs.append(candidate)

        if not imdb_result and parsed.media_type in {"show", "anime"}:
            show_candidate = imdb_client.search_show(
                parsed.clean_title or parsed.normalized_title,
                parsed.season,
            )
            if show_candidate:
                imdb_result = show_candidate
                if not any(existing.id == show_candidate.id for existing in imdb_candidates_objs):
                    imdb_candidates_objs.insert(0, show_candidate)

        imdb_match = imdb_result if imdb_result and imdb_result.score >= 70 else None
        movie_result = None
        show_result = None
        if not imdb_match:
            logger.info("🌐 TMDB fallback for %s", search_query)
            movie_result = tmdb.search_movie(search_query, parsed.year)
            show_result = tmdb.search_show(search_query, parsed.year)
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
            )

        if not best_result or not similarity_info or not similarity_info["accepted"]:
            logger.warning("⚠️ Unmatched: %s", path.name)
            summary["unmatched"] += 1
            imdb_payload = [candidate.__dict__ for candidate in imdb_candidates_objs]
            tmdb_payload: List[Dict[str, Any]] = []
            if movie_result:
                tmdb_payload.append(movie_result.__dict__)
            if show_result:
                tmdb_payload.append(show_result.__dict__)
            _write_unmatched(
                config,
                path,
                ai_data,
                imdb_candidates=imdb_payload,
                tmdb_candidates=tmdb_payload,
            )
            record = {
                "file": str(path),
                "status": "unmatched",
                "ai": ai_data,
                "imdb": getattr(imdb_result, "__dict__", {}),
                "similarity": similarity_info,
            }
            _write_jsonl(record)
            continue

        candidate = MediaCandidate(
            media_type=best_type or "unmatched",
            query=_safe_str(best_result.title),
            year_hint=best_result.year,
            season=parsed.season,
            episode=parsed.episode,
        )
        plan: DestinationPlan = build_destination(path, candidate, best_result, config)
        record = {
            "file": str(path),
            "type": best_type,
            "destination": str(plan.destination),
            "score": similarity_info["score"] if similarity_info else None,
            "accepted": similarity_info["accepted"] if similarity_info else False,
            "warn": similarity_info["warn"] if similarity_info else False,
        }
        _write_jsonl(record)
        if not dry_run:
            ok = create_symlink(plan.source, plan.destination)
            if ok:
                if best_type == "movie":
                    summary["matched_movies"] += 1
                else:
                    summary["matched_shows"] += 1

    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    logger.info("✅ Plan complete. Summary written to %s", SUMMARY_FILE)
    return summary


__all__ = ["run_plan"]
