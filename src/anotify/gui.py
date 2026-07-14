"""GUI components — system tray icon and settings window.

Requires the ``gui`` extra (``pip install anotify[gui]``): ``pystray`` and
``Pillow`` for the tray icon; ``tkinter`` (stdlib) for the settings window.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import ensure_ws_url, load_config, save_config

if TYPE_CHECKING:
    from .client import NotifyClient


def create_tray_icon(client: NotifyClient) -> Any:
    """Create a system-tray icon showing connection status.

    Returns a ``pystray.Icon`` instance (call ``.run()`` in a thread) or
    ``None`` if ``pystray``/``Pillow`` are not installed.
    """
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    _assets = Path(__file__).parent / "assets"
    # Load the mascot once; status is shown as a small corner dot composited
    # over it, so the tray matches the macOS menu-bar bird instead of a bare
    # colored circle. Falls back to a drawn circle if the asset is missing.
    try:
        _bird = Image.open(_assets / "08_tray.png").convert("RGBA")
    except Exception:
        _bird = None

    def _status_color() -> str:
        if client.dnd:
            return "#9ca3af"        # muted gray
        if client.connected:
            return "#22c55e"        # green
        return "#ef4444"            # red

    def make_icon(color: str | None = None) -> Any:
        color = color or _status_color()
        if _bird is not None:
            base = _bird.copy()
            w, h = base.size
            draw = ImageDraw.Draw(base)
            # status dot, bottom-right, with a thin contrasting ring
            r = max(5, w // 6)
            x1, y1 = w - r - 2, h - r - 2
            draw.ellipse([x1 - 1, y1 - 1, w - 1, h - 1], fill="#ffffff")
            draw.ellipse([x1, y1, w - 2, h - 2], fill=color)
            return base
        # Fallback: plain colored disc
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([8, 8, 56, 56], fill=color)
        return img

    def update_icon() -> None:
        icon.icon = make_icon()
        state = "DND" if client.dnd else ("connected" if client.connected else "disconnected")
        icon.title = f"anotify — {state}"

    def on_status(connected: bool) -> None:
        update_icon()

    client.on_status_change(on_status)

    def on_settings(icon: Any, item: Any) -> None:
        open_settings_window(client)

    def on_dnd(icon: Any, item: Any) -> None:
        client.toggle_dnd()
        update_icon()

    def on_quit(icon: Any, item: Any) -> None:
        client.stop()
        icon.stop()

    icon = pystray.Icon(
        "anotify",
        icon=make_icon("#9ca3af"),
        title="anotify — connecting...",
        menu=pystray.Menu(
            pystray.MenuItem(
                "Do Not Disturb", on_dnd, checked=lambda item: client.dnd
            ),
            pystray.MenuItem("Settings", on_settings, default=True),
            pystray.MenuItem("Quit", on_quit),
        ),
    )
    return icon


_settings_lock = threading.Lock()
_settings_open = False


def open_settings_window(client: NotifyClient | None = None) -> None:
    """Open the settings window, on its own UI thread.

    The tray icon's menu callbacks run on the tray's event-loop thread; calling
    ``Tk().mainloop()`` there would block the tray (its status dot could no
    longer update) and hard-crash on macOS, where Cocoa UI must stay on its own
    thread. So we spin the whole window up on a dedicated thread and keep a
    single-instance guard so repeated clicks don't stack windows/roots.
    """
    global _settings_open
    with _settings_lock:
        if _settings_open:
            return
        _settings_open = True

    threading.Thread(
        target=_run_settings_window, args=(client,), daemon=True,
    ).start()


def _run_settings_window(client: NotifyClient | None) -> None:
    """Build and run the tkinter settings window (own thread, own root)."""
    global _settings_open
    try:
        try:
            import tkinter as tk
            from tkinter import messagebox, ttk
        except Exception:
            # No Tk on this Python build (common on minimal/Homebrew installs).
            # Fall back to opening the JSON config in the default editor so the
            # user can still change settings, and don't crash the tray.
            _open_config_in_editor()
            return

        win = tk.Tk()
        win.title("anotify Settings")
        win.geometry("440x340")
        win.resizable(False, False)

        cfg: dict[str, Any] = load_config()

        style = ttk.Style()
        style.configure("TLabel", padding=4)
        style.configure("TEntry", padding=4)

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)

        # Server
        ttk.Label(frame, text="Server URL:").grid(row=0, column=0, sticky="w")
        server_var = tk.StringVar(value=cfg.get("server", ""))
        ttk.Entry(frame, textvariable=server_var, width=40).grid(row=0, column=1, sticky="ew")

        # Token
        ttk.Label(frame, text="Token:").grid(row=1, column=0, sticky="w")
        token_var = tk.StringVar(value=cfg.get("token", ""))
        ttk.Entry(frame, textvariable=token_var, width=40, show="*").grid(
            row=1, column=1, sticky="ew"
        )

        # Auto-start
        autostart_var = tk.BooleanVar(value=cfg.get("autostart", False))
        ttk.Checkbutton(frame, text="Start on login", variable=autostart_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        # Do Not Disturb (live — reflects/controls the running client)
        dnd_var = tk.BooleanVar(value=bool(client and client.dnd))

        def on_dnd_toggle() -> None:
            if client:
                client.set_dnd(dnd_var.get())

        dnd_cb = ttk.Checkbutton(
            frame, text="Do Not Disturb", variable=dnd_var, command=on_dnd_toggle
        )
        dnd_cb.grid(row=3, column=0, columnspan=2, sticky="w")
        if client is None:
            dnd_cb.state(["disabled"])

        # Status
        connected = bool(client and client.connected)
        status_label = ttk.Label(
            frame,
            text=f"Status: {'Connected' if connected else 'Disconnected'}",
            foreground="green" if connected else "red",
        )
        status_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=(16, 0), sticky="ew")

        def on_save() -> None:
            existing = load_config()  # preserve keys we don't manage (muted_sources)
            existing.update({
                "server": server_var.get().strip(),
                "token": token_var.get().strip(),
                "autostart": autostart_var.get(),
            })
            save_config(existing)
            _set_autostart(bool(existing["autostart"]))
            if client:
                # Apply immediately and force a reconnect so the new server/
                # token take effect now instead of at the next dropout. Token
                # is set verbatim (clearing it is allowed).
                if existing["server"]:
                    client.server_url = ensure_ws_url(existing["server"])
                client.token = existing["token"]
                client.reconnect()
            messagebox.showinfo("anotify", "Settings saved.", parent=win)

        def on_test() -> None:
            # Shells out to the OS notifier (multi-second timeout) — run off the
            # UI thread so the window doesn't freeze.
            def _fire() -> None:
                from .notify_backend import notify
                notify("anotify Test", "Notification is working!", "medium")
            threading.Thread(target=_fire, daemon=True).start()

        ttk.Button(btn_frame, text="Save", command=on_save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="Test Notification", command=on_test).pack(side="left")
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right")

        frame.columnconfigure(1, weight=1)

        # Keep the live Status label fresh while the window is open.
        def _tick() -> None:
            if client:
                up = client.connected
                status_label.config(
                    text=f"Status: {'Connected' if up else 'Disconnected'}",
                    foreground="green" if up else "red",
                )
                dnd_var.set(client.dnd)
            win.after(1000, _tick)

        win.after(1000, _tick)
        win.mainloop()
    finally:
        with _settings_lock:
            _settings_open = False


def _open_config_in_editor() -> None:
    """Open ``~/.anotify.json`` in the OS default editor (Tk-less fallback)."""
    from .config import CONFIG_PATH
    if not CONFIG_PATH.exists():
        save_config(load_config())
    path = str(CONFIG_PATH)
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-t", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _set_autostart(enabled: bool) -> None:
    """Add or remove anotify-client from OS auto-start.

    Supports Windows (Startup folder), macOS (LaunchAgent), and Linux
    (.desktop autostart).
    """
    system: str = platform.system()

    if system == "Windows":
        startup_dir = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        shortcut = startup_dir / "anotify.bat"
        if enabled:
            shortcut.write_text(f'@echo off\n"{sys.executable}" -m anotify.client --no-tray\n')
        else:
            shortcut.unlink(missing_ok=True)

    elif system == "Darwin":
        plist_dir = Path.home() / "Library/LaunchAgents"
        plist = plist_dir / "com.anotify.client.plist"
        if enabled:
            plist.write_text(
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                f'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                f'<plist version="1.0">\n'
                f"<dict>\n"
                f"    <key>Label</key><string>com.anotify.client</string>\n"
                f"    <key>ProgramArguments</key>\n"
                f"    <array><string>{sys.executable}</string>"
                f"<string>-m</string><string>anotify.client</string>"
                f"<string>--no-tray</string></array>\n"
                f"    <key>RunAtLoad</key><true/>\n"
                f"    <key>KeepAlive</key><true/>\n"
                f"</dict>\n"
                f"</plist>"
            )
            subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
        else:
            if plist.exists():
                subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
                plist.unlink(missing_ok=True)

    elif system == "Linux":
        desktop_dir = Path.home() / ".config/autostart"
        desktop = desktop_dir / "anotify.desktop"
        if enabled:
            desktop_dir.mkdir(parents=True, exist_ok=True)
            desktop.write_text(
                f"[Desktop Entry]\n"
                f"Type=Application\n"
                f"Name=anotify\n"
                f"Exec={sys.executable} -m anotify.client --no-tray\n"
                f"Hidden=false\n"
                f"X-GNOME-Autostart-enabled=true\n"
            )
        else:
            desktop.unlink(missing_ok=True)


def main() -> None:
    """Entry point for the ``anotify-gui`` command."""
    import argparse

    parser = argparse.ArgumentParser(description="anotify settings GUI")
    parser.parse_args()
    # Standalone: there's no tray to block, and tkinter wants the main thread,
    # so build the window here directly (open_settings_window spawns a thread,
    # which is only right when called from the tray's own event loop).
    global _settings_open
    _settings_open = True
    _run_settings_window(None)
