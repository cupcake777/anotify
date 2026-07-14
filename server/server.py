"""anotify-server: Lightweight WebSocket relay for agent notifications.

Accepts notifications via REST API (``POST /api/notify``) and pushes them to
all connected desktop clients over WebSocket.  Includes token authentication,
rate limiting, payload size limits, and an in-memory history buffer.

Usage::

    python server.py --port 7799 --token YOUR_SECRET

Public relay mode (default on HF Spaces)::

    python server.py --public
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

# ── Config ─────────────────────────────────────────────────────────────

MAX_PAYLOAD_BYTES: int = 2048          # 2KB per notification
MAX_HISTORY: int = 100                 # in-memory history cap
RATE_LIMIT_PER_MINUTE: int = 30       # per-IP send rate
MAX_MESSAGE_LEN: int = 1000           # max message chars
MAX_TITLE_LEN: int = 100              # max title chars
MAX_SOURCE_LEN: int = 50              # max source chars
MAX_WS_PER_IP: int = 5                # max WebSocket connections per IP
MAX_TOTAL_CLIENTS: int = 200          # global cap on connected desktop clients
PUBLIC_MODE: bool = False             # --public flag disables auth


@dataclass(frozen=True)
class AuthContext:
    """Authenticated caller scope.

    ``workspace_id is None`` is the legacy/global scope.  Scoped public-relay
    tokens carry a workspace id and one of three roles:

    * ``workspace``: owner/manage token, may send/read/receive/respond.
    * ``sender``: agent/CLI token, may send notifications and wait approvals.
    * ``receiver``: desktop token, may receive/read/respond but not send.
    """

    role: str = "global"
    workspace_id: str | None = None
    token: str = ""

    @property
    def is_global(self) -> bool:
        return self.workspace_id is None and self.role == "global"

    def can_send(self) -> bool:
        return self.role in {"global", "workspace", "sender"}

    def can_receive(self) -> bool:
        return self.role in {"global", "workspace", "receiver"}

    def can_read_history(self) -> bool:
        return self.role in {"global", "workspace", "receiver"}

    def can_respond_approval(self) -> bool:
        return self.role in {"global", "workspace", "receiver"}

    def can_wait_approval(self) -> bool:
        return self.role in {"global", "workspace", "sender"}

    def can_confirm_approval(self) -> bool:
        """Agent-side permission to acknowledge actual queue resolution."""
        return self.role in {"global", "workspace", "sender"}

# ── Rate Limiter ───────────────────────────────────────────────────────

_rate_buckets: dict[str, list[float]] = defaultdict(list)
_sweep_counter: int = 0
_SWEEP_EVERY: int = 500  # sweep stale IP buckets roughly every N requests


def _sweep_rate_buckets(now: float) -> None:
    """Drop buckets for IPs idle longer than the window, bounding memory."""
    stale = [ip for ip, ts in _rate_buckets.items() if not ts or now - ts[-1] >= 60]
    for ip in stale:
        del _rate_buckets[ip]


def check_rate_limit(ip: str) -> bool:
    """Return True if request is within rate limit, False otherwise."""
    global _sweep_counter
    now = time.time()
    _sweep_counter += 1
    if _sweep_counter >= _SWEEP_EVERY:
        _sweep_counter = 0
        _sweep_rate_buckets(now)
    bucket = _rate_buckets[ip]
    # Prune entries older than 60s
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        return False
    bucket.append(now)
    return True


# ── Models ─────────────────────────────────────────────────────────────

class Notification(BaseModel):
    """Schema for an incoming notification."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    message: str
    title: str = "Agent Notification"
    priority: str = "medium"  # low, medium, high, critical
    source: str = "unknown"
    timestamp: float = Field(default_factory=time.time)
    # Optional context for richer toasts (one-line summary + expandable detail)
    summary: str = ""
    script: str = ""
    cwd: str = ""
    host: str = ""
    agent: str = ""
    approval_id: str = ""
    callback_url: str = ""
    # Compatibility with clients/agents that send approval metadata as a nested object.
    approval: dict[str, Any] = Field(default_factory=dict)
    # Visual classification + interaction detail (propagated to the toast overlay).
    kind: str = ""
    interaction: str = ""  # passive | ack | approval
    require_ack: bool = False
    action: str = ""
    target: str = ""

    @field_validator("message")
    @classmethod
    def truncate_message(cls, v: str) -> str:
        return v[:MAX_MESSAGE_LEN]

    @field_validator("title")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        return v[:MAX_TITLE_LEN]

    @field_validator("source")
    @classmethod
    def truncate_source(cls, v: str) -> str:
        return v[:MAX_SOURCE_LEN]

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        if v not in ("low", "medium", "high", "critical"):
            return "medium"
        return v


class ApprovalResponse(BaseModel):
    """Schema for desktop approval button responses."""

    approval_id: str
    choice: str
    callback_url: str = ""

    @field_validator("choice")
    @classmethod
    def validate_choice(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized in {"accepted", "accept", "approve", "approved", "once"}:
            return "once"
        if normalized in {"denied", "deny", "reject", "rejected"}:
            return "deny"
        if normalized in {"session", "approve_session"}:
            return "session"
        if normalized in {"always", "permanent"}:
            return "always"
        raise ValueError("choice must be accept/deny/session/always")


class ApprovalConfirmation(BaseModel):
    """Agent confirmation that the originating task consumed a decision."""

    approval_id: str
    choice: str

    @field_validator("choice")
    @classmethod
    def validate_choice(cls, v: str) -> str:
        return ApprovalResponse.validate_choice(v)


class WorkspaceCreate(BaseModel):
    """Create a public-relay workspace and scoped token bundle."""

    name: str = "Workspace"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        name = str(v or "").strip()[:80]
        return name or "Workspace"


# ── State ──────────────────────────────────────────────────────────────

TOKEN: str = ""
connected_clients: set[WebSocket] = set()
client_meta: dict[WebSocket, dict[str, Any]] = {}
workspaces: dict[str, dict[str, Any]] = {}
token_index: dict[str, AuthContext] = {}
# Remote senders (agents/CLI jobs) are not persistent WebSocket clients. Keep a
# short last-seen roster for dashboards that want to show "recent senders", but
# never mix them into Connected Devices — otherwise screenshot/test messages look
# like fake online machines.
sender_meta: dict[str, dict[str, Any]] = {}
MAX_SENDERS: int = 50
SENDER_TTL_SECONDS: float = 300.0
history: list[dict[str, Any]] = []
ws_ips: dict[str, int] = defaultdict(int)

# Approval decisions waiting to be collected by a long-polling sender.
#   decisions[approval_id]      -> {"choice": ..., "ts": ...}
#   approval_waiters[approval_id] -> asyncio.Event set when a decision lands
# This lets `anotify approve` work with an *outbound-only* HTTP round-trip (the
# same model `send` uses), so it works from a locked-down remote host where the
# relay cannot reach back into the agent's localhost. The legacy callback_url
# path (relay -> http://127.0.0.1 of a co-located agent) still works too.
import asyncio  # noqa: E402  (kept near the state it powers)

approval_decisions: dict[str, dict[str, Any]] = {}
approval_waiters: dict[str, asyncio.Event] = {}
MAX_APPROVALS: int = 500          # bound the decision store
APPROVAL_WAIT_MAX: float = 300.0  # cap a single long-poll (seconds)


def _record_decision(approval_id: str, choice: str, status: str = "submitted") -> None:
    """Store an approval decision and wake any waiter."""
    if not approval_id:
        return
    approval_decisions[approval_id] = {
        "choice": choice,
        "status": status,
        "ts": time.time(),
    }
    # Bound memory: drop the oldest decisions past the cap.
    if len(approval_decisions) > MAX_APPROVALS:
        oldest = sorted(approval_decisions, key=lambda k: approval_decisions[k]["ts"])
        for k in oldest[: len(approval_decisions) - MAX_APPROVALS]:
            approval_decisions.pop(k, None)
    ev = approval_waiters.get(approval_id)
    if ev is not None:
        ev.set()


# ── Client/sender roster ───────────────────────────────────────────────

def _trim(value: Any, limit: int) -> str:
    """Return a safe short string for roster metadata."""
    return str(value or "").strip()[:limit]


def _sender_key(data: dict[str, Any], client_ip: str) -> str:
    """Stable-ish key for a remote sender shown in Connected Devices."""
    agent = _trim(data.get("agent"), 60).lower()
    source = _trim(data.get("source"), 60).lower()
    host = _trim(data.get("host"), 80).lower()
    base = "|".join(part for part in (agent, source, host, client_ip) if part)
    # Keep the key readable for debugging while avoiding unbounded user data.
    safe = "".join(ch if ch.isalnum() or ch in ".:_-" else "-" for ch in base)
    return f"sender:{safe[:180]}"


def record_sender(data: dict[str, Any], client_ip: str) -> None:
    """Record a one-shot REST sender separately from persistent clients.

    Desktop clients are persistent WebSockets and live in ``client_meta``.
    Hermes/Codex/Claude/HPC jobs usually send one-shot REST notifications; they
    are recent senders, not online devices, and must not be rendered as such.
    """
    key = _sender_key(data, client_ip)
    workspace_id = _trim(data.get("workspace_id"), 80)
    if workspace_id:
        key = f"{workspace_id}:{key}"
    agent = _trim(data.get("agent"), 60)
    source = _trim(data.get("source"), 60)
    host = _trim(data.get("host"), 80)
    name = agent or source or host or client_ip
    platform = f"agent:{agent}" if agent else "remote sender"
    sender_meta[key] = {
        "id": key,
        "name": name,
        "host": host or client_ip,
        "platform": platform,
        "ip": host or client_ip,
        "source": source,
        "agent": agent,
        "last_seen": time.time(),
        "offline": True,
        "workspace_id": workspace_id,
    }
    if len(sender_meta) > MAX_SENDERS:
        oldest = sorted(sender_meta, key=lambda k: sender_meta[k].get("last_seen", 0.0))
        for k in oldest[: len(sender_meta) - MAX_SENDERS]:
            sender_meta.pop(k, None)


def recent_senders(now: float | None = None) -> list[dict[str, Any]]:
    """Return non-expired one-shot senders, newest first."""
    now = time.time() if now is None else now
    expired = [
        key for key, item in sender_meta.items()
        if now - float(item.get("last_seen", 0.0)) > SENDER_TTL_SECONDS
    ]
    for key in expired:
        sender_meta.pop(key, None)
    return sorted(
        sender_meta.values(),
        key=lambda item: float(item.get("last_seen", 0.0)),
        reverse=True,
    )


# ── Auth ───────────────────────────────────────────────────────────────

def _extract_http_token(request: Request) -> str:
    """Extract Bearer token, falling back to the legacy query parameter."""
    auth: str = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token", "")


def _extract_ws_token(websocket: WebSocket) -> str:
    """Extract a WebSocket auth token from header or legacy query parameter."""
    auth: str = websocket.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return websocket.query_params.get("token", "")


def _lookup_scoped_token(token: str) -> AuthContext | None:
    """Return scoped auth context for a workspace token, if known."""
    if not token:
        return None
    # ``dict.get`` is exact-match only.  Avoid leaking timing about whether a
    # token exists by doing constant-time comparison for the rare miss path.
    ctx = token_index.get(token)
    if ctx is not None:
        return ctx
    for stored, stored_ctx in token_index.items():
        if hmac.compare_digest(token, stored):
            return stored_ctx
    return None


def _auth_from_token(token: str, *, require_auth: bool = True) -> AuthContext:
    """Authenticate a global or scoped token.

    Compatibility rules:
    * no global token and no bearer token keeps the old open-dev/public relay
      behavior (global context) when ``require_auth`` is False or ``TOKEN`` is
      unset;
    * a matching ``ANOTIFY_TOKEN`` remains a global admin token;
    * generated workspace/sender/receiver tokens map to workspace contexts.
    """
    if TOKEN and hmac.compare_digest(token, TOKEN):
        return AuthContext(role="global", token=token)
    scoped = _lookup_scoped_token(token)
    if scoped is not None:
        return scoped
    if not TOKEN and not token:
        return AuthContext(role="global")
    if require_auth or TOKEN or token:
        raise HTTPException(status_code=401, detail="Invalid token")
    return AuthContext(role="global")


def require_auth(request: Request) -> AuthContext:
    return _auth_from_token(_extract_http_token(request), require_auth=True)


def verify_token(request: Request) -> None:
    """Legacy FastAPI dependency: accept any valid global/scoped token."""
    require_auth(request)


def get_auth_context(request: Request) -> AuthContext:
    """Return authenticated caller context for scoped authorization checks."""
    return require_auth(request)


def get_ws_auth_context(websocket: WebSocket) -> AuthContext | None:
    """Return WebSocket auth context from header/query token, or ``None``."""
    try:
        ctx = _auth_from_token(_extract_ws_token(websocket), require_auth=True)
    except HTTPException:
        return None
    return ctx if ctx.can_receive() else None


def verify_ws_token(websocket: WebSocket) -> bool:
    """Legacy boolean WebSocket token check used by hardening tests.

    Prefers the ``Authorization: Bearer ...`` header (kept out of URLs and
    proxy logs); falls back to the ``?token=`` query param for older clients.
    """
    return get_ws_auth_context(websocket) is not None


def _forbid(detail: str = "Forbidden") -> None:
    raise HTTPException(status_code=403, detail=detail)


def _workspace_notifications(ctx: AuthContext, limit: int = 50) -> list[dict[str, Any]]:
    """Return notifications visible to an auth context."""
    items = history if ctx.is_global else [
        item for item in history if item.get("workspace_id") == ctx.workspace_id
    ]
    return items[-limit:]


def _approval_workspace_id(approval_id: str) -> str | None:
    """Find the workspace that owns an approval id, if it came via notify."""
    for item in reversed(history):
        if item.get("approval_id") == approval_id:
            workspace_id = item.get("workspace_id")
            return str(workspace_id) if workspace_id else None
    return None


def _token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(24)}"


# ── App ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """FastAPI lifespan — logs startup/shutdown."""
    if TOKEN:
        mode = "PUBLIC + token-protected" if PUBLIC_MODE else "token-protected"
    elif PUBLIC_MODE:
        mode = "PUBLIC (open, no auth)"
    else:
        mode = "AUTH DISABLED (dev only — set ANOTIFY_TOKEN)"
    print(f"[anotify-server] Mode: {mode}")
    print(f"[anotify-server] Rate limit: {RATE_LIMIT_PER_MINUTE}/min per IP")
    print(f"[anotify-server] Max payload: {MAX_PAYLOAD_BYTES} bytes")
    yield
    print("[anotify-server] Shutting down...")


app = FastAPI(title="anotify-server", lifespan=lifespan)


@app.post("/api/workspaces")
async def create_workspace(payload: WorkspaceCreate, request: Request) -> dict[str, Any]:
    """Create an ephemeral workspace with scoped sender/receiver tokens."""
    # Public relay bootstrap: if a global token is configured, workspace creation
    # is an admin operation; otherwise anyone may create an isolated workspace.
    token = _extract_http_token(request)
    if TOKEN and not hmac.compare_digest(token, TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")

    workspace_id = f"ws_{secrets.token_urlsafe(12)}"
    tokens = {
        "workspace": _token("awk"),
        "sender": _token("aks"),
        "receiver": _token("akr"),
    }
    workspace = {
        "id": workspace_id,
        "name": payload.name,
        "created_at": time.time(),
        "tokens": tokens,
    }
    workspaces[workspace_id] = workspace
    for role, token_value in tokens.items():
        token_index[token_value] = AuthContext(
            role=role,
            workspace_id=workspace_id,
            token=token_value,
        )

    # Keep server blank in setup payload so desktop/CLI can keep its current
    # default relay unless the UI fills in window.location.origin.
    return {
        "ok": True,
        "workspace_id": workspace_id,
        "name": payload.name,
        "tokens": tokens,
        "setup": {"server": "", "token": tokens["receiver"]},
        "sender_config": {"server": "", "token": tokens["sender"]},
    }


@app.post("/api/notify")
async def send_notification(
    notif: Notification,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    """Receive a notification from the CLI and broadcast to matching clients."""
    if not ctx.can_send():
        _forbid("token cannot send notifications")
    # Reject oversized payloads (the limit advertised at startup).
    content_length: int = int(request.headers.get("content-length") or 0)
    if content_length > MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    # Rate limit check
    client_ip: str = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    data: dict[str, Any] = notif.model_dump()
    if ctx.workspace_id:
        data["workspace_id"] = ctx.workspace_id
    # Normalize nested approval metadata into the top-level fields used by
    # maintained desktop clients and history/state synchronization.
    approval = data.get("approval") or {}
    if isinstance(approval, dict) and approval:
        data["approval_id"] = (
            data.get("approval_id")
            or approval.get("id")
            or approval.get("approval_id")
            or ""
        )
        data["callback_url"] = data.get("callback_url") or approval.get("callback_url") or ""
        data["action"] = (
            data.get("action")
            or approval.get("command")
            or approval.get("action")
            or ""
        )
        data["target"] = (
            data.get("target")
            or approval.get("description")
            or approval.get("target")
            or ""
        )
        data["kind"] = data.get("kind") or "approval"

    # Store in history
    history.append(data)
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    # Broadcast to all connected WebSocket clients in the same workspace. Keep
    # this as the next frame after a POST so legacy consumers that expect
    # "history -> notification" do not see roster metadata first.
    payload: str = json.dumps(data)
    delivered: int = 0
    disconnected: set[WebSocket] = set()
    for ws in connected_clients:
        meta = client_meta.get(ws, {})
        if ctx.workspace_id and meta.get("workspace_id") != ctx.workspace_id:
            continue
        try:
            await ws.send_text(payload)
            delivered += 1
        except Exception:
            disconnected.add(ws)
    connected_clients.difference_update(disconnected)
    for ws in disconnected:
        client_meta.pop(ws, None)

    # REST senders are usually remote agents/jobs rather than WebSocket peers;
    # record and rebroadcast them so Connected Devices does not look empty.
    record_sender(data, client_ip)
    await broadcast_clients(ctx.workspace_id)

    return {"ok": True, "delivered": delivered}


@app.get("/api/history")
async def get_history(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    """Return recent notifications visible to the caller."""
    if not ctx.can_read_history():
        _forbid("token cannot read history")
    return {"notifications": _workspace_notifications(ctx, limit=50)}


@app.post("/api/approval/respond")
async def respond_approval(
    response: ApprovalResponse,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    """Record a desktop approval decision and deliver it to the agent.

    Delivery happens by whichever path the agent set up:

    * **Long-poll** (default, outbound-only): the decision is recorded here and
      a waiting ``GET /api/approval/wait/{id}`` picks it up. Works from a
      locked-down remote host — no inbound reachability required.
    * **Local callback** (legacy/co-located): if a ``callback_url`` is known
      (passed here or recorded on the original notification), the relay POSTs
      the decision to it. The URL must be loopback, since the relay reaches it
      via its *own* localhost.
    """
    if not ctx.can_respond_approval():
        _forbid("token cannot respond to approvals")
    owner_workspace = _approval_workspace_id(response.approval_id)
    if ctx.workspace_id and owner_workspace != ctx.workspace_id:
        _forbid("approval belongs to another workspace")

    # Always record for a long-polling waiter first — this is the path that
    # works regardless of where the agent lives.
    _record_decision(response.approval_id, response.choice)

    callback_url = response.callback_url
    if not callback_url:
        for item in reversed(history):
            if item.get("approval_id") == response.approval_id:
                callback_url = item.get("callback_url", "")
                break

    # No callback configured: acknowledge only that the relay accepted the
    # decision. The desktop must remain pending until the agent confirms that
    # its real task/queue consumed it via /api/approval/confirm.
    if not callback_url:
        await broadcast_approval_submitted(response.approval_id, response.choice, owner_workspace)
        return {
            "ok": True,
            "choice": response.choice,
            "delivery": "poll",
            "status": "submitted",
        }

    if not (
        callback_url.startswith("http://127.0.0.1:")
        or callback_url.startswith("http://localhost:")
    ):
        raise HTTPException(status_code=400, detail="approval callback must be local")

    payload = {"approval_id": response.approval_id, "choice": response.choice}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            callback_resp = await client.post(callback_url, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"callback failed: {exc}") from exc
    if callback_resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=callback_resp.text[:500])
    _record_decision(response.approval_id, response.choice, status="confirmed")
    await broadcast_approval_resolved(response.approval_id, response.choice, owner_workspace)
    return {
        "ok": True,
        "choice": response.choice,
        "delivery": "callback",
        "status": "confirmed",
    }


@app.post("/api/approval/confirm")
async def confirm_approval(
    confirmation: ApprovalConfirmation,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    """Confirm that the originating agent actually consumed the decision."""
    if not ctx.can_confirm_approval():
        _forbid("token cannot confirm approvals")
    owner_workspace = _approval_workspace_id(confirmation.approval_id)
    if ctx.workspace_id and owner_workspace != ctx.workspace_id:
        _forbid("approval belongs to another workspace")

    existing = approval_decisions.get(confirmation.approval_id)
    if existing and existing.get("choice") != confirmation.choice:
        raise HTTPException(status_code=409, detail="approval choice conflict")
    _record_decision(
        confirmation.approval_id,
        confirmation.choice,
        status="confirmed",
    )
    await broadcast_approval_resolved(
        confirmation.approval_id,
        confirmation.choice,
        owner_workspace,
    )
    return {
        "ok": True,
        "approval_id": confirmation.approval_id,
        "choice": confirmation.choice,
        "status": "confirmed",
    }


@app.get("/api/approval/wait/{approval_id}")
async def wait_approval(
    approval_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Long-poll for an approval decision (outbound-only model for agents).

    Returns ``{"choice": ...}`` as soon as a desktop responds, or HTTP 408 if
    no decision arrives within ``timeout`` seconds (the caller then retries).
    """
    if not ctx.can_wait_approval():
        _forbid("token cannot wait for approvals")
    owner_workspace = _approval_workspace_id(approval_id)
    if ctx.workspace_id and owner_workspace != ctx.workspace_id:
        _forbid("approval belongs to another workspace")

    # Already decided? Return immediately.
    decided = approval_decisions.get(approval_id)
    if decided is not None:
        return {
            "ok": True,
            "choice": decided["choice"],
            "status": decided.get("status", "submitted"),
            "approval_id": approval_id,
        }

    wait_for = max(0.0, min(timeout, APPROVAL_WAIT_MAX))
    ev = approval_waiters.get(approval_id)
    if ev is None:
        ev = asyncio.Event()
        approval_waiters[approval_id] = ev
    try:
        await asyncio.wait_for(ev.wait(), timeout=wait_for)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="approval pending") from None
    finally:
        # Clean the waiter once nobody is blocked on it.
        if ev.is_set():
            approval_waiters.pop(approval_id, None)

    decided = approval_decisions.get(approval_id)
    if decided is None:  # woken without a decision (shouldn't happen) → pending
        raise HTTPException(status_code=408, detail="approval pending")
    return {
        "ok": True,
        "choice": decided["choice"],
        "status": decided.get("status", "submitted"),
        "approval_id": approval_id,
    }


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Health-check endpoint (no auth required)."""
    return {
        "status": "ok",
        "public": PUBLIC_MODE,
        "auth": bool(TOKEN),
        "clients": len(connected_clients),
        "history": len(history),
    }


async def broadcast_clients(workspace_id: str | None = None) -> None:
    """Broadcast online desktop clients plus a separate recent-senders roster."""
    all_clients = list(client_meta.values())
    disconnected: set[WebSocket] = set()
    for ws in list(connected_clients):
        meta = client_meta.get(ws, {})
        target_workspace = meta.get("workspace_id")
        if workspace_id and target_workspace != workspace_id:
            continue
        if target_workspace:
            clients = [item for item in all_clients if item.get("workspace_id") == target_workspace]
            senders = [
                item
                for item in recent_senders()
                if item.get("workspace_id") == target_workspace
            ]
        else:
            clients = all_clients
            senders = recent_senders()
        payload = json.dumps({"type": "clients", "clients": clients, "senders": senders})
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)
    connected_clients.difference_update(disconnected)
    for ws in disconnected:
        client_meta.pop(ws, None)


async def broadcast_approval_resolved(
    approval_id: str,
    choice: str,
    workspace_id: str | None = None,
) -> None:
    """Broadcast an agent-confirmed approval decision to desktop clients."""
    payload = json.dumps({
        "type": "approval-resolved",
        "approval_id": approval_id,
        "choice": choice,
    })
    disconnected: set[WebSocket] = set()
    for ws in connected_clients:
        if workspace_id and client_meta.get(ws, {}).get("workspace_id") != workspace_id:
            continue
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)
    connected_clients.difference_update(disconnected)
    for ws in disconnected:
        client_meta.pop(ws, None)


async def broadcast_approval_submitted(
    approval_id: str,
    choice: str,
    workspace_id: str | None = None,
) -> None:
    """Tell desktop views a decision is in flight, not yet resolved."""
    payload = json.dumps({
        "type": "approval-submitted",
        "approval_id": approval_id,
        "choice": choice,
    })
    disconnected: set[WebSocket] = set()
    for ws in connected_clients:
        if workspace_id and client_meta.get(ws, {}).get("workspace_id") != workspace_id:
            continue
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)
    connected_clients.difference_update(disconnected)
    for ws in disconnected:
        client_meta.pop(ws, None)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for desktop clients.

    Authenticates via ``?token=`` query param (skipped in public mode),
    sends recent history on connect, then keeps the connection alive.
    """
    ctx = get_ws_auth_context(websocket)
    if ctx is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Per-IP WebSocket connection limit
    client_ip: str = websocket.client.host if websocket.client else "unknown"
    if ws_ips[client_ip] >= MAX_WS_PER_IP:
        await websocket.close(code=4029, reason="Too many connections")
        return

    # Global capacity guard
    if len(connected_clients) >= MAX_TOTAL_CLIENTS:
        await websocket.close(code=4029, reason="Server at capacity")
        return

    await websocket.accept()
    connected_clients.add(websocket)
    client_meta[websocket] = {
        "name": client_ip,
        "host": client_ip,
        "platform": "unknown",
        "ip": client_ip,
        "workspace_id": ctx.workspace_id or "",
    }
    ws_ips[client_ip] += 1

    try:
        # Send history on connect
        await websocket.send_text(json.dumps({
            "type": "history",
            "notifications": _workspace_notifications(ctx, limit=20),
        }))

        # Keep alive and accept optional client identity frames.
        while True:
            data: str = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
                continue
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "hello":
                device_id = str(msg.get("id") or msg.get("device_id") or "")[:120]
                name = str(msg.get("name") or client_ip)[:80]
                host = str(msg.get("host") or name)[:80]
                platform = str(msg.get("platform") or "unknown")[:40]
                client_meta[websocket] = {
                    "id": device_id,
                    "name": name,
                    "host": host,
                    "platform": platform,
                    "ip": client_ip,
                    "workspace_id": ctx.workspace_id or "",
                }
                await broadcast_clients(ctx.workspace_id)
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)
        client_meta.pop(websocket, None)
        ws_ips[client_ip] -= 1
        if ws_ips[client_ip] <= 0:
            del ws_ips[client_ip]
        await broadcast_clients(ctx.workspace_id)


# ── CLI entry ──────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for running the server standalone."""
    global TOKEN, PUBLIC_MODE

    parser = argparse.ArgumentParser(description="anotify relay server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=7799, help="Listen port")
    parser.add_argument("--token", default="", help="Auth token (or set ANOTIFY_TOKEN env)")
    parser.add_argument(
        "--token-file", default="",
        help="Read auth token from file (use with systemd EnvironmentFile or chmod 600 file)",
    )
    parser.add_argument(
        "--public", action="store_true", help="Public relay mode (no auth, rate-limited)"
    )
    args: argparse.Namespace = parser.parse_args()

    # Token resolution: --token-file > --token > env
    token_value: str = args.token or os.environ.get("ANOTIFY_TOKEN", "")
    if args.token_file:
        try:
            token_value = Path(args.token_file).read_text(encoding="utf-8").strip()
        except (OSError, FileNotFoundError) as exc:
            print(f"[anotify-server] Cannot read token file: {exc}", file=sys.stderr)
            sys.exit(1)
    TOKEN = token_value
    PUBLIC_MODE = args.public or os.environ.get(
        "ANOTIFY_PUBLIC", ""
    ).lower() in ("1", "true", "yes")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning" if PUBLIC_MODE else "info")


if __name__ == "__main__":
    main()
