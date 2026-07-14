"""Build anotify Windows exe with PyInstaller.

Creates a single-file executable at ``dist/anotify.exe`` that bundles
the desktop client — no Python installation required on the target machine.

Usage::

    python build_exe.py
"""

from __future__ import annotations

import subprocess
import sys


def main() -> None:
    """Install PyInstaller and build the exe."""
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        check=True,
    )

    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--name", "anotify",
            "--hidden-import", "websockets",
            "--hidden-import", "httpx",
            "src/anotify/client.py",
        ],
        check=True,
    )

    print("\nBuild complete: dist/anotify.exe")


if __name__ == "__main__":
    main()
