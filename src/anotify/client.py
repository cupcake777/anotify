"""WebSocket client — connects to anotify-server, shows desktop notifications.

Provides the ``anotify-client`` command and the :class:`NotifyClient` class
with automatic reconnection and exponential backoff.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import sys
import threading
from collections import OrderedDict
from typing import Any, Callable

from .config import ensure_ws_url, get_server, get_token, load_config, save_config
from .events import classify
from .notify_backend import notify, play_sound

logger: logging.Logger = logging.getLogger("anotify")


class NotifyClient:
    """WebSocket client with auto-reconnect and exponential backoff.

    Args:
        server_url: Relay server URL.  Falls back to config/env/default.
        token: Authentication token.
    """

    def __init__(self, server_url: str = "", token: str = "") -> None:
        self.server_url: str = ensure_ws_url(server_url or get_server())
        self.token: str = token or get_token()
        self._running: bool = True
        self._connected: bool = False
        self._reconnect_delay: float = 1.0
        # Set once run() starts; lets other threads (e.g. the settings window)
        # poke the asyncio loop to force an immediate reconnect.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any | None = None
        self._on_status_change: Callable[[bool], None] | None = None
        self._on_notification: Callable[[dict[str, Any]], None] | None = None
        # Optional override for the approve/deny prompt (e.g. a GUI). When None,
        # the default interactive dialog in anotify.approval is used.
        self._on_approval: Callable[[dict[str, Any]], None] | None = None
        # Dedup: ids of notifications already surfaced, as a bounded LRU set so
        # reconnect replays and accidental rebroadcasts don't double-popup.
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._max_seen: int = 500
        # Whether we've taken our first history snapshot. The first snapshot is
        # treated as a baseline (recorded, not shown); later snapshots after a
        # reconnect surface anything genuinely missed while offline.
        self._seeded: bool = False
        # Quiet controls (gate *alerting*, never the event stream / dedup):
        #   dnd            — suppress popups+sound; critical can break through
        #   muted_sources  — per-source absolute mute (even critical stays quiet)
        #   sources        — sources seen this session, for a self-populating UI
        self.dnd: bool = False
        self.critical_breaks_dnd: bool = True
        self.muted_sources: set[str] = set(load_config().get("muted_sources", []))
        self.sources: set[str] = set()

    @property
    def connected(self) -> bool:
        """Whether the client is currently connected to the server."""
        return self._connected

    def on_status_change(self, callback: Callable[[bool], None]) -> None:
        """Register a callback invoked when connection status changes."""
        self._on_status_change = callback

    def on_notification(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback invoked when a notification is received.

        Called with the raw notification dict: {id, title, message, priority,
        source}.  Fires for both live and replayed (missed) notifications, so
        a GUI/pet can build a full inbox from this single stream.
        Runs synchronously in the WebSocket receive loop — keep it fast.
        """
        self._on_notification = callback

    def on_approval(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a handler for approval notifications.

        Called (on a background thread) with the notification dict for any
        notification whose ``kind`` is ``approval``. The handler is responsible
        for asking the user and posting the decision (see
        :func:`anotify.approval.respond`). If unset, a default interactive
        dialog is used.
        """
        self._on_approval = callback

    # ── Quiet controls ──────────────────────────────────────────────────

    def set_dnd(self, enabled: bool) -> None:
        """Enable/disable Do-Not-Disturb (suppresses popups + sound)."""
        self.dnd = enabled
        logger.info("Do Not Disturb %s", "on" if enabled else "off")

    def toggle_dnd(self) -> bool:
        """Flip DND and return the new state."""
        self.set_dnd(not self.dnd)
        return self.dnd

    def mute_source(self, source: str) -> None:
        """Mute a source permanently (persisted to the config file)."""
        self.muted_sources.add(source)
        self._persist_muted()

    def unmute_source(self, source: str) -> None:
        """Unmute a previously muted source (persisted)."""
        self.muted_sources.discard(source)
        self._persist_muted()

    def toggle_source(self, source: str) -> bool:
        """Flip mute state for a source; return True if now muted."""
        if source in self.muted_sources:
            self.unmute_source(source)
            return False
        self.mute_source(source)
        return True

    def _persist_muted(self) -> None:
        """Write muted_sources back to the config file, preserving other keys."""
        cfg = load_config()
        cfg["muted_sources"] = sorted(self.muted_sources)
        save_config(cfg)

    def _should_alert(self, data: dict[str, Any]) -> bool:
        """Whether to actually popup + sound for this notification.

        A muted source is absolute (even ``critical`` stays quiet); DND is a
        softer "I'm busy now" gate that ``critical`` can break through.
        """
        if (data.get("source") or "") in self.muted_sources:
            return False
        if self.dnd:
            return self.critical_breaks_dnd and data.get("priority") == "critical"
        return True

    def stop(self) -> None:
        """Signal the client to stop reconnecting."""
        self._running = False

    def reconnect(self) -> None:
        """Drop the current connection so the run loop reconnects at once.

        Safe to call from any thread (e.g. the settings window after the
        server/token changed). Closing the live socket makes ``run()`` fall
        straight through to a fresh ``_connect_loop`` using the new
        ``server_url``/``token`` instead of waiting for the next failure.
        """
        loop, ws = self._loop, self._ws
        if loop is None or ws is None:
            return
        self._reconnect_delay = 1.0

        def _close() -> None:
            import asyncio as _asyncio
            with contextlib.suppress(Exception):
                _asyncio.ensure_future(ws.close())

        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(_close)

    async def run(self) -> None:
        """Main loop — connect, receive, and auto-reconnect on failure."""
        self._loop = asyncio.get_event_loop()
        while self._running:
            try:
                await self._connect_loop()
            except Exception as e:
                self._set_connected(False)
                if self._running:
                    base: float = min(self._reconnect_delay, 30)
                    # Full jitter (0.5x–1.5x) so many clients don't reconnect
                    # in lockstep after a server restart.
                    delay: float = base * (0.5 + random.random())
                    logger.info("Connection lost (%s), retrying in %.1fs...", e, delay)
                    await asyncio.sleep(delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    async def _connect_loop(self) -> None:
        """Connect to the server and process incoming messages."""
        import websockets

        url: str = self.server_url
        kwargs: dict[str, Any] = {"ping_interval": 20, "ping_timeout": 10}

        if self.token:
            header = ("Authorization", f"Bearer {self.token}")
            # websockets renamed extra_headers -> additional_headers in v14;
            # try the modern name, then the legacy name.
            for key in ("additional_headers", "extra_headers"):
                attempt: dict[str, Any] = {**kwargs, key: [header]}
                try:
                    async with websockets.connect(url, **attempt) as ws:
                        await self._consume(ws)
                    return
                except TypeError:
                    continue

        async with websockets.connect(url, **kwargs) as ws:
            await self._consume(ws)

    async def _consume(self, ws: Any) -> None:
        """Mark connected and process the incoming message stream."""
        self._ws = ws
        self._set_connected(True)
        self._reconnect_delay = 1.0
        logger.info("Connected to %s", self.server_url)

        try:
            async for raw in ws:
                if not self._running:
                    break
                try:
                    data: dict[str, Any] = json.loads(raw)
                    self._handle_message(data)
                except json.JSONDecodeError:
                    continue
        finally:
            self._ws = None

    def _set_connected(self, connected: bool) -> None:
        """Update connection state and notify callback."""
        self._connected = connected
        if self._on_status_change:
            self._on_status_change(connected)

    def _handle_message(self, data: dict[str, Any]) -> None:
        """Process an incoming message: a live notification or a history frame."""
        if data.get("type") == "history":
            self._handle_history(data.get("notifications", []))
            return

        # Live notification — dedup so a rebroadcast can't double-popup.
        if not self._mark_seen(self._notif_id(data)):
            return

        src = data.get("source")
        if src and src != "unknown":
            self.sources.add(src)
        self._annotate_kind(data)

        title, message, priority = self._display_fields(data)
        logger.info("%s: %s - %s", priority.upper(), title, message)

        # Fire on_notification callback first (fast, dynamic-UI hook). The event
        # always flows through, even when muted/DND — only the popup is gated.
        if self._on_notification:
            self._on_notification(data)
        if self._should_alert(data):
            self._dispatch_native(title, message, priority)
            # Approvals need a decision — ask the user (off the event loop, the
            # prompt blocks) and post the result back to the relay.
            if data.get("kind") == "approval" and data.get("approval_id"):
                self._dispatch_approval(data)

    def _dispatch_approval(self, data: dict[str, Any]) -> None:
        """Run the approve/deny prompt off the asyncio loop (it blocks)."""
        handler = self._on_approval or self._default_approval
        threading.Thread(target=handler, args=(data,), daemon=True).start()

    @staticmethod
    def _default_approval(data: dict[str, Any]) -> None:
        """Default approval prompt — interactive dialog, posts the decision."""
        try:
            from .approval import prompt
            prompt(data)
        except Exception:  # noqa: BLE001
            logger.exception("Approval prompt failed")

    def _handle_history(self, notifications: list[dict[str, Any]]) -> None:
        """Handle a history snapshot sent by the server on (re)connect.

        First snapshot after startup = baseline: record the ids but don't pop
        up (you just launched the client; you don't want a wall of old toasts).
        Later snapshots (after a reconnect) surface anything not seen yet —
        these are notifications that arrived while you were offline/asleep,
        subject to DND / muted-source quiet controls.
        """
        for n in notifications:
            src = n.get("source")
            if src and src != "unknown":
                self.sources.add(src)
            self._annotate_kind(n)

        missed: list[dict[str, Any]] = [
            n for n in notifications if self._mark_seen(self._notif_id(n))
        ]

        # The event stream always carries every missed item (for a GUI/pet).
        if self._on_notification:
            for n in missed:
                self._on_notification(n)

        if not self._seeded:
            self._seeded = True
            logger.info("Seeded %d history item(s) as baseline (not shown)", len(missed))
            return

        # Only items that pass the quiet controls produce a popup.
        alertable: list[dict[str, Any]] = [n for n in missed if self._should_alert(n)]
        if not alertable:
            return

        logger.info("Replaying %d missed notification(s)", len(alertable))
        if len(alertable) == 1:
            title, message, priority = self._display_fields(alertable[0])
            self._dispatch_native(title, message, priority)
        else:
            # Collapse a backlog into one popup instead of spamming N toasts.
            latest = alertable[-1]
            priority = "high" if any(
                n.get("priority") in ("high", "critical") for n in alertable
            ) else "medium"
            summary = f"Latest: {latest.get('title') or ''} {latest.get('message') or ''}".strip()
            self._dispatch_native(
                f"anotify — {len(alertable)} missed notifications", summary[:200], priority
            )

    @staticmethod
    def _annotate_kind(data: dict[str, Any]) -> None:
        """Tag a notification with its canonical visual ``kind`` (in place).

        Surfaces (menu-bar icon, pet, custom popups) read ``data["kind"]``
        instead of re-deriving it, so they all react consistently.
        """
        data["kind"] = classify(
            data.get("title", ""), data.get("message", ""),
            data.get("source", ""), data.get("priority", "medium"),
        )

    @staticmethod
    def _notif_id(data: dict[str, Any]) -> str:
        """Stable id for dedup. Falls back to content when no server id."""
        nid = data.get("id")
        if nid:
            return str(nid)
        return f"{data.get('timestamp')}|{data.get('title')}|{data.get('message')}"

    def _mark_seen(self, nid: str) -> bool:
        """Record an id as seen; return True if it was new (not seen before)."""
        if nid in self._seen_ids:
            return False
        self._seen_ids[nid] = None
        if len(self._seen_ids) > self._max_seen:
            self._seen_ids.popitem(last=False)  # evict oldest
        return True

    @staticmethod
    def _display_fields(data: dict[str, Any]) -> tuple[str, str, str]:
        """Build (title, message, priority) for display, prefixing the source."""
        title: str = data.get("title", "Agent Notification")
        message: str = data.get("message", "")
        priority: str = data.get("priority", "medium")
        source: str = data.get("source", "unknown")
        if source and source != "unknown":
            title = f"[{source}] {title}"
        return title, message, priority

    def _dispatch_native(self, title: str, message: str, priority: str) -> None:
        """Show the OS notification off the event loop.

        notify()/play_sound() shell out to PowerShell/osascript/paplay with
        multi-second timeouts; running them inline would block the asyncio
        receive loop (stalling pings and other messages), so use a daemon
        thread and keep the socket responsive.
        """
        threading.Thread(
            target=self._show_native,
            args=(title, message, priority),
            daemon=True,
        ).start()

    @staticmethod
    def _show_native(title: str, message: str, priority: str) -> None:
        """Show the OS notification and play sound (runs off the event loop)."""
        notify(title, message, priority)
        play_sound(priority)


def _hide_console() -> None:
    """Hide the console window on Windows (silent background mode).

    When running as ``pythonw.exe`` or with ``--silent``, this hides the
    console window so the client runs invisibly in the background.
    """
    import platform
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        ctypes.windll.user32.ShowWindow(  # type: ignore[attr-defined]
            ctypes.windll.kernel32.GetConsoleWindow(),  # type: ignore[attr-defined]
            0,  # SW_HIDE
        )
    except Exception:
        pass


def main() -> None:
    """Entry point for the ``anotify-client`` command."""
    import argparse

    parser = argparse.ArgumentParser(description="anotify desktop client")
    parser.add_argument("--server", "-s", help="Server URL")
    parser.add_argument("--token", "-t", help="Auth token")
    parser.add_argument("--no-tray", action="store_true", help="Run without tray icon")
    parser.add_argument("--silent", action="store_true",
                        help="Run silently (hide console on Windows)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args: argparse.Namespace = parser.parse_args()

    # Hide console in silent mode (default on Windows when no TTY)
    if args.silent or (not sys.stdout.isatty()):
        _hide_console()

    # Log to file in silent mode, console otherwise
    if args.silent or not sys.stdout.isatty():
        log_file = os.path.join(os.path.expanduser("~"), ".anotify.log")
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s [%(name)s] %(message)s",
            filename=log_file,
            filemode="a",
        )
    else:
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="[%(name)s] %(message)s",
        )

    client: NotifyClient = NotifyClient(
        server_url=args.server or "",
        token=args.token or "",
    )

    # Tray icon (optional)
    tray_icon: Any = None
    if not args.no_tray:
        try:
            from .gui import create_tray_icon
            tray_icon = create_tray_icon(client)
            if tray_icon:
                import threading
                threading.Thread(target=tray_icon.run, daemon=True).start()
        except ImportError:
            logger.info("pystray not installed, running without tray icon")

    logger.info("Connecting to %s...", client.server_url)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        client.stop()
        if tray_icon:
            tray_icon.stop()
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
