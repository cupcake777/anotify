"""CLI for sending notifications from remote hosts (HPC, VPS, etc.).

Provides the ``anotify`` command with subcommands: ``send``, ``config``, and
``test``.  Communicates with the relay server over HTTP POST.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from typing import Any

from .config import CONFIG_PATH, ensure_ws_url, get_server, get_token, load_config, save_config


def _http_url(ws_url: str) -> str:
    """Convert a WebSocket URL back to an HTTP URL for REST API calls."""
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[6:]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[5:]
    return ws_url


def _detect_source() -> str:
    """Auto-detect a short source identifier from the local hostname."""
    hostname: str = socket.gethostname().lower()
    if "hpc" in hostname or "login" in hostname:
        return "hpc"
    return socket.gethostname()


def cmd_config(args: argparse.Namespace) -> None:
    """Save server/token configuration to ``~/.anotify.json``."""
    cfg: dict[str, Any] = load_config()
    if args.server:
        cfg["server"] = args.server
    if args.token:
        cfg["token"] = args.token
    save_config(cfg)
    print(f"Config saved to {CONFIG_PATH}")
    print(f"  server: {cfg.get('server', '(not set)')}")
    print(f"  token: {'***' if cfg.get('token') else '(not set)'}")


def cmd_send(args: argparse.Namespace) -> None:
    """Send a notification to the relay server via HTTP POST."""
    import httpx

    server: str = args.server or get_server()
    token: str = args.token or get_token()

    # Convert to HTTP for REST API
    http_base: str = _http_url(ensure_ws_url(server)).rstrip("/")
    if http_base.endswith("/ws"):
        http_base = http_base[:-3]

    cwd: str = args.cwd if args.cwd is not None else os.getcwd()
    host: str = args.host or socket.gethostname()
    script: str = args.script or ""
    # One-line toast summary: explicit wins, else "script · dirname" when a
    # script is given; otherwise left empty so the client falls back to the
    # first line of the message.
    summary: str = args.summary or (
        f"{script} · {os.path.basename(cwd.rstrip('/'))}" if script else ""
    )

    payload: dict[str, Any] = {
        "message": args.message,
        "title": args.title or "Agent Notification",
        "priority": args.priority,
        "source": args.source or _detect_source(),
        "timestamp": time.time(),
        "host": host,
        "cwd": cwd,
    }
    for key, val in (("summary", summary), ("script", script), ("agent", args.agent or "")):
        if val:
            payload[key] = val

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(f"{http_base}/api/notify", json=payload, headers=headers)
            if resp.status_code == 200:
                result: dict[str, Any] = resp.json()
                n: int = result.get("delivered", 0)
                if args.verbose:
                    print(f"Delivered to {n} client(s)")
            elif resp.status_code == 401:
                print("Auth failed. Check token.", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"Server error: {resp.status_code}", file=sys.stderr)
                sys.exit(1)
    except httpx.ConnectError:
        print(f"Cannot connect to {http_base}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_test(args: argparse.Namespace) -> None:
    """Send a test notification with default values."""
    args.message = "Test notification from anotify"
    args.title = "Test"
    args.priority = "medium"
    args.source = _detect_source()
    args.verbose = True
    # cmd_send also reads these optional fields; the `test` subcommand doesn't
    # define them, so default them here to avoid AttributeError.
    for field in ("summary", "script", "cwd", "host", "agent"):
        if not hasattr(args, field):
            setattr(args, field, None)
    cmd_send(args)


# Map an approval decision to a process exit code so shell callers can branch:
#   0 = approved (once/session/always), 1 = denied, 2 = timeout/error.
_APPROVE_EXIT = {"once": 0, "session": 0, "always": 0, "deny": 1}


def cmd_approve(args: argparse.Namespace) -> None:
    """Request approval from the desktop and block until the user decides.

    Outbound-only: POSTs an approval notification, then long-polls the relay
    for the decision. Works from a locked-down remote host (no inbound
    reachability needed). Prints the decision and exits 0 (approved) / 1
    (denied) / 2 (timeout or error) so scripts can gate on it::

        if anotify approve "Deploy to prod?"; then ./deploy.sh; fi
    """
    import uuid

    import httpx

    server: str = args.server or get_server()
    token: str = args.token or get_token()
    http_base: str = _http_url(ensure_ws_url(server)).rstrip("/")
    if http_base.endswith("/ws"):
        http_base = http_base[:-3]

    approval_id: str = uuid.uuid4().hex
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"} if token else {}

    payload: dict[str, Any] = {
        "message": args.message,
        "title": args.title or "Approval required",
        "priority": "high",
        "source": args.source or _detect_source(),
        "timestamp": time.time(),
        "host": args.host or socket.gethostname(),
        "approval_id": approval_id,
        "kind": "approval",
    }
    for key, val in (
        ("agent", args.agent or ""),
        ("action", getattr(args, "action", "") or ""),
        ("target", getattr(args, "target", "") or ""),
        ("callback_url", getattr(args, "callback", "") or ""),
    ):
        if val:
            payload[key] = val

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(f"{http_base}/api/notify", json=payload, headers=headers)
            if resp.status_code == 401:
                print("Auth failed. Check token.", file=sys.stderr)
                sys.exit(2)
            if resp.status_code != 200:
                print(f"Server error: {resp.status_code}", file=sys.stderr)
                sys.exit(2)
            if args.verbose:
                print(f"Approval requested (id={approval_id}); waiting for a decision...")

            # Long-poll until decided or the overall timeout elapses.
            deadline = time.time() + max(1.0, args.timeout)
            choice: str = ""
            while time.time() < deadline:
                remaining = max(1.0, min(60.0, deadline - time.time()))
                try:
                    w = client.get(
                        f"{http_base}/api/approval/wait/{approval_id}",
                        params={"timeout": remaining},
                        headers=headers,
                        timeout=remaining + 10,
                    )
                except httpx.ReadTimeout:
                    continue
                if w.status_code == 200:
                    choice = w.json().get("choice", "")
                    break
                if w.status_code == 408:
                    continue  # still pending → poll again
                print(f"Server error: {w.status_code}", file=sys.stderr)
                sys.exit(2)
    except httpx.ConnectError:
        print(f"Cannot connect to {http_base}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if not choice:
        print("timeout", file=sys.stderr)
        sys.exit(2)
    print(choice)
    sys.exit(_APPROVE_EXIT.get(choice, 2))


def main() -> None:
    """Entry point for the ``anotify`` CLI command."""
    # Global flags live on a parent parser so they're accepted *before or after*
    # the subcommand — `anotify --server X send "m"` and
    # `anotify send "m" --server X` both work (the README uses both styles).
    # argparse.SUPPRESS keeps an *unused* occurrence from overwriting the other
    # with None when the same dest appears on both parsers.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server", help="Server URL (overrides config)",
                        default=argparse.SUPPRESS)
    common.add_argument("--token", help="Auth token (overrides config)",
                        default=argparse.SUPPRESS)
    common.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        prog="anotify",
        description="Send notifications from remote hosts to desktop clients",
        parents=[common],
    )

    sub = parser.add_subparsers(dest="command")

    # send
    p_send = sub.add_parser("send", help="Send a notification", parents=[common])
    p_send.add_argument("message", help="Notification message")
    p_send.add_argument("--title", "-t", help="Notification title")
    p_send.add_argument(
        "--priority", "-p", default="medium",
        choices=["low", "medium", "high", "critical"],
    )
    p_send.add_argument("--source", "-s", help="Source identifier (default: auto-detect)")
    p_send.add_argument("--summary", help="One-line toast summary (default: derived)")
    p_send.add_argument("--script", help="Script/command name shown on the toast")
    p_send.add_argument("--cwd", help="Working directory (default: current dir)")
    p_send.add_argument("--host", help="Host name (default: hostname)")
    p_send.add_argument("--agent", help="Agent name (e.g. claude-code, codex)")

    # config (its own --server/--token are the values to *save*, so no parent)
    p_cfg = sub.add_parser("config", help="Save configuration")
    p_cfg.add_argument("--server", help="Server URL")
    p_cfg.add_argument("--token", help="Auth token")

    # approve — request a yes/no decision and block until the desktop responds
    p_app = sub.add_parser(
        "approve",
        help="Request approval from the desktop and wait for the decision",
        parents=[common],
    )
    p_app.add_argument("message", help="What you're asking the user to approve")
    p_app.add_argument("--title", "-t", help="Approval title")
    p_app.add_argument("--source", "-s", help="Source identifier (default: auto-detect)")
    p_app.add_argument("--agent", help="Agent name (e.g. claude-code, codex)")
    p_app.add_argument("--action", help="Action being requested (shown in details)")
    p_app.add_argument("--target", help="Target of the action (e.g. a path)")
    p_app.add_argument("--host", help="Host name (default: hostname)")
    p_app.add_argument(
        "--timeout", type=float, default=300.0,
        help="Max seconds to wait for a decision (default: 300)",
    )
    p_app.add_argument(
        "--callback",
        help="Optional local callback URL (http://127.0.0.1:PORT/...) for the "
             "co-located-relay model; default uses outbound long-poll",
    )

    # test
    sub.add_parser("test", help="Send a test notification", parents=[common])

    args: argparse.Namespace = parser.parse_args()
    # Fill in any global flags the user didn't supply (SUPPRESS leaves them off
    # the namespace entirely) so downstream code can always read them.
    for name, default in (("server", None), ("token", None), ("verbose", False)):
        if not hasattr(args, name):
            setattr(args, name, default)

    if args.command == "config":
        cmd_config(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "approve":
        cmd_approve(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
