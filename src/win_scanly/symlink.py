from __future__ import annotations

"""Symlink helpers with NTFS junction fallback."""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_collision(destination: Path) -> Path:
    if not destination.exists():
        return destination
    base = destination.stem
    ext = destination.suffix
    parent = destination.parent
    index = 1
    while True:
        candidate = parent / f"{base} ({index}){ext}"
        if not candidate.exists():
            return candidate
        index += 1


def create_symlink(source: Path, destination: Path) -> bool:
    """Create a symlink or NTFS junction on Windows."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            if destination.is_symlink() and destination.resolve() == source.resolve():
                logger.debug("⏭️ Already linked: %s", destination)
                return True
            destination = _resolve_collision(destination)
        except Exception:  # pragma: no cover - defensive logging
            destination = _resolve_collision(destination)

    try:
        os.symlink(source, destination)
        logger.info("🔗 Created symlink: %s", destination.name)
        return True
    except OSError as exc:
        logger.warning("⚠️ Symlink failed (%s), trying NTFS junction…", exc)

    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("🔗 Created NTFS junction: %s", destination.name)
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("❌ Failed to create junction for %s: %s", source, exc)
        return False


__all__ = ["create_symlink"]
