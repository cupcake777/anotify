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
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
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


# ── State ──────────────────────────────────────────────────────────────

TOKEN: str = ""
connected_clients: set[WebSocket] = set()
history: list[dict[str, Any]] = []
ws_ips: dict[str, int] = defaultdict(int)


# ── Auth ───────────────────────────────────────────────────────────────

def verify_token(request: Request) -> None:
    """Verify Bearer token from the Authorization header.

    A configured token is enforced in *every* mode, including ``--public``:
    public mode only removes the auth requirement when no token is set, so a
    public relay can be locked down simply by setting ``ANOTIFY_TOKEN``.
    Raises 401 if a token is configured and the request's token is invalid.
    """
    if not TOKEN:
        return
    auth: str = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token: str = auth[7:]
    else:
        token = request.query_params.get("token", "")
    if not hmac.compare_digest(token, TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")


def verify_ws_token(websocket: WebSocket) -> bool:
    """Verify the token from the Authorization header or query parameter.

    Prefers the ``Authorization: Bearer`` header (kept out of URLs and proxy
    logs); falls back to the ``?token=`` query param for older clients.
    A configured token is enforced in every mode (see :func:`verify_token`).
    Returns True if valid or no token configured.
    """
    if not TOKEN:
        return True
    auth: str = websocket.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token: str = auth[7:]
    else:
        token = websocket.query_params.get("token", "")
    return hmac.compare_digest(token, TOKEN)


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


@app.post("/api/notify")
async def send_notification(
    notif: Notification,
    request: Request,
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """Receive a notification from the CLI and broadcast to all clients."""
    # Reject oversized payloads (the limit advertised at startup).
    content_length: int = int(request.headers.get("content-length") or 0)
    if content_length > MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    # Rate limit check
    client_ip: str = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    data: dict[str, Any] = notif.model_dump()

    # Store in history
    history.append(data)
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    # Broadcast to all connected WebSocket clients
    payload: str = json.dumps(data)
    delivered: int = 0
    disconnected: set[WebSocket] = set()
    for ws in connected_clients:
        try:
            await ws.send_text(payload)
            delivered += 1
        except Exception:
            disconnected.add(ws)
    connected_clients.difference_update(disconnected)

    return {"ok": True, "delivered": delivered}


@app.get("/api/history")
async def get_history(
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """Return recent notifications from the in-memory history."""
    return {"notifications": history[-50:]}


@app.post("/api/approval/respond")
async def respond_approval(
    response: ApprovalResponse,
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """Forward a desktop approval decision to the originating Hermes process."""
    callback_url = response.callback_url
    if not callback_url:
        for item in reversed(history):
            if item.get("approval_id") == response.approval_id:
                callback_url = item.get("callback_url", "")
                break
    if not callback_url:
        raise HTTPException(status_code=404, detail="approval callback not found")
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
    return {"ok": True, "choice": response.choice}


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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for desktop clients.

    Authenticates via ``?token=`` query param (skipped in public mode),
    sends recent history on connect, then keeps the connection alive.
    """
    if not verify_ws_token(websocket):
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
    ws_ips[client_ip] += 1

    try:
        # Send history on connect
        await websocket.send_text(json.dumps({
            "type": "history",
            "notifications": history[-20:],
        }))

        # Keep alive and listen for pings
        while True:
            data: str = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)
        ws_ips[client_ip] -= 1
        if ws_ips[client_ip] <= 0:
            del ws_ips[client_ip]


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
