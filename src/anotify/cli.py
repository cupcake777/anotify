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
    cmd_send(args)


def main() -> None:
    """Entry point for the ``anotify`` CLI command."""
    parser = argparse.ArgumentParser(
        prog="anotify",
        description="Send notifications from remote hosts to desktop clients",
    )
    parser.add_argument("--server", help="Server URL (overrides config)")
    parser.add_argument("--token", help="Auth token (overrides config)")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")

    # send
    p_send = sub.add_parser("send", help="Send a notification")
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

    # config
    p_cfg = sub.add_parser("config", help="Save configuration")
    p_cfg.add_argument("--server", help="Server URL")
    p_cfg.add_argument("--token", help="Auth token")

    # test
    sub.add_parser("test", help="Send a test notification")

    args: argparse.Namespace = parser.parse_args()

    if args.command == "config":
        cmd_config(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
