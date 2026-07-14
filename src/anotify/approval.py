"""Approval handling for the desktop client.

When a notification carries an ``approval_id``, the user can Accept/Deny it and
the decision is POSTed back to the relay's ``/api/approval/respond`` — which
delivers it to the waiting agent (``anotify approve``).

The default prompt is interactive and best-effort across platforms:

* **macOS** — ``osascript`` ``display dialog`` with Approve/Deny buttons.
* **Linux** — ``notify-send`` with actions (where the notification daemon
  supports them), falling back to a tkinter dialog.
* **Windows / other** — a small tkinter dialog.

If no interactive surface is available (headless, no tkinter), the approval is
logged and left for another client (e.g. the desktop app) to resolve.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Any

from .cli import _http_url
from .config import ensure_ws_url, get_server, get_token

logger = logging.getLogger("anotify.approval")


def respond(approval_id: str, choice: str, callback_url: str = "") -> bool:
    """POST an approval decision to the relay. Returns True on success."""
    if not approval_id:
        return False
    import httpx

    base = _http_url(ensure_ws_url(get_server())).rstrip("/")
    if base.endswith("/ws"):
        base = base[:-3]
    headers: dict[str, str] = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body: dict[str, Any] = {"approval_id": approval_id, "choice": choice}
    if callback_url:
        body["callback_url"] = callback_url
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(f"{base}/api/approval/respond", json=body, headers=headers)
        if resp.status_code == 200:
            logger.info("Approval %s → %s", approval_id, choice)
            return True
        logger.warning("Approval response rejected: %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Approval response failed: %s", exc)
    return False


def prompt(data: dict[str, Any]) -> None:
    """Ask the user to Accept/Deny an approval, then post the decision.

    Runs the platform dialog and, on a definite choice, calls :func:`respond`.
    A dismissed/closed dialog is treated as "no decision" — left for another
    client to resolve, so closing a window never silently denies.
    """
    approval_id = data.get("approval_id", "")
    if not approval_id:
        return
    title = data.get("title") or "Approval required"
    message = data.get("message") or ""
    detail = message
    if data.get("action"):
        detail = f"{message}\n\nAction: {data['action']}"
    if data.get("target"):
        detail += f"\nTarget: {data['target']}"

    choice = _ask(title, detail)
    if choice in ("once", "deny"):
        respond(approval_id, choice, data.get("callback_url", ""))


def _ask(title: str, message: str) -> str:
    """Return 'once', 'deny', or '' (no decision) via the best available UI."""
    system = platform.system()
    if system == "Darwin":
        return _ask_macos(title, message)
    if system == "Linux":
        result = _ask_tk(title, message)  # most reliable interactive surface
        return result
    return _ask_tk(title, message)


def _ask_macos(title: str, message: str) -> str:
    """macOS approve/deny dialog via osascript (content passed as argv)."""
    script = (
        "on run argv\n"
        '    set theTitle to item 1 of argv\n'
        '    set theMsg to item 2 of argv\n'
        '    try\n'
        '        set r to display dialog theMsg with title theTitle '
        'buttons {"Deny", "Approve"} default button "Approve" with icon note\n'
        '        return button returned of r\n'
        '    on error number -128\n'
        '        return "cancel"\n'
        '    end try\n'
        "end run"
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script, title, message],
            capture_output=True, text=True, timeout=300,
        )
        answer = (out.stdout or "").strip().lower()
    except Exception:  # noqa: BLE001
        return ""
    if answer == "approve":
        return "once"
    if answer == "deny":
        return "deny"
    return ""


def _ask_tk(title: str, message: str) -> str:
    """Cross-platform fallback dialog using tkinter (if available)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:  # noqa: BLE001
        logger.info("No interactive surface for approval %r; leaving for another client", title)
        return ""
    try:
        root = tk.Tk()
        root.withdraw()
        # Yes = Approve, No = Deny, Cancel/close = no decision
        ans = messagebox.askyesnocancel(title, message)
        root.destroy()
    except Exception:  # noqa: BLE001
        return ""
    if ans is True:
        return "once"
    if ans is False:
        return "deny"
    return ""
