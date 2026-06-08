"""GUI components — system tray icon and settings window.

Requires the ``gui`` extra (``pip install anotify[gui]``): ``pystray`` and
``Pillow`` for the tray icon; ``tkinter`` (stdlib) for the settings window.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
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

    def make_icon(color: str = "#22c55e") -> Any:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill=color)
        return img

    def update_icon() -> None:
        # muted gray while DND, else green/red by connection state
        if client.dnd:
            color = "#9ca3af"
        elif client.connected:
            color = "#22c55e"
        else:
            color = "#ef4444"
        icon.icon = make_icon(color)
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
        icon=make_icon(),
        title="anotify — connecting...",
        menu=pystray.Menu(
            pystray.MenuItem(
                "Do Not Disturb", on_dnd, checked=lambda item: client.dnd
            ),
            pystray.MenuItem("Settings", on_settings),
            pystray.MenuItem("Quit", on_quit),
        ),
    )
    return icon


def open_settings_window(client: NotifyClient | None = None) -> None:
    """Open a tkinter window for editing anotify settings."""
    win = tk.Tk()
    win.title("anotify Settings")
    win.geometry("420x320")
    win.resizable(False, False)

    cfg: dict[str, Any] = load_config()

    # Style
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
    ttk.Entry(frame, textvariable=token_var, width=40, show="*").grid(row=1, column=1, sticky="ew")

    # Auto-start
    autostart_var = tk.BooleanVar(value=cfg.get("autostart", False))
    ttk.Checkbutton(frame, text="Start on login", variable=autostart_var).grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(8, 0)
    )

    # Status
    status_text = "Connected" if (client and client.connected) else "Disconnected"
    status_label = ttk.Label(
        frame,
        text=f"Status: {status_text}",
        foreground="green" if (client and client.connected) else "red",
    )
    status_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

    # Buttons
    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=4, column=0, columnspan=2, pady=(16, 0), sticky="ew")

    def on_save() -> None:
        new_cfg: dict[str, Any] = {
            "server": server_var.get().strip(),
            "token": token_var.get().strip(),
            "autostart": autostart_var.get(),
        }
        save_config(new_cfg)
        _set_autostart(bool(new_cfg["autostart"]))
        if client:
            if new_cfg["server"]:
                client.server_url = ensure_ws_url(new_cfg["server"])
            client.token = new_cfg["token"] or client.token
        messagebox.showinfo("anotify", "Settings saved!")

    def on_test() -> None:
        from .notify_backend import notify
        notify("anotify Test", "Notification is working!", "medium")

    ttk.Button(btn_frame, text="Save", command=on_save).pack(side="left", padx=(0, 8))
    ttk.Button(btn_frame, text="Test Notification", command=on_test).pack(side="left")
    ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right")

    frame.columnconfigure(1, weight=1)
    win.mainloop()


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
    open_settings_window()
