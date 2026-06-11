"""Regression tests for the v0.3.0-rc6 hardening pass.

Each test pins a specific fix so it cannot silently regress:
- notification content must travel as *data* (argv / env), never interpolated
  into a shell/AppleScript/PowerShell source string;
- ``anotify config`` must not echo the token to stdout;
- the server must enforce the advertised payload-size limit and accept the
  Authorization header for WebSocket auth.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
_server_dir = os.path.join(os.path.dirname(__file__), "..", "server")
if _server_dir not in sys.path:
    sys.path.insert(0, _server_dir)

# A payload that would execute code if interpolated into the backend scripts.
EVIL_PS = '$(Start-Process calc.exe)'
EVIL_APPLESCRIPT = '\\" & (do shell script "open -a Calculator") & \\"'


class TestNotificationInjection:
    def test_windows_content_not_in_command_string(self):
        from anotify import notify_backend

        with patch.object(notify_backend, "platform") as mock_plat, \
             patch.object(notify_backend, "subprocess") as mock_sub:
            mock_plat.system.return_value = "Windows"
            notify_backend.notify("Title", EVIL_PS, "medium")

            args, kwargs = mock_sub.run.call_args
            command_str = " ".join(args[0])
            # The malicious content must NOT appear in the PowerShell source...
            assert EVIL_PS not in command_str
            # ...it must be passed as environment-variable data instead.
            assert kwargs["env"]["ANOTIFY_MESSAGE"] == EVIL_PS

    def test_macos_content_passed_as_argv(self):
        from anotify import notify_backend

        with patch.object(notify_backend, "platform") as mock_plat, \
             patch.object(notify_backend, "subprocess") as mock_sub:
            mock_plat.system.return_value = "Darwin"
            notify_backend.notify("Title", EVIL_APPLESCRIPT, "medium")

            argv = mock_sub.run.call_args[0][0]
            script = argv[2]  # osascript -e <script> <message> <title>
            assert EVIL_APPLESCRIPT not in script
            assert EVIL_APPLESCRIPT in argv  # present only as a separate arg

    def test_linux_uses_option_terminator(self):
        from anotify import notify_backend

        with patch.object(notify_backend, "platform") as mock_plat, \
             patch.object(notify_backend, "subprocess") as mock_sub:
            mock_plat.system.return_value = "Linux"
            notify_backend.notify("-rm -rf", "body", "critical")

            argv = mock_sub.run.call_args[0][0]
            assert "--" in argv
            # critical priority maps to the freedesktop "critical" urgency
            assert "critical" in argv


class TestConfigDoesNotLeakToken:
    def test_token_not_printed(self, tmp_path, capsys):
        import anotify.config
        from anotify.cli import cmd_config

        original = anotify.config.CONFIG_PATH
        anotify.config.CONFIG_PATH = tmp_path / ".anotify.json"
        try:
            args = MagicMock()
            args.server = "https://test.com"
            args.token = "super-secret-token"
            cmd_config(args)
            out = capsys.readouterr().out
            assert "super-secret-token" not in out
            assert "***" in out
        finally:
            anotify.config.CONFIG_PATH = original


class TestServerHardening:
    @pytest.fixture(autouse=True)
    def _reset(self):
        import server as srv
        srv.TOKEN = "test-token"
        srv.PUBLIC_MODE = False
        srv.connected_clients.clear()
        srv.history.clear()
        srv._rate_buckets.clear()
        yield

    def test_oversized_payload_rejected(self):
        from fastapi.testclient import TestClient

        import server as srv

        client = TestClient(srv.app, raise_server_exceptions=False)
        big = {"message": "x" * 5000, "title": "t"}
        resp = client.post(
            "/api/notify", json=big, headers={"Authorization": "Bearer test-token"}
        )
        assert resp.status_code == 413

    def test_ws_accepts_authorization_header(self):
        import server as srv

        ws = MagicMock()
        ws.headers = {"Authorization": "Bearer test-token"}
        ws.query_params = {}
        assert srv.verify_ws_token(ws) is True

    def test_ws_rejects_bad_header(self):
        import server as srv

        ws = MagicMock()
        ws.headers = {"Authorization": "Bearer wrong"}
        ws.query_params = {}
        assert srv.verify_ws_token(ws) is False

    def test_public_mode_does_not_bypass_ws_token(self):
        """Public mode must not disable a configured token on the WS path."""
        import server as srv

        srv.PUBLIC_MODE = True
        srv.TOKEN = "test-token"
        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {}
        assert srv.verify_ws_token(ws) is False  # no token supplied → rejected

    def test_notification_gets_id(self):
        import server as srv

        n = srv.Notification(message="hello")
        assert n.id  # server assigns a stable id used for client-side dedup


class TestOfflineReplay:
    """Client surfaces missed notifications on reconnect, without spam or dups."""

    def _client(self):
        from anotify.client import NotifyClient

        c = NotifyClient(server_url="wss://x/ws", token="")
        c._dispatch_native = MagicMock()  # capture "show a popup" decisions
        return c

    def test_live_notification_shown_once(self):
        c = self._client()
        msg = {"id": "a1", "title": "T", "message": "m", "priority": "medium", "source": "hpc"}
        c._handle_message(dict(msg))
        c._handle_message(dict(msg))  # duplicate id (e.g. rebroadcast)
        assert c._dispatch_native.call_count == 1

    def test_first_history_is_baseline_not_shown(self):
        c = self._client()
        c._handle_message({"type": "history", "notifications": [
            {"id": "h1", "title": "old", "message": "m"},
            {"id": "h2", "title": "old2", "message": "m"},
        ]})
        assert c._dispatch_native.call_count == 0
        assert c._seeded is True

    def test_reconnect_replays_single_missed(self):
        c = self._client()
        # first connect seeds h1 (baseline)
        c._handle_message({"type": "history", "notifications": [
            {"id": "h1", "title": "a", "message": "m"},
        ]})
        # reconnect: h1 already seen, h2 is new → replayed as one popup
        c._handle_message({"type": "history", "notifications": [
            {"id": "h1", "title": "a", "message": "m"},
            {"id": "h2", "title": "b", "message": "m"},
        ]})
        assert c._dispatch_native.call_count == 1
        # the single missed item is shown directly (its title carries through)
        assert "b" in c._dispatch_native.call_args[0][0]

    def test_reconnect_collapses_many_missed(self):
        c = self._client()
        c._handle_message({"type": "history", "notifications": []})  # seed empty
        c._handle_message({"type": "history", "notifications": [
            {"id": "m1", "title": "a", "message": "x"},
            {"id": "m2", "title": "b", "message": "y"},
            {"id": "m3", "title": "c", "message": "z", "priority": "high"},
        ]})
        # three missed → a single summary popup, not three toasts
        assert c._dispatch_native.call_count == 1
        title = c._dispatch_native.call_args[0][0]
        assert "3" in title
        # summary uses the highest priority among the backlog
        assert c._dispatch_native.call_args[0][2] == "high"


class TestQuietControls:
    """DND and per-source mute gate alerting, never the event stream."""

    def _client(self):
        from anotify.client import NotifyClient

        c = NotifyClient(server_url="wss://x/ws", token="")
        c._dispatch_native = MagicMock()
        c.muted_sources = set()  # ignore any persisted config in the test env
        return c

    def _notif(self, **kw):
        base = {"id": kw.get("id", "n1"), "title": "T", "message": "m",
                "priority": "medium", "source": "hpc"}
        base.update(kw)
        return base

    def test_default_alerts(self):
        c = self._client()
        assert c._should_alert(self._notif()) is True

    def test_dnd_suppresses_but_critical_breaks_through(self):
        c = self._client()
        c.set_dnd(True)
        assert c._should_alert(self._notif(priority="medium")) is False
        assert c._should_alert(self._notif(priority="critical")) is True

    def test_dnd_can_suppress_critical_when_configured(self):
        c = self._client()
        c.set_dnd(True)
        c.critical_breaks_dnd = False
        assert c._should_alert(self._notif(priority="critical")) is False

    def test_muted_source_is_absolute(self):
        c = self._client()
        c.muted_sources = {"ci"}
        # even critical from a muted source stays quiet
        assert c._should_alert(self._notif(source="ci", priority="critical")) is False
        assert c._should_alert(self._notif(source="hpc", priority="medium")) is True

    def test_live_dnd_fires_callback_but_no_popup(self):
        c = self._client()
        cb = MagicMock()
        c.on_notification(cb)
        c.set_dnd(True)
        c._handle_message(self._notif(priority="medium"))
        cb.assert_called_once()                  # event still flows through
        assert c._dispatch_native.call_count == 0  # but no popup

    def test_sources_self_populate(self):
        c = self._client()
        c._handle_message(self._notif(id="a", source="hpc"))
        c._handle_message(self._notif(id="b", source="vps"))
        assert c.sources == {"hpc", "vps"}

    def test_toggle_source_round_trips(self, tmp_path):
        import anotify.config
        from anotify.client import NotifyClient

        original = anotify.config.CONFIG_PATH
        anotify.config.CONFIG_PATH = tmp_path / ".anotify.json"
        try:
            c = NotifyClient(server_url="wss://x/ws", token="")
            c.muted_sources = set()
            assert c.toggle_source("noisy") is True   # now muted
            assert "noisy" in c.muted_sources
            # persisted to disk
            import json
            saved = json.loads((tmp_path / ".anotify.json").read_text())
            assert saved["muted_sources"] == ["noisy"]
            assert c.toggle_source("noisy") is False  # unmuted
        finally:
            anotify.config.CONFIG_PATH = original

    def test_replay_respects_dnd(self):
        c = self._client()
        c._handle_message({"type": "history", "notifications": []})  # seed
        c.set_dnd(True)
        c._handle_message({"type": "history", "notifications": [
            self._notif(id="m1", priority="medium"),
            self._notif(id="m2", priority="medium"),
        ]})
        assert c._dispatch_native.call_count == 0  # missed but DND → no popup


class TestClassify:
    """Canonical event classification shared by every visual surface."""

    def test_error(self):
        from anotify.events import classify
        assert classify(title="Build failed on CI") == "error"

    def test_complete(self):
        from anotify.events import classify
        assert classify(title="Training job done") == "complete"

    def test_approval(self):
        from anotify.events import classify
        assert classify(message="permission needed to write file") == "approval"

    def test_message(self):
        from anotify.events import classify
        assert classify(title="New message from agent") == "message"

    def test_default_info(self):
        from anotify.events import classify
        assert classify(title="heartbeat") == "info"

    def test_critical_without_keyword_is_error(self):
        from anotify.events import classify
        assert classify(title="status update", priority="critical") == "error"

    def test_client_annotates_kind_on_event_stream(self):
        from anotify.client import NotifyClient

        c = NotifyClient(server_url="ws://x/ws", token="")
        c._dispatch_native = MagicMock()
        c.muted_sources = set()
        seen: list[str] = []
        c.on_notification(lambda d: seen.append(d.get("kind", "")))
        c._handle_message({"id": "k1", "title": "deploy failed", "message": "",
                           "priority": "high", "source": "ci"})
        assert seen == ["error"]


class TestServerHygiene:
    @pytest.fixture(autouse=True)
    def _reset(self):
        import server as srv
        srv.TOKEN = "test-token"
        srv.PUBLIC_MODE = False
        srv.connected_clients.clear()
        srv.history.clear()
        srv._rate_buckets.clear()
        srv._sweep_counter = 0
        srv.ws_ips.clear()
        yield

    def test_delivered_counts_connected_clients(self):
        from fastapi.testclient import TestClient

        import server as srv

        client = TestClient(srv.app, raise_server_exceptions=False)
        headers = {"Authorization": "Bearer test-token"}
        with client.websocket_connect("/ws?token=test-token") as ws:
            ws.receive_json()  # initial history frame
            resp = client.post("/api/notify", json={"message": "hi"}, headers=headers)
            assert resp.json()["delivered"] == 1
            pushed = ws.receive_json()
            assert pushed["message"] == "hi"
            assert pushed["id"]  # carries the dedup id end to end

    def test_rate_bucket_sweep_evicts_stale_ips(self):
        import time as _t

        import server as srv

        srv._rate_buckets["1.2.3.4"] = [_t.time() - 120]  # stale (idle > 60s)
        srv._sweep_counter = srv._SWEEP_EVERY - 1          # next call triggers sweep
        srv.check_rate_limit("5.6.7.8")
        assert "1.2.3.4" not in srv._rate_buckets           # swept away
        assert "5.6.7.8" in srv._rate_buckets               # active IP kept


class TestReconnect:
    """NotifyClient.reconnect() forces an immediate reconnect (used by the
    settings window so server/token changes take effect now, not on next drop).
    """

    def _client(self):
        from anotify.client import NotifyClient

        return NotifyClient(server_url="wss://x/ws", token="")

    def test_reconnect_before_run_is_noop(self):
        # No loop/socket yet (run() not started) → must not raise.
        c = self._client()
        c.reconnect()  # should be a safe no-op

    def test_reconnect_schedules_socket_close(self):
        from unittest.mock import MagicMock

        c = self._client()

        async def _fake_close():
            return None

        # Stand in for a live loop + websocket.
        loop = MagicMock()
        ws = MagicMock()
        ws.close = _fake_close
        c._loop = loop
        c._ws = ws
        c.reconnect()
        # It must hop onto the loop thread rather than touching the socket
        # directly from the caller's thread.
        assert loop.call_soon_threadsafe.called
        # Backoff is reset so the fresh attempt happens promptly.
        assert c._reconnect_delay == 1.0
