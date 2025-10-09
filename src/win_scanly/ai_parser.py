from __future__ import annotations

"""Thin wrapper around the local Ollama API for filename parsing."""

import json
import logging
import os
import socket
import subprocess
import time
from threading import Lock
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate").strip()
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_MODEL = os.getenv("AI_MODEL", "gemma2:2b").strip()
OLLAMA_BINARY = os.getenv("OLLAMA_PATH", "ollama").strip()
USE_AI = os.getenv("AI_ENABLED", "true").lower() == "true"
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT_SECONDS", "15"))

_AI_LOCK = Lock()
_AI_DISABLED_REASON: Optional[str] = None


def _disable_ai(reason: str) -> None:
    """Disable AI parsing for the remainder of the process."""

    global USE_AI, _AI_DISABLED_REASON
    USE_AI = False
    if _AI_DISABLED_REASON is None:
        _AI_DISABLED_REASON = reason
        logger.warning("⚠️ Disabling AI parsing: %s", reason)


def _is_ollama_running(host: str = "localhost", port: int = OLLAMA_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _start_ollama_service() -> bool:
    """Attempt to start the Ollama background service if it is not already running."""

    if _is_ollama_running():
        return True

    try:
        logger.info("🧠 Starting Ollama service…")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [OLLAMA_BINARY, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        for _ in range(10):
            if _is_ollama_running():
                logger.info("✅ Ollama service started successfully.")
                return True
            time.sleep(1)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("⚠️ Failed to start Ollama: %s", exc)

    return _is_ollama_running()


def ai_parse_filename(filename: str, parent: str = "") -> Optional[Dict[str, object]]:
    """Ask the local LLM to parse filename hints for downstream processing."""

    if not USE_AI:
        if _AI_DISABLED_REASON:
            logger.debug("🤖 AI parsing skipped: %s", _AI_DISABLED_REASON)
        else:
            logger.debug("🤖 AI parsing disabled via configuration.")
        return None

    if not _is_ollama_running() and not _start_ollama_service():
        logger.warning("⚠️ Ollama unavailable — skipping AI parsing.")
        return None

    prompt = f"""
You are a filename sanitiser/parser.
You must not decide whether a file is a movie or a TV show.
Extract only helpful tokens and hints. Remove junk tags (resolution, codec, release group, site).
Output strictly valid JSON matching this schema:
{{
  "raw": "...",
  "sanitised_guess": "...",
  "title_tokens": ["..."],
  "year_hint": <int or null>,
  "season_hint": <int or null>,
  "episode_hint": <int or null>,
  "possible_alt_titles": ["..."],
  "removed_tags": ["..."],
  "confidence": 0.0
}}
Rules:
- Do not invent data.
- Use null or [] if unknown.
- Output JSON only, no prose or markdown.
Filename: {filename}
Parent folder: {parent}
"""

    with _AI_LOCK:
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt.strip(),
                    "format": "json",
                    "stream": False,
                },
                timeout=AI_TIMEOUT,
            )
            response.raise_for_status()
            raw = response.json().get("response", "").strip()
            if not raw:
                logger.debug("⚠️ Empty AI response for '%s'", filename)
                return None
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                logger.warning("⚠️ Non-dict AI output for %s: %s", filename, raw[:80])
                return None
            parsed.setdefault("raw", filename)
            parsed.setdefault("sanitised_guess", filename)
            parsed.setdefault("title_tokens", [])
            parsed.setdefault("year_hint", None)
            parsed.setdefault("season_hint", None)
            parsed.setdefault("episode_hint", None)
            parsed.setdefault("possible_alt_titles", [])
            parsed.setdefault("removed_tags", [])
            parsed.setdefault("confidence", 0.0)
            return parsed
        except json.JSONDecodeError:
            logger.warning("⚠️ Invalid JSON from AI for %s", filename)
        except requests.Timeout:
            logger.warning("⏱️ AI parsing timeout for %s", filename)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else "unknown"
            _disable_ai(
                f"HTTP {status_code} from Ollama endpoint while parsing '{filename}'"
            )
        except requests.ConnectionError:
            _disable_ai("unable to reach Ollama service")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("⚠️ AI request failed for %s: %s", filename, exc)

    return None


__all__ = ["ai_parse_filename"]
