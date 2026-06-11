"""Tests for anotify config module."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from anotify.config import (
    DEFAULT_SERVER,
    ensure_ws_url,
    get_server,
    get_token,
    load_config,
    save_config,
)


@pytest.fixture
def tmp_config(tmp_path):
    """Temporarily override CONFIG_PATH."""
    import anotify.config
    original = anotify.config.CONFIG_PATH
    new_path = tmp_path / ".anotify.json"
    anotify.config.CONFIG_PATH = new_path
    yield new_path
    anotify.config.CONFIG_PATH = original


class TestLoadConfig:
    def test_missing_file_returns_empty(self, tmp_path):
        import anotify.config
        original = anotify.config.CONFIG_PATH
        anotify.config.CONFIG_PATH = tmp_path / "nonexistent.json"
        assert load_config() == {}
        anotify.config.CONFIG_PATH = original

    def test_valid_json(self, tmp_config):
        tmp_config.write_text('{"server": "wss://test.com/ws", "token": "abc"}')
        cfg = load_config()
        assert cfg["server"] == "wss://test.com/ws"
        assert cfg["token"] == "abc"

    def test_invalid_json_returns_empty(self, tmp_config):
        tmp_config.write_text("{bad json")
        assert load_config() == {}

    @pytest.mark.parametrize("body", ["[]", '"a string"', "42", "true", "null"])
    def test_non_object_json_returns_empty(self, tmp_config, body):
        # A config file whose top-level value isn't an object used to crash
        # every load_config().get(...) caller with AttributeError. Guard it.
        tmp_config.write_text(body)
        assert load_config() == {}


class TestSaveConfig:
    def test_creates_file(self, tmp_path):
        import anotify.config
        original = anotify.config.CONFIG_PATH
        path = tmp_path / "new" / ".anotify.json"
        anotify.config.CONFIG_PATH = path
        save_config({"server": "test"})
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["server"] == "test"
        assert oct(path.stat().st_mode)[-3:] == "600"
        anotify.config.CONFIG_PATH = original

    def test_overwrites(self, tmp_config):
        tmp_config.write_text('{"old": true}')
        save_config({"new": True})
        data = json.loads(tmp_config.read_text())
        assert data == {"new": True}


class TestGetServer:
    def test_env_overrides_config(self, tmp_config):
        tmp_config.write_text('{"server": "from-file"}')
        with patch.dict(os.environ, {"ANOTIFY_SERVER": "from-env"}):
            assert get_server() == "from-env"

    def test_falls_back_to_config(self, tmp_config):
        tmp_config.write_text('{"server": "from-file"}')
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANOTIFY_SERVER", None)
            assert get_server() == "from-file"

    def test_falls_back_to_default(self, tmp_path):
        import anotify.config
        original = anotify.config.CONFIG_PATH
        anotify.config.CONFIG_PATH = tmp_path / "missing.json"
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANOTIFY_SERVER", None)
            assert get_server() == DEFAULT_SERVER
        anotify.config.CONFIG_PATH = original


class TestGetToken:
    def test_env_overrides(self, tmp_config):
        tmp_config.write_text('{"token": "file-token"}')
        with patch.dict(os.environ, {"ANOTIFY_TOKEN": "env-token"}):
            assert get_token() == "env-token"

    def test_falls_back_to_config(self, tmp_config):
        tmp_config.write_text('{"token": "file-token"}')
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANOTIFY_TOKEN", None)
            assert get_token() == "file-token"


class TestEnsureWsUrl:
    @pytest.mark.parametrize("input_url,expected", [
        ("https://example.com", "wss://example.com/ws"),
        ("http://example.com", "ws://example.com/ws"),
        ("wss://example.com/ws", "wss://example.com/ws"),
        ("ws://example.com/ws", "ws://example.com/ws"),
        ("example.com", "wss://example.com/ws"),
        ("https://example.com/", "wss://example.com/ws"),
        ("https://example.com/ws", "wss://example.com/ws"),
    ])
    def test_url_normalization(self, input_url, expected):
        assert ensure_ws_url(input_url) == expected
