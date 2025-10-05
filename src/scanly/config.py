"""Configuration utilities for the streamlined Scanly worker."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

load_dotenv()


def _parse_extensions(raw: str) -> List[str]:
    return [ext.strip().lower() for ext in raw.split(",") if ext.strip()]


def _parse_replacements(raw: str) -> List[Tuple[re.Pattern[str], str]]:
    rules: List[Tuple[re.Pattern[str], str]] = []
    if not raw:
        return rules
    # Allow either a single mapping "pattern => replacement" or a semicolon separated list.
    for chunk in raw.split(";"):
        if "=>" not in chunk:
            continue
        pattern, replacement = chunk.split("=>", 1)
        pattern = pattern.strip()
        replacement = replacement.strip().strip('"').strip("'")
        if not pattern:
            continue
        rules.append((re.compile(pattern), replacement))
    return rules


@dataclass
class Config:
    source_dir: Path
    movies_dir: Path
    shows_dir: Path
    allowed_extensions: List[str]
    tmdb_api_key: str
    scan_interval: int = 30
    rename_pattern: re.Pattern[str] | None = None
    rename_replacements: List[Tuple[re.Pattern[str], str]] = field(default_factory=list)
    state_file: Path = Path("data/processed_files.json")

    @classmethod
    def from_env(cls) -> "Config":
        tmdb_key = os.getenv("TMDB_API_KEY", "").strip()
        if not tmdb_key:
            raise ValueError("TMDB_API_KEY must be set in the environment or .env file")

        source_dir = Path(os.getenv("SOURCE_DIR", "").strip()).expanduser()
        if not source_dir:
            raise ValueError("SOURCE_DIR must be provided in the environment")

        movies_dir_raw = os.getenv("DESTINATION_MOVIES")
        shows_dir_raw = os.getenv("DESTINATION_SHOWS")
        if not movies_dir_raw or not shows_dir_raw:
            base_dest = os.getenv("DESTINATION_DIRECTORY", "").strip()
            if not base_dest:
                raise ValueError(
                    "DESTINATION_MOVIES/DESTINATION_SHOWS or DESTINATION_DIRECTORY must be configured"
                )
            movies_dir_raw = os.path.join(base_dest, os.getenv("CUSTOM_MOVIE_FOLDER", "Movies"))
            shows_dir_raw = os.path.join(base_dest, os.getenv("CUSTOM_SHOW_FOLDER", "Shows"))

        movies_dir = Path(movies_dir_raw).expanduser()
        shows_dir = Path(shows_dir_raw).expanduser()

        interval = int(os.getenv("SCAN_INTERVAL_SECONDS", os.getenv("MONITOR_SCAN_INTERVAL", "30")))

        extensions = _parse_extensions(
            os.getenv(
                "ALLOWED_EXTENSIONS",
                ".mp4,.mkv,.srt,.avi,.mov,.divx,.m4v,.ts,.wmv",
            )
        )

        rename_tags = os.getenv("RENAME_TAGS", "").strip()
        rename_pattern = re.compile(rename_tags, re.IGNORECASE) if rename_tags else None
        replacements = _parse_replacements(os.getenv("RENAME_REPLACEMENTS", r"\.|_|- => \" \""))

        state_file = Path(os.getenv("STATE_FILE", "data/processed_files.json")).expanduser()

        return cls(
            source_dir=source_dir,
            movies_dir=movies_dir,
            shows_dir=shows_dir,
            allowed_extensions=extensions,
            tmdb_api_key=tmdb_key,
            scan_interval=interval,
            rename_pattern=rename_pattern,
            rename_replacements=replacements,
            state_file=state_file,
        )

    def ensure_directories(self, require_source: bool = True) -> None:
        if require_source and not self.source_dir.exists():
            raise FileNotFoundError(f"Source directory does not exist: {self.source_dir}")
        self.movies_dir.mkdir(parents=True, exist_ok=True)
        self.shows_dir.mkdir(parents=True, exist_ok=True)
        if self.state_file.parent:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def is_supported(self, path: Path) -> bool:
        return path.suffix.lower() in self.allowed_extensions

    def apply_replacements(self, text: str) -> str:
        updated = text
        for pattern, replacement in self.rename_replacements:
            updated = pattern.sub(replacement, updated)
        return updated

    def strip_release_tags(self, text: str) -> str:
        if self.rename_pattern is None:
            return text
        return self.rename_pattern.sub(" ", text)


__all__ = ["Config"]
