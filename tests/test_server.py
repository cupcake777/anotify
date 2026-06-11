"""Tests for anotify server (FastAPI + WebSocket)."""

from __future__ import annotations

import os
import sys

import pytest

# Add server/ to path so `import server` resolves to server/server.py
_server_dir = os.path.join(os.path.dirname(__file__), "..", "server")
if _server_dir not in sys.path:
    sys.path.insert(0, _server_dir)

from fastapi.testclient import TestClient as FastAPITestClient  # noqa: E402

import server as srv  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset server state between tests."""
    srv.TOKEN = "test-token"
    srv.PUBLIC_MODE = False
    srv.connected_clients.clear()
    srv.history.clear()
    srv._rate_buckets.clear()
    srv.approval_decisions.clear()
    srv.approval_waiters.clear()
    yield


@pytest.fixture
def client():
    """Create a test client."""
    return FastAPITestClient(srv.app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


# ── Health ──

class TestHealth:
    def test_health_no_auth(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["clients"] == 0
        assert data["history"] == 0


# ── Notify ──

class TestNotify:
    def test_send_notification(self, client, auth_headers):
        resp = client.post(
            "/api/notify",
            json={"message": "test", "title": "T", "priority": "medium"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["delivered"] == 0

    def test_send_no_auth(self, client):
        resp = client.post("/api/notify", json={"message": "test"})
        assert resp.status_code == 401

    def test_send_wrong_token(self, client):
        resp = client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    def test_send_stores_history(self, client, auth_headers):
        client.post("/api/notify", json={"message": "hello"}, headers=auth_headers)
        resp = client.get("/api/history", headers=auth_headers)
        assert len(resp.json()["notifications"]) == 1
        assert resp.json()["notifications"][0]["message"] == "hello"

    def test_priority_validation(self, client, auth_headers):
        resp = client.post(
            "/api/notify",
            json={"message": "test", "priority": "invalid"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_message_truncation(self, client, auth_headers):
        client.post("/api/notify", json={"message": "x" * 2000}, headers=auth_headers)
        resp = client.get("/api/history", headers=auth_headers)
        assert len(resp.json()["notifications"][0]["message"]) <= 1000

    def test_public_mode_open_without_token(self, client):
        """Public mode + no token configured = open relay (anyone may send)."""
        srv.PUBLIC_MODE = True
        srv.TOKEN = ""
        resp = client.post("/api/notify", json={"message": "public test"})
        assert resp.status_code == 200

    def test_public_mode_enforces_token_when_set(self, client, auth_headers):
        """A configured token is enforced even in public mode."""
        srv.PUBLIC_MODE = True
        srv.TOKEN = "test-token"
        # No auth → rejected
        assert client.post("/api/notify", json={"message": "x"}).status_code == 401
        # Correct token → accepted
        resp = client.post("/api/notify", json={"message": "x"}, headers=auth_headers)
        assert resp.status_code == 200

    def test_rate_limit(self, client, auth_headers):
        srv.RATE_LIMIT_PER_MINUTE = 3
        for _ in range(3):
            client.post("/api/notify", json={"message": "test"}, headers=auth_headers)
        resp = client.post("/api/notify", json={"message": "test"}, headers=auth_headers)
        assert resp.status_code == 429


# ── History ──

class TestHistory:
    def test_requires_auth(self, client):
        assert client.get("/api/history").status_code == 401

    def test_returns_list(self, client, auth_headers):
        resp = client.get("/api/history", headers=auth_headers)
        assert resp.status_code == 200
        assert "notifications" in resp.json()


# ── Approval Response ──
class TestApprovalResponse:
    def test_requires_auth(self, client):
        resp = client.post(
            "/api/approval/respond",
            json={"approval_id": "a1", "choice": "accepted"},
        )
        assert resp.status_code == 401

    def test_rejects_nonlocal_callback(self, client, auth_headers):
        resp = client.post(
            "/api/approval/respond",
            json={
                "approval_id": "a1",
                "choice": "accepted",
                "callback_url": "https://example.com/cb",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_uses_history_callback_and_normalizes_choice(self, client, auth_headers, monkeypatch):
        captured = {}

        class FakeAsyncClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, json):
                captured["url"] = url
                captured["json"] = json

                class Resp:
                    status_code = 200
                    text = "ok"

                return Resp()

        monkeypatch.setattr(srv.httpx, "AsyncClient", FakeAsyncClient)
        client.post(
            "/api/notify",
            json={
                "message": "approval",
                "approval_id": "a1",
                "callback_url": "http://127.0.0.1:12345/approval/respond",
            },
            headers=auth_headers,
        )
        resp = client.post(
            "/api/approval/respond",
            json={"approval_id": "a1", "choice": "accepted"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["choice"] == "once"
        assert captured == {
            "url": "http://127.0.0.1:12345/approval/respond",
            "json": {"approval_id": "a1", "choice": "once"},
        }


# ── Model ──

class TestNotificationModel:
    def test_defaults(self):
        n = srv.Notification(message="test")
        assert n.title == "Agent Notification"
        assert n.priority == "medium"

    def test_custom(self):
        n = srv.Notification(message="m", title="t", priority="high", source="hpc")
        assert n.priority == "high"
        assert n.source == "hpc"


# ── Approval long-poll (outbound-only model) ──
class TestApprovalLongPoll:
    def test_respond_records_decision_without_callback(self, client, auth_headers):
        # No callback_url → decision is recorded for a waiter, not an error.
        resp = client.post(
            "/api/approval/respond",
            json={"approval_id": "p1", "choice": "deny"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["choice"] == "deny"
        assert resp.json()["delivery"] == "poll"
        assert srv.approval_decisions["p1"]["choice"] == "deny"

    def test_wait_returns_already_decided_immediately(self, client, auth_headers):
        client.post(
            "/api/approval/respond",
            json={"approval_id": "p2", "choice": "accepted"},
            headers=auth_headers,
        )
        resp = client.get("/api/approval/wait/p2?timeout=1", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["choice"] == "once"  # normalized

    def test_wait_times_out_when_pending(self, client, auth_headers):
        resp = client.get("/api/approval/wait/never?timeout=0", headers=auth_headers)
        assert resp.status_code == 408

    def test_wait_requires_auth(self, client):
        assert client.get("/api/approval/wait/x?timeout=0").status_code == 401

    def test_kind_propagates_through_notify(self, client, auth_headers):
        # The model now carries kind/action/target end to end.
        client.post(
            "/api/notify",
            json={"message": "ok?", "kind": "approval", "action": "rm -rf", "target": "/tmp/x"},
            headers=auth_headers,
        )
        hist = client.get("/api/history", headers=auth_headers).json()["notifications"]
        assert hist[-1]["kind"] == "approval"
        assert hist[-1]["action"] == "rm -rf"
        assert hist[-1]["target"] == "/tmp/x"
