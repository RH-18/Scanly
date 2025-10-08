from __future__ import annotations

import pytest

from win_scanly.config import Config
from win_scanly.naming import MediaCandidate, build_destination
from win_scanly.scanner import iter_media_files


@pytest.fixture
def temp_config(tmp_path, monkeypatch) -> Config:
    source = tmp_path / "source"
    fallback = tmp_path / "fallback"
    movies = tmp_path / "movies"
    shows = tmp_path / "shows"
    unmatched = tmp_path / "unmatched"
    state_file = tmp_path / "state.json"

    for directory in (source, movies, shows, unmatched):
        directory.mkdir()

    monkeypatch.setenv("SOURCE_DIR", str(source))
    monkeypatch.setenv("FALLBACK_SOURCE_DIRS", str(fallback))
    monkeypatch.setenv("DEST_MOVIES_DIR", str(movies))
    monkeypatch.setenv("DEST_SHOWS_DIR", str(shows))
    monkeypatch.setenv("DEST_UNMATCHED_DIR", str(unmatched))
    monkeypatch.setenv("STATE_FILE", str(state_file))
    monkeypatch.setenv("ALLOWED_EXTENSIONS", ".mkv")

    return Config.from_env()


def test_config_directories_created(temp_config: Config):
    temp_config.ensure_directories()
    assert temp_config.movies_dir.exists()
    assert temp_config.shows_dir.exists()
    assert temp_config.unmatched_dir.exists()
    assert temp_config.state_file.parent.exists()


def test_build_destination_movie(temp_config: Config, tmp_path):
    source_file = tmp_path / "Avatar.2009.mkv"
    source_file.write_text("dummy")
    candidate = MediaCandidate(media_type="movie", query="Avatar", year_hint=2009)
    tmdb_data = type("TMDB", (), {"title": "Avatar", "year": 2009})()
    plan = build_destination(source_file, candidate, tmdb_data, temp_config)
    assert plan.destination.parent == temp_config.movies_dir / "Avatar (2009)"
    assert plan.destination.name == "Avatar (2009).mkv"


def test_iter_media_files_respects_extensions(temp_config: Config):
    video = temp_config.source_dir / "movie.mkv"
    small = temp_config.source_dir / "skip.mp4"
    video.write_bytes(b"0" * (1024 * 1024 * 150))
    small.write_bytes(b"0" * (1024 * 1024))

    files = list(iter_media_files(config=temp_config))
    assert files
    assert files[0]["path"].name == "movie.mkv"
