"""Command-line entry point for the streamlined Scanly worker."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .processor import run_forever


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan and organise media files for Jellyfin")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process the source directory once and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for troubleshooting",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    configure_logging(args.verbose)

    try:
        config = Config.from_env()
    except Exception as exc:
        logging.error("Configuration error: %s", exc)
        return 1

    if args.once:
        from .processor import load_state, process_once, save_state
        from .tmdb import TMDBClient

        config.ensure_directories()
        state = load_state(config.state_file)
        tmdb = TMDBClient(config.tmdb_api_key)
        process_once(config, tmdb, state)
        save_state(config.state_file, state)
        return 0

    run_forever(config)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
