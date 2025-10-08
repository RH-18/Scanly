from __future__ import annotations

"""Configuration helpers tailored for the Windows-focused pipeline."""

import os
import re
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env either from project root or current working directory.
_ENV_PATH_CANDIDATES: Tuple[Path, ...] = (
    Path(__file__).resolve().parents[2] / ".env",
    Path.cwd() / ".env",
)
for candidate in _ENV_PATH_CANDIDATES:
    if candidate.exists():
        load_dotenv(candidate)
        break
else:
    load_dotenv()


@dataclass(frozen=True)
class Config:
    """Container for runtime configuration."""

    tmdb_api_key: str
    source_dir: Path
    fallback_dirs: Tuple[Path, ...]
    movies_dir: Path
    shows_dir: Path
    unmatched_dir: Path
    scan_interval: int
    allowed_extensions: Tuple[str, ...]
    rename_tags: re.Pattern[str]
    rename_replacements: Dict[str, str]
    state_file: Path
    ai_enabled: bool
    ai_model: str
    ai_timeout: int
    ollama_path: str

    @staticmethod
    def from_env() -> "Config":
        """Build a :class:`Config` from environment variables."""

        source_override = os.getenv("SOURCE_DIR")
        fallback_override = os.getenv("FALLBACK_SOURCE_DIRS")

        if source_override:
            source_dir = Path(source_override).expanduser()
        else:
            candidates = [
                Path(r"R:\\_all_"),
                Path(r"R:\\Shows"),
                Path(r"R:\\Movies"),
            ]
            source_dir = next((path for path in candidates if path.exists()), Path.cwd() / "input")

        if fallback_override:
            fallback_dirs: Tuple[Path, ...] = tuple(
                Path(part.strip()).expanduser()
                for part in fallback_override.split(";")
                if part.strip()
            )
        else:
            fallback_dirs = (
                Path(r"R:\\Shows"),
                Path(r"R:\\Movies"),
            )

        movies_dir = Path(os.getenv("DEST_MOVIES_DIR", r"C:\\zurgrclone\\libraries\\movies")).expanduser()
        shows_dir = Path(os.getenv("DEST_SHOWS_DIR", r"C:\\zurgrclone\\libraries\\shows")).expanduser()
        unmatched_dir = Path(
            os.getenv("DEST_UNMATCHED_DIR", r"C:\\zurgrclone\\libraries\\_Unmatched")
        ).expanduser()

        allowed_extensions = tuple(
            ext.strip().lower()
            for ext in os.getenv(
                "ALLOWED_EXTENSIONS",
                ".mp4,.mkv,.avi,.mov,.m4v,.ts,.wmv",
            ).split(",")
            if ext.strip()
        )

        rename_tags = re.compile(
            os.getenv(
                "RENAME_TAGS",
                r"(?i)(^|[ ._\-\[(])(?:WEB[ ._-]?DL|WEBRip|Blu[ ._-]?Ray|x264|x265|1080p|720p)(?=$|[ ._\-\]),])",
            )
        )

        rename_replacements = {
            pattern: repl
            for pattern, repl in {
                r"\\.|_|-": " ",
            }.items()
        }

        return Config(
            tmdb_api_key=os.getenv("TMDB_API_KEY", "").strip(),
            source_dir=source_dir,
            fallback_dirs=fallback_dirs,
            movies_dir=movies_dir,
            shows_dir=shows_dir,
            unmatched_dir=unmatched_dir,
            scan_interval=int(os.getenv("SCAN_INTERVAL_SECONDS", "60")),
            allowed_extensions=allowed_extensions,
            rename_tags=rename_tags,
            rename_replacements=rename_replacements,
            state_file=Path(os.getenv("STATE_FILE", "data/state.json")),
            ai_enabled=os.getenv("AI_ENABLED", "true").lower() == "true",
            ai_model=os.getenv("AI_MODEL", "gemma2:2b").strip(),
            ai_timeout=int(os.getenv("AI_TIMEOUT_SECONDS", "15")),
            ollama_path=os.getenv("OLLAMA_PATH", "ollama").strip(),
        )

    def ensure_directories(self) -> None:
        """Ensure writable output directories exist without touching read-only sources."""

        # The source and fallback directories may be mounted read-only (e.g. rclone WebDAV).
        # Avoid creating them, but warn if none of them currently exist.
        readable_roots = [self.source_dir, *self.fallback_dirs]
        if not any(path.exists() for path in readable_roots):
            logger.warning(
                "⚠️ No readable source directories found among: %s",
                ", ".join(str(path) for path in readable_roots),
            )

        # Ensure destination and state directories exist.
        for directory in (self.movies_dir, self.shows_dir, self.unmatched_dir):
            if not directory.exists():
                logger.info("📁 Creating directory: %s", directory)
                directory.mkdir(parents=True, exist_ok=True)

        state_parent = self.state_file.parent
        if not state_parent.exists():
            logger.info("📁 Creating state directory: %s", state_parent)
            state_parent.mkdir(parents=True, exist_ok=True)

    def apply_replacements(self, text: str) -> str:
        for pattern, repl in self.rename_replacements.items():
            text = re.sub(pattern, repl, text)
        return text.strip()

    def strip_release_tags(self, text: str) -> str:
        return self.rename_tags.sub(" ", text)

    def is_supported(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.allowed_extensions


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return a cached :class:`Config` instance."""
    return Config.from_env()


__all__ = ["Config", "get_config"]
