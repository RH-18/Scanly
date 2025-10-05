# Scanly (Windows-native edition)

Scanly is a lightweight helper that keeps a Real-Debrid/Zurg + rclone workflow tidy on Windows. It watches the messy download drive (`R:\__all__`), looks up clean titles on TMDB, and builds Jellyfin-ready libraries under `C:\zurgrclone\libraries` using symlinks. Drop files into the mount and they appear inside your Movies/Shows folders a few seconds later.

## What it does

- Monitors the source drive and re-scans every 30 seconds (configurable).
- Detects whether a file is a movie or TV episode by filename patterns (SxxEyy, 1x01, etc.).
- Queries TMDB for the canonical title and release year.
- Creates the directory structure Jellyfin expects:
  - Movies → `Movie Name (Year)/Movie Name (Year).ext`
  - Shows → `Show Name/Season 01/Show Name (S01E01) (Year).ext`
- Uses Windows file symlinks so only one copy of the data lives on the rclone mount.

Everything else from the previous project (TUI, Discord/Plex hooks, Docker, resume files, etc.) has been removed so Scanly focuses entirely on this flow.

## Requirements

- Windows 10/11 with Python 3.10+
- rclone mount that exposes the Zurg WebDAV (e.g. `R:\__all__`)
- TMDB API key (free account)

## Installation

```powershell
# Clone and set up a virtual environment
git clone https://github.com/amcgready/Scanly.git
cd Scanly
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Edit `.env` (already committed with sensible defaults):

```ini
TMDB_API_KEY=your_tmdb_key
SOURCE_DIR=R:\__all__
DESTINATION_MOVIES=C:\zurgrclone\libraries\Movies
DESTINATION_SHOWS=C:\zurgrclone\libraries\Shows
SCAN_INTERVAL_SECONDS=30
ALLOWED_EXTENSIONS=.mp4,.mkv,.srt,.avi,.mov,.divx,.m4v,.ts,.wmv
RENAME_TAGS=...long regex for release junk...
RENAME_REPLACEMENTS=\.|_|- => " "
```

Adjust `SCAN_INTERVAL_SECONDS` if you want a longer or shorter delay between passes. When changing paths, keep them as absolute Windows paths.

## Running Scanly

### Continuous monitor (recommended)

```powershell
# From the project root with the virtual environment activated
python -m scanly.main
```

Scanly will run indefinitely, waking every 30 seconds to look for new or updated files in `SOURCE_DIR`. Logs print to the console; schedule the command with Windows Task Scheduler to run at startup or on a timer.

If the rclone drive is not mounted when Scanly starts, it will stay alive and retry until the source path becomes available.

### One-off sweep

```powershell
python -m scanly.main --once
```

Runs a single pass over the source directory and exits. Useful after adjusting configuration.

## Scheduling as a Windows task

1. Open **Task Scheduler** → **Create Basic Task**.
2. Trigger: **At startup** (or any schedule you prefer).
3. Action: **Start a program**.
   - Program/script: `C:\Path\To\Python\python.exe`
   - Add arguments: `-m scanly.main`
   - Start in: `C:\Path\To\Scanly`
4. Enable **Run with highest privileges** so Windows allows symlink creation.

## How matching works

1. File name is normalised (dots/underscores to spaces) and release tags are removed via `RENAME_TAGS`.
2. `SxxEyy` or `1x01` patterns mark the file as a TV episode; otherwise it is treated as a movie.
3. TMDB is queried for the cleaned title (year hints help choose the right result).
4. The destination folder and filename are built using the TMDB title/year.
5. A symlink is created. If the link already exists it is replaced.

If TMDB has no result, Scanly falls back to the cleaned local title/year so files still flow through.

## Data directory

`data/processed_files.json` keeps a light cache of modification times so previously-linked files are skipped until they change. Delete this file to force a full rebuild of symlinks.

## Troubleshooting

- **Symlink permission errors**: Run the scheduled task with administrative privileges or enable Developer Mode in Windows Settings.
- **TMDB failures**: Check your API key and network connectivity. Scanly falls back to local naming but logs a warning.
- **Files not moving**: Ensure the extension is listed in `ALLOWED_EXTENSIONS` and that the filename contains enough information to detect movie vs. TV episode.

## License

MIT License. See `LICENSE` for details.
