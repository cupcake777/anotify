"""macOS native menu bar app — pure rumps, no tkinter.

Uses ``rumps`` (Cocoa NSStatusBar) — zero external GUI deps, no crash.
Architecture:

    Menu Bar Icon (pixel art bird)
    ├── ● Connected / ○ Disconnected
    ├── Server: your-server.example
    ├── ──────────────────
    ├── 🧪 Test Notification
    ├── ⚙ Edit Settings...
    ├── ──────────────────
    ├── ❓ About anotify
    └── 🚪 Quit

The WebSocket client runs in a background asyncio thread.
Provides the ``anotify-mac`` command.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import rumps

from .client import NotifyClient
from .config import get_token, load_config
from .events import KIND_APPROVAL, KIND_COMPLETE, KIND_ERROR, KIND_MESSAGE, classify
from .notify_backend import notify as send_notification

logger = logging.getLogger("anotify.mac")

# ═══════════════════════════════════════════════════════════════════════════
# Assets
# ═══════════════════════════════════════════════════════════════════════════

ASSETS_DIR = Path(__file__).parent / "assets"
TRAY_ICON = "08_tray.png"


def _asset_path(name: str) -> str:
    """Return absolute path to a bundled asset."""
    local = ASSETS_DIR / name
    if local.is_file():
        return str(local)
    try:
        from importlib import resources
        ref = resources.files("anotify").joinpath("assets").joinpath(name)
        if hasattr(ref, "is_file") and ref.is_file():
            return str(ref)
    except Exception:
        pass
    return str(local)


# ═══════════════════════════════════════════════════════════════════════════
# Menu Bar App
# ═══════════════════════════════════════════════════════════════════════════

class AnotifyMacApp(rumps.App):
    """macOS menu bar application.

    Left-click or right-click the bird icon to see the menu.
    Everything is in the menu — no separate windows.
    """

    def __init__(self) -> None:
        icon_path = _asset_path(TRAY_ICON)
        super().__init__(
            name="anotify",
            title="",             # icon only, no text
            icon=icon_path,
            quit_button=None,     # we handle quit
        )
        self._running = True

        # WebSocket client
        cfg = load_config()
        self.client = NotifyClient(
            server_url=cfg.get("server", ""),
            token=cfg.get("token", ""),
        )
        self.client.on_status_change(self._on_status_change)
        self.client.on_notification(self._on_notification)

        # Dynamic icon state
        self._default_icon = icon_path
        self._silence_icon = _asset_path("05_silence_mode.png")  # shown while DND on
        self._state_icons: dict[str, str] = {
            "02_new_message": _asset_path("02_new_message.png"),
            "03_approval_required": _asset_path("03_approval_required.png"),
            "04_task_complete": _asset_path("04_task_complete.png"),
            "06_error": _asset_path("06_error.png"),
        }
        self._icon_revert_timer: Any = None

        # Server label
        server_host = self.client.server_url.replace("wss://", "").replace("ws://", "").rstrip("/")

        # ── Menu ──
        self._status_item = rumps.MenuItem("○ Connecting...")
        self._server_item = rumps.MenuItem(f"Server: {server_host}")
        self._sep1 = rumps.separator
        self._dnd_item = rumps.MenuItem("🔕 Do Not Disturb", callback=self._toggle_dnd)
        self._test_item = rumps.MenuItem("🧪 Test Notification", callback=self._test_notify)
        self._settings_item = rumps.MenuItem("⚙ Edit Settings...", callback=self._edit_settings)
        self._sep2 = rumps.separator
        self._about_item = rumps.MenuItem("❓ About anotify", callback=self._show_about)
        self._quit_item = rumps.MenuItem("🚪 Quit", callback=self.quit_app)

        self.menu = [
            self._status_item,
            self._server_item,
            self._sep1,
            self._dnd_item,
            self._test_item,
            self._settings_item,
            self._sep2,
            self._about_item,
            self._quit_item,
        ]

        self._start_client()
        rumps.Timer(self._refresh_status, 2).start()
        logger.info("anotify menu bar app ready 🐦")

    # ── Client lifecycle ────────────────────────────────────────────────

    def _start_client(self) -> None:
        """Run the asyncio WebSocket client in a daemon thread."""
        def _run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.client.run())
            except Exception as exc:
                if self._running:
                    logger.error("Client loop error: %s", exc)

        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()

    # ── Menu callbacks ──────────────────────────────────────────────────

    def _toggle_dnd(self, sender: Any) -> None:
        """Toggle Do-Not-Disturb; reflect it in the menu + menu-bar icon."""
        on = self.client.toggle_dnd()
        sender.state = 1 if on else 0
        # The bird "puts on headphones": swap to the silence-mode art while DND.
        if self._icon_revert_timer:
            with contextlib.suppress(Exception):
                self._icon_revert_timer.stop()
            self._icon_revert_timer = None
        self.icon = self._silence_icon if on else self._default_icon

    def _test_notify(self, _: Any) -> None:
        """Send a test notification.

        Prefers a real end-to-end round-trip through the configured relay (the
        most useful test — it exercises auth + WebSocket delivery and the popup
        arrives via the normal path). Only if no server/token is configured, or
        the round-trip fails, do we fall back to a direct local popup — so a
        working setup shows the toast *once*, not twice.
        """
        try:
            import httpx

            from .cli import _http_url
            from .config import ensure_ws_url, get_server

            token = get_token()
            base = _http_url(ensure_ws_url(get_server())).rstrip("/")
            if base.endswith("/ws"):
                base = base[:-3]
            # No usable relay target → just show a local popup.
            if not base or "your-server.example" in base:
                raise RuntimeError("no relay configured")

            # Uses httpx (already a dependency) so the token is never exposed on
            # the process argv the way `curl ... -H "Authorization: ..."` would.
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            with httpx.Client(timeout=6) as http:
                resp = http.post(
                    f"{base}/api/notify",
                    json={
                        "title": "🐦 anotify Test",
                        "message": "Round-trip from your Mac menu bar app!",
                        "priority": "medium",
                        "source": "anotify-mac",
                    },
                    headers=headers,
                )
            resp.raise_for_status()
            return  # popup will arrive over the WebSocket — don't double-fire
        except Exception:
            send_notification(
                "🧪 anotify Test", "Local notification is working on macOS! 🐦", "medium"
            )

    def _edit_settings(self, _: Any) -> None:
        """Open the config file in the default text editor."""
        config_path = os.path.expanduser("~/.anotify.json")
        cfg = load_config()
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=2)
        subprocess.Popen(["open", "-t", config_path])

    def _show_about(self, _: Any) -> None:
        """Show About dialog.

        Uses rumps.Timer (runs on main thread) with one-shot stop.
        threading.Timer would run on background thread → Cocoa crash.
        Direct rumps.alert() would deadlock while NSMenu is open.
        """
        def _fire(timer: Any) -> None:
            timer.stop()
            rumps.alert(
                title="🐦 anotify v0.3.0",
                message="Tiny messages. Big heart.\n\n"
                        "Cross-platform remote notification system.\n"
                        "Menu bar app — click the bird for options.\n\n"
                        "github.com/cupcake777/anotify",
                ok="💙 Cool!",
            )

        rumps.Timer(_fire, 0.15).start()

    def quit_app(self, _: Any) -> None:
        """Graceful shutdown."""
        self._running = False
        self.client.stop()
        rumps.quit_application()

    # ── Dynamic icon ────────────────────────────────────────────────────

    # Canonical event kind (from anotify.events.classify) → bundled asset.
    _KIND_ICONS: dict[str, str] = {
        KIND_ERROR: "06_error",
        KIND_APPROVAL: "03_approval_required",
        KIND_COMPLETE: "04_task_complete",
        KIND_MESSAGE: "02_new_message",
    }

    def _on_notification(self, data: dict[str, Any]) -> None:
        """Called from WebSocket thread when a notification arrives.

        Schedules icon change on main thread via rumps.Timer.
        """
        # If this notification is silenced (muted source / DND), don't let the
        # menu-bar icon react either — keep the current (silence) look.
        if not self.client._should_alert(data):
            return

        kind = data.get("kind") or classify(
            data.get("title", ""), data.get("message", ""),
            data.get("source", ""), data.get("priority", "medium"),
        )
        name = self._KIND_ICONS.get(kind)
        if name and name in self._state_icons:
            self._pending_icon = self._state_icons[name]
            # Schedule on main thread — rumps.Timer runs on Cocoa run loop
            rumps.Timer(self._do_change_icon, 0.05).start()

    def _do_change_icon(self, timer: Any) -> None:
        """Set icon to the pending state icon, schedule revert."""
        timer.stop()
        icon = getattr(self, "_pending_icon", None)
        if icon:
            self.icon = icon
        # Cancel previous revert timer
        if self._icon_revert_timer:
            with contextlib.suppress(Exception):
                self._icon_revert_timer.stop()
        # Schedule revert after 4 seconds
        self._icon_revert_timer = rumps.Timer(self._revert_icon, 4)
        self._icon_revert_timer.start()

    def _revert_icon(self, timer: Any) -> None:
        """Revert menu bar icon to default (or the silence icon while DND)."""
        timer.stop()
        self.icon = self._silence_icon if self.client.dnd else self._default_icon
        self._icon_revert_timer = None

    # ── Status updates ──────────────────────────────────────────────────

    def _on_status_change(self, connected: bool) -> None:
        pass  # _refresh_status picks it up on timer

    def _refresh_status(self, _: Any = None) -> None:
        """Update the status menu item."""
        if not self._running:
            return
        connected = self.client.connected
        self._status_item.title = "● Connected" if connected else "○ Disconnected"


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Entry point for ``anotify-mac`` command."""
    if platform.system() != "Darwin":
        print("anotify-mac requires macOS.", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(message)s",
    )

    AnotifyMacApp().run()


if __name__ == "__main__":
    main()
