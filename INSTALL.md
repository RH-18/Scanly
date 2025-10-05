# Installing Scanly on Windows

## Prerequisites

- Windows 10/11
- Python 3.10 or newer available on the PATH
- Git (optional but recommended)

## 1. Clone and set up the environment

```powershell
git clone https://github.com/amcgready/Scanly.git
cd Scanly
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure credentials and paths

The repository ships with a ready-to-edit `.env`. Update the values to match your setup:

```ini
TMDB_API_KEY=your_tmdb_key
SOURCE_DIR=R:\__all__
DESTINATION_MOVIES=C:\zurgrclone\libraries\Movies
DESTINATION_SHOWS=C:\zurgrclone\libraries\Shows
SCAN_INTERVAL_SECONDS=30
```

Keep the paths absolute and make sure the destination drive allows symlink creation (run Task Scheduler jobs with elevated permissions or enable Windows Developer Mode).

## 3. Run Scanly

```powershell
python -m scanly.main
```

Scanly will stay active until you close the window and will keep retrying until the rclone mount appears. To run a one-off sweep use `python -m scanly.main --once`.

## 4. Schedule it (optional)

Use **Task Scheduler → Create Basic Task** with:

- **Program/script**: `C:\Path\To\Python\python.exe`
- **Add arguments**: `-m scanly.main`
- **Start in**: path to the Scanly repository
- **Run with highest privileges**: enabled

This starts Scanly automatically at boot and keeps Jellyfin libraries in sync with your rclone mount.

## Troubleshooting

- **Symlink creation failed** – run the task with administrator privileges or enable Developer Mode in Windows settings.
- **Files ignored** – confirm the extension is listed in `ALLOWED_EXTENSIONS` and the filename includes movie/year or TV episode markers.
- **TMDB API errors** – verify your key and internet connectivity. Scanly falls back to local naming when TMDB is unavailable.
