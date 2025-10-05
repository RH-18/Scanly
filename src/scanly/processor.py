"""Core processing loop for Scanly."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict

from .config import Config
from .naming import analyse_filename, build_destination, resolve_metadata
from .tmdb import TMDBClient

logger = logging.getLogger(__name__)


def load_state(path: Path) -> Dict[str, float]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(k): float(v) for k, v in data.items()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load state file %s: %s", path, exc)
        return {}


def save_state(path: Path, state: Dict[str, float]) -> None:
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle)
    temp_path.replace(path)


def _symlink(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        else:
            raise RuntimeError(f"Destination path exists and is not a file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(source, destination)
    except OSError:
        # Windows requires the destination directory flag for directory links, but we're
        # only linking files. Re-raise the original error for visibility.
        raise


def process_once(config: Config, tmdb: TMDBClient, state: Dict[str, float]) -> tuple[int, int, int]:
    processed = 0
    linked = 0
    skipped = 0
    for file_path in config.source_dir.rglob("*"):
        if file_path.is_dir() or file_path.is_symlink():
            continue
        if not config.is_supported(file_path):
            continue
        key = str(file_path.resolve())
        try:
            mtime = file_path.stat().st_mtime
        except FileNotFoundError:
            continue
        if state.get(key) == mtime:
            continue

        processed += 1
        candidate = analyse_filename(file_path, config)
        if not candidate:
            logger.info("Skipping %s: unable to determine media type", file_path)
            state[key] = mtime
            skipped += 1
            continue

        metadata = resolve_metadata(candidate, tmdb)
        plan = build_destination(file_path, candidate, metadata, config)

        try:
            _symlink(plan.source, plan.destination)
        except Exception as exc:
            logger.error("Failed to link %s -> %s: %s", plan.source, plan.destination, exc)
            skipped += 1
            continue

        logger.info("Linked %s -> %s", plan.source, plan.destination)
        state[key] = mtime
        linked += 1

    return processed, linked, skipped


def run_forever(config: Config) -> None:
    config.ensure_directories(require_source=False)
    tmdb = TMDBClient(config.tmdb_api_key)
    state = load_state(config.state_file)

    logger.info(
        "Starting Scanly watcher: source=%s movies=%s shows=%s interval=%ss",
        config.source_dir,
        config.movies_dir,
        config.shows_dir,
        config.scan_interval,
    )

    wait_interval = min(max(config.scan_interval // 3, 5), config.scan_interval)
    missing_logged = False

    try:
        while True:
            if not config.source_dir.exists():
                if not missing_logged:
                    logger.warning(
                        "Source directory %s not available; waiting for the mount...",
                        config.source_dir,
                    )
                    missing_logged = True
                time.sleep(wait_interval)
                continue

            if missing_logged:
                logger.info("Source directory %s detected. Resuming scans.", config.source_dir)
                missing_logged = False

            config.ensure_directories(require_source=False)
            processed, linked, skipped = process_once(config, tmdb, state)
            save_state(config.state_file, state)
            if processed:
                logger.info(
                    "Scan complete: %d new/updated files (%d linked, %d skipped)",
                    processed,
                    linked,
                    skipped,
                )
            else:
                logger.info("Scan complete: no changes detected")
            time.sleep(config.scan_interval)
    except KeyboardInterrupt:
        logger.info("Stopping Scanly watcher")
        save_state(config.state_file, state)


__all__ = ["process_once", "run_forever", "load_state", "save_state"]
