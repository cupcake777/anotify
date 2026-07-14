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


class TestArgOrdering:
    """Global --server/--token are accepted before *or* after the subcommand,
    and the `test` subcommand doesn't crash on missing send-only fields.
    """

    def _run(self, argv):
        import sys

        from anotify import cli

        captured = {}

        def fake_send(args):
            captured["server"] = args.server
            captured["token"] = args.token

        with patch.object(cli, "cmd_send", side_effect=fake_send), \
             patch.object(sys, "argv", ["anotify", *argv]):
            cli.main()
        return captured

    def test_flag_after_subcommand(self):
        out = self._run(["send", "hi", "--server", "https://a.example"])
        assert out["server"] == "https://a.example"

    def test_flag_before_subcommand(self):
        out = self._run(["--server", "https://b.example", "send", "hi"])
        assert out["server"] == "https://b.example"

    def test_flags_split_across_position(self):
        out = self._run(["--token", "T", "send", "hi", "--server", "https://c.example"])
        assert out["server"] == "https://c.example"
        assert out["token"] == "T"

    def test_test_subcommand_has_all_send_fields(self):
        import sys

        from anotify import cli

        seen = {}

        def fake_send(args):
            # cmd_send reads all of these; none should be missing.
            for f in ("message", "title", "priority", "source",
                      "summary", "script", "cwd", "host", "agent",
                      "server", "token", "verbose"):
                seen[f] = getattr(args, f)

        with patch.object(cli, "cmd_send", side_effect=fake_send), \
             patch.object(sys, "argv", ["anotify", "test", "--server", "https://d.example"]):
            cli.main()
        assert seen["server"] == "https://d.example"
        assert seen["message"]  # test fills a default message


class TestApproveExitCodes:
    """`anotify approve` maps the decision to a process exit code."""

    def _run_approve(self, decision):
        import sys

        from anotify import cli

        # Fake httpx: POST /api/notify ok; GET wait returns the decision.
        class FakeResp:
            def __init__(self, status, payload=None):
                self.status_code = status
                self._p = payload or {}

            def json(self):
                return self._p

        class FakeClient:
            def __init__(self, timeout):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json, headers):
                return FakeResp(200, {"ok": True})

            def get(self, url, params, headers, timeout):
                return FakeResp(200, {"choice": decision})

        import httpx

        argv = ["anotify", "approve", "Do it?", "--server", "https://r.example", "--timeout", "5"]
        with patch.object(httpx, "Client", FakeClient), \
             patch.object(sys, "argv", argv), \
             patch("anotify.cli.get_token", return_value=""):
            try:
                cli.main()
            except SystemExit as e:
                return e.code
        return None

    def test_accept_exits_zero(self):
        assert self._run_approve("once") == 0

    def test_session_exits_zero(self):
        assert self._run_approve("session") == 0

    def test_deny_exits_one(self):
        assert self._run_approve("deny") == 1
