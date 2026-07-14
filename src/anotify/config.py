"""Configuration management for anotify.

Resolves settings from three sources in priority order:
1. CLI flags (passed directly)
2. Environment variables (``ANOTIFY_SERVER``, ``ANOTIFY_TOKEN``)
3. Config file (``~/.anotify.json``)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_SERVER: str = "https://your-server.example"
CONFIG_PATH: Path = Path(os.environ.get("ANOTIFY_CONFIG", "~/.anotify.json")).expanduser()


def load_config() -> dict[str, Any]:
    """Load configuration from the JSON config file.

    Returns an empty dict if the file doesn't exist or is invalid.
    """
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        # A config file containing a non-object (``[]``, ``"x"``, ``42``) would
        # otherwise crash every ``load_config().get(...)`` caller. Treat it as
        # absent rather than letting the AttributeError propagate.
        if isinstance(data, dict):
            return data
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    """Save configuration to the JSON config file.

    Creates parent directories if needed and sets file permissions to 0600.
    """
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)


def get_server() -> str:
    """Resolve the server URL: env variable > config file > default."""
    return (
        os.environ.get("ANOTIFY_SERVER")
        or load_config().get("server", "")
        or DEFAULT_SERVER
    )


def get_token() -> str:
    """Resolve the auth token: env variable > config file."""
    return (
        os.environ.get("ANOTIFY_TOKEN")
        or load_config().get("token", "")
    )


def ensure_ws_url(url: str) -> str:
    """Normalize a URL to a WebSocket ``/ws`` endpoint.

    Converts ``http://`` / ``https://`` schemes to ``ws://`` / ``wss://``
    and appends ``/ws`` if missing.
    """
    if url.startswith("http://"):
        url = "ws://" + url[7:]
    elif url.startswith("https://"):
        url = "wss://" + url[8:]
    if not url.startswith("ws"):
        url = "wss://" + url
    url = url.rstrip("/")
    if not url.endswith("/ws"):
        url += "/ws"
    return url
