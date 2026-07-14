"""Cross-platform system notification backend.

Supports three platforms:
- **Windows 10/11**: Toast notifications via PowerShell
- **macOS**: ``osascript`` display notification
- **Linux**: ``notify-send`` (freedesktop)

Falls back to printing to stderr if no native backend is available.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys


def notify(title: str, message: str, priority: str = "medium") -> bool:
    """Show a native system notification.

    Args:
        title: Notification title text.
        message: Notification body text.
        priority: One of ``low``, ``medium``, ``high``, ``critical``.

    Returns:
        ``True`` if the notification was shown via a native backend.
    """
    system: str = platform.system()
    try:
        if system == "Windows":
            return _windows_toast(title, message)
        elif system == "Darwin":
            return _macos_notify(title, message)
        elif system == "Linux":
            return _linux_notify(title, message, priority)
    except Exception:
        pass
    # Fallback
    print(f"[anotify] {title}: {message}", file=sys.stderr)
    return False


def play_sound(priority: str = "medium") -> None:
    """Play an alert sound for high-priority notifications.

    Only fires for ``high`` or ``critical`` priority.  Uses the platform
    default sound system (``winsound``, ``afplay``, ``paplay``).
    """
    if priority not in ("high", "critical"):
        return
    system: str = platform.system()
    try:
        if system == "Windows":
            import winsound

            winsound.MessageBeep(  # type: ignore[attr-defined]
                winsound.MB_ICONEXCLAMATION  # type: ignore[attr-defined]
            )
        elif system == "Darwin":
            subprocess.run(
                ["afplay", "/System/Library/Sounds/Glass.aiff"],
                capture_output=True, timeout=5,
            )
        elif system == "Linux":
            subprocess.run(
                ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


def _windows_toast(title: str, message: str) -> bool:
    """Show a Windows 10/11 toast notification via PowerShell.

    The title/message are passed as environment variables and referenced
    inside the script as ``$env:...``.  PowerShell does not re-parse
    environment-variable *values* for ``$(...)`` subexpression or ``$var``
    expansion, so notification content cannot inject PowerShell code — even
    when it originates from an untrusted relay.
    """
    ps: str = (
        '[Windows.UI.Notifications.ToastNotificationManager, '
        'Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n'
        '$t = [Windows.UI.Notifications.ToastNotificationManager]::'
        'GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n'
        '$n = $t.GetElementsByTagName("text")\n'
        '$n[0].AppendChild($t.CreateTextNode($env:ANOTIFY_TITLE)) | Out-Null\n'
        '$n[1].AppendChild($t.CreateTextNode($env:ANOTIFY_MESSAGE)) | Out-Null\n'
        '$toast = [Windows.UI.Notifications.ToastNotification]::new($t)\n'
        '[Windows.UI.Notifications.ToastNotificationManager]::'
        'CreateToastNotifier("anotify").Show($toast)'
    )
    env: dict[str, str] = {**os.environ, "ANOTIFY_TITLE": title, "ANOTIFY_MESSAGE": message}
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-WindowStyle", "Hidden", "-Command", ps],
        capture_output=True, timeout=10, env=env,
    )
    return True


def _macos_notify(title: str, message: str) -> bool:
    """Show a macOS notification via ``osascript``.

    Title/message are passed as ``argv`` to the AppleScript rather than
    interpolated into the script source, so the content cannot break out of
    the string literal or inject AppleScript (``do shell script`` etc.).
    """
    script: str = (
        "on run argv\n"
        "    display notification (item 1 of argv) with title (item 2 of argv)\n"
        "end run"
    )
    subprocess.run(
        ["osascript", "-e", script, message, title],
        capture_output=True, timeout=5,
    )
    return True


def _linux_notify(title: str, message: str, priority: str = "medium") -> bool:
    """Show a Linux notification via ``notify-send``.

    ``--`` stops option parsing so a title/message beginning with ``-`` is
    treated as text, not a flag.  Priority is mapped to freedesktop urgency.
    """
    urgency: str = "critical" if priority in ("high", "critical") else "normal"
    subprocess.run(
        ["notify-send", "-u", urgency, "--", title, message],
        capture_output=True, timeout=5,
    )
    return True
