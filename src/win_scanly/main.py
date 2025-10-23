from __future__ import annotations

"""Command-line entry point for the Windows pipeline."""

import argparse
import logging
import os
import sys
from pathlib import Path


if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(package_root.parent))

    from win_scanly.config import get_config  # type: ignore[import-not-found]
    from win_scanly.processor import process_once, run_forever  # type: ignore[import-not-found]
else:
    from .config import get_config
    from .processor import process_once, run_forever


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.info("🧠 Scanly Windows Initialising…")
    if verbose:
        logging.getLogger("requests").setLevel(logging.WARNING)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Scanly Windows — AI-assisted media reorganisation"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one complete scan and exit (dry-run safe).",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuous watcher mode (default 60s interval).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Interval in seconds between scans in daemon mode.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform scan and generate plan without linking files.",
    )
    return parser.parse_args(argv or sys.argv[1:])


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)
    config = get_config()
    config.ensure_directories()

    tmdb_key = os.getenv("TMDB_API_KEY", "").strip()
    if not tmdb_key:
        logging.warning("⚠️ TMDB_API_KEY not found in environment — lookups will fail.")

    if args.once:
        logging.info("🧭 Running single full scan (dry-run=%s)…", args.dry_run)
        process_once(tmdb_key, config=config, dry_run=args.dry_run)
        logging.info("✅ Single scan completed.")
        return 0

    if args.daemon:
        logging.info("♻️ Starting continuous watcher (interval=%ds)…", args.interval)
        run_forever(tmdb_key, config=config, interval=args.interval)
        return 0

    logging.info("🧩 No mode selected — running one scan.")
    process_once(tmdb_key, config=config, dry_run=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
