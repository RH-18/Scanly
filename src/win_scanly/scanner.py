from __future__ import annotations

"""File system scanning utilities."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .config import Config, get_config

logger = logging.getLogger(__name__)

MIN_SIZE_BYTES = 100 * 1024 * 1024
MIN_DURATION_SECONDS = 15 * 60


def _is_supported(file_path: Path, config: Config) -> bool:
    return config.is_supported(file_path)


def get_media_duration(file_path: Path) -> Optional[float]:
    """Return the media duration in seconds if ffprobe is available."""

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(file_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        data = json.loads(result.stdout)
        duration = data.get("format", {}).get("duration")
        if duration is None:
            return None
        return float(duration)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("ffprobe failed for %s: %s", file_path, exc)
        return None


def _iter_roots(config: Config) -> Iterator[Path]:
    if config.source_dir.exists():
        yield config.source_dir
    else:
        for fallback in config.fallback_dirs:
            if fallback.exists():
                yield fallback


def iter_media_files(config: Optional[Config] = None) -> Iterator[Dict[str, Any]]:
    """Yield metadata for candidate media files."""

    config = config or get_config()
    roots = list(_iter_roots(config))
    if not roots:
        logger.error("❌ No valid source directories found.")
        return

    for root in roots:
        logger.info("🔍 Scanning %s recursively…", root)
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if not _is_supported(file_path, config):
                continue
            try:
                size = file_path.stat().st_size
                if size < MIN_SIZE_BYTES:
                    logger.debug("⏩ Skipped (small) %s [%.1f MB]", file_path.name, size / 1e6)
                    continue
                duration = get_media_duration(file_path)
                if duration is not None and duration < MIN_DURATION_SECONDS:
                    logger.debug(
                        "⏩ Skipped (short) %s [%.1f min]", file_path.name, duration / 60
                    )
                    continue
                yield {
                    "path": file_path,
                    "size_bytes": size,
                    "duration_seconds": duration,
                }
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("⚠️ Error scanning file %s: %s", file_path, exc)
                continue


def scan_summary(config: Optional[Config] = None) -> Dict[str, int]:
    total = passed = skipped = 0
    for entry in iter_media_files(config=config):
        total += 1
        if entry:
            passed += 1
        else:
            skipped += 1
    return {"total": total, "passed": passed, "skipped": skipped}


__all__ = ["iter_media_files", "scan_summary", "get_media_duration"]
