"""Tests for the Python client's approval handling."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


class TestRespond:
    def test_posts_decision_with_token(self, monkeypatch):
        from anotify import approval

        captured = {}

        class FakeClient:
            def __init__(self, timeout):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json, headers):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers

                class R:
                    status_code = 200

                return R()

        monkeypatch.setattr(approval, "get_server", lambda: "https://relay.example")
        monkeypatch.setattr(approval, "get_token", lambda: "secret")
        import httpx

        monkeypatch.setattr(httpx, "Client", FakeClient)

        ok = approval.respond("a1", "deny", callback_url="http://127.0.0.1:9/cb")
        assert ok is True
        assert captured["url"] == "https://relay.example/api/approval/respond"
        assert captured["json"] == {
            "approval_id": "a1", "choice": "deny", "callback_url": "http://127.0.0.1:9/cb",
        }
        assert captured["headers"]["Authorization"] == "Bearer secret"

    def test_empty_id_is_noop(self):
        from anotify import approval
        assert approval.respond("", "deny") is False


class TestPrompt:
    def test_definite_choice_posts(self, monkeypatch):
        from anotify import approval

        monkeypatch.setattr(approval, "_ask", lambda title, msg: "once")
        posted = {}
        monkeypatch.setattr(approval, "respond",
                            lambda aid, choice, cb="": posted.update(id=aid, choice=choice))
        approval.prompt({"approval_id": "x", "title": "t", "message": "m"})
        assert posted == {"id": "x", "choice": "once"}

    def test_no_decision_does_not_post(self, monkeypatch):
        from anotify import approval

        monkeypatch.setattr(approval, "_ask", lambda title, msg: "")  # dismissed
        called = MagicMock()
        monkeypatch.setattr(approval, "respond", called)
        approval.prompt({"approval_id": "x", "title": "t", "message": "m"})
        called.assert_not_called()

    def test_missing_id_skips(self, monkeypatch):
        from anotify import approval
        called = MagicMock()
        monkeypatch.setattr(approval, "_ask", called)
        approval.prompt({"title": "t"})  # no approval_id
        called.assert_not_called()


class TestClientDispatch:
    def test_approval_notification_triggers_handler(self):
        from anotify.client import NotifyClient

        c = NotifyClient(server_url="wss://x/ws", token="")
        c._dispatch_native = MagicMock()
        c.muted_sources = set()
        seen = []
        c.on_approval(lambda data: seen.append(data["approval_id"]))
        # Run the handler synchronously for the test.
        with patch("anotify.client.threading.Thread") as thread_cls:
            def _sync(target, args, daemon):
                runner = MagicMock()
                runner.start = lambda: target(*args)
                return runner
            thread_cls.side_effect = _sync
            c._handle_message({
                "id": "n1", "kind": "approval", "approval_id": "ap1",
                "title": "Approve?", "message": "do it", "priority": "high", "source": "ci",
            })
        assert seen == ["ap1"]

    def test_non_approval_does_not_trigger(self):
        from anotify.client import NotifyClient

        c = NotifyClient(server_url="wss://x/ws", token="")
        c._dispatch_native = MagicMock()
        c.muted_sources = set()
        called = MagicMock()
        c.on_approval(called)
        c._handle_message({
            "id": "n2", "title": "done", "message": "x", "priority": "medium", "source": "ci",
        })
        called.assert_not_called()
