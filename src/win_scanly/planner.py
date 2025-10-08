from __future__ import annotations

"""Dry-run planner for the Windows pipeline."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ai_parser import ai_parse_filename
from .config import Config, get_config
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


def _write_unmatched(config: Config, file_path: Path, ai_result: Dict[str, Any], candidates: List[Dict[str, Any]]) -> None:
    config.unmatched_dir.mkdir(parents=True, exist_ok=True)
    sidecar = config.unmatched_dir / f"{file_path.stem}.json"
    payload = {
        "file": str(file_path),
        "ai_parse": ai_result,
        "tmdb_candidates": candidates,
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
    logger.info("🚀 Starting Scanly Windows pipeline…")
    for entry in iter_media_files(config=config):
        path: Path = entry["path"]
        summary["scanned"] += 1
        ai_data = ai_parse_filename(path.name, path.parent.name)
        if not isinstance(ai_data, dict):
            logger.debug("AI parse failed or malformed for: %s", path.name)
            ai_data = {"raw": path.name, "sanitised_guess": path.stem}
        guess = _safe_str(ai_data.get("sanitised_guess", path.stem))
        year_hint = ai_data.get("year_hint")
        season_hint = ai_data.get("season_hint")
        episode_hint = ai_data.get("episode_hint")
        movie_result = tmdb.search_movie(guess, year_hint)
        show_result = tmdb.search_show(guess, year_hint)
        best_result = None
        best_type = None
        similarity_info = None
        if movie_result and show_result:
            sim_movie = evaluate_match(
                guess,
                _safe_str(movie_result.title),
                query_year=year_hint,
                candidate_year=movie_result.year,
            )
            sim_show = evaluate_match(
                guess,
                _safe_str(show_result.title),
                query_year=year_hint,
                candidate_year=show_result.year,
            )
            if sim_movie["score"] >= sim_show["score"]:
                best_result, best_type, similarity_info = movie_result, "movie", sim_movie
            else:
                best_result, best_type, similarity_info = show_result, "show", sim_show
        elif movie_result:
            best_result, best_type = movie_result, "movie"
            similarity_info = evaluate_match(
                guess,
                _safe_str(movie_result.title),
                query_year=year_hint,
                candidate_year=movie_result.year,
            )
        elif show_result:
            best_result, best_type = show_result, "show"
            similarity_info = evaluate_match(
                guess,
                _safe_str(show_result.title),
                query_year=year_hint,
                candidate_year=show_result.year,
            )

        if not best_result or not similarity_info or not similarity_info["accepted"]:
            logger.warning("⚠️ Unmatched: %s", path.name)
            summary["unmatched"] += 1
            _write_unmatched(
                config,
                path,
                ai_data,
                [
                    movie_result.__dict__ if movie_result else {},
                    show_result.__dict__ if show_result else {},
                ],
            )
            record = {
                "file": str(path),
                "status": "unmatched",
                "ai": ai_data,
                "similarity": similarity_info,
            }
            _write_jsonl(record)
            continue

        candidate = MediaCandidate(
            media_type=best_type or "unmatched",
            query=_safe_str(best_result.title),
            year_hint=best_result.year,
            season=season_hint,
            episode=episode_hint,
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
