"""Tests for anotify CLI module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from anotify.cli import _detect_source, _http_url, cmd_config, cmd_send


class TestHttpUrl:
    @pytest.mark.parametrize("ws,http", [
        ("wss://example.com/ws", "https://example.com/ws"),
        ("ws://example.com/ws", "http://example.com/ws"),
        ("https://example.com/ws", "https://example.com/ws"),
    ])
    def test_conversion(self, ws, http):
        assert _http_url(ws) == http


class TestDetectSource:
    def test_hpc_hostname(self):
        with patch("anotify.cli.socket") as mock_sock:
            mock_sock.gethostname.return_value = "hpc-login01"
            assert _detect_source() == "hpc"

    def test_login_hostname(self):
        with patch("anotify.cli.socket") as mock_sock:
            mock_sock.gethostname.return_value = "login-node"
            assert _detect_source() == "hpc"

    def test_regular_hostname(self):
        with patch("anotify.cli.socket") as mock_sock:
            mock_sock.gethostname.return_value = "my-laptop"
            assert _detect_source() == "my-laptop"


class TestCmdConfig:
    def test_saves_server_and_token(self, tmp_path):
        import anotify.config
        original = anotify.config.CONFIG_PATH
        anotify.config.CONFIG_PATH = tmp_path / ".anotify.json"

        args = MagicMock()
        args.server = "https://test.com"
        args.token = "test-token"
        cmd_config(args)

        data = json.loads((tmp_path / ".anotify.json").read_text())
        assert data["server"] == "https://test.com"
        assert data["token"] == "test-token"
        anotify.config.CONFIG_PATH = original


class TestCmdSend:
    def test_success(self):
        args = MagicMock()
        args.server = "https://test.com"
        args.token = "test-token"
        args.message = "hello"
        args.title = "T"
        args.priority = "medium"
        args.source = "test"
        args.summary = args.script = args.cwd = args.host = args.agent = None
        args.verbose = True

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "delivered": 1}

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            cmd_send(args)  # should not raise

    def test_auth_error(self):
        args = MagicMock()
        args.server = "https://test.com"
        args.token = "bad"
        args.message = "hello"
        args.title = None
        args.priority = "medium"
        args.source = None
        args.summary = args.script = args.cwd = args.host = args.agent = None
        args.verbose = False

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(SystemExit, match="1"):
                cmd_send(args)

    def test_autofills_context_fields(self):
        args = MagicMock()
        args.server = "https://test.com"
        args.token = ""
        args.message = "build done"
        args.title = None
        args.priority = "medium"
        args.source = "ci"
        args.summary = None
        args.script = "bootstrap.R"
        args.cwd = "/home/user/project"
        args.host = "hpc-login"
        args.agent = "claude-code"
        args.verbose = False

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "delivered": 1}

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            cmd_send(args)
            payload = mock_client.post.call_args.kwargs["json"]

        assert payload["cwd"] == "/home/user/project"
        assert payload["host"] == "hpc-login"
        assert payload["script"] == "bootstrap.R"
        assert payload["agent"] == "claude-code"
        # summary derived as "script · dirname" when not given explicitly
        assert payload["summary"] == "bootstrap.R · project"
