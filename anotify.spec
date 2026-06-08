# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for anotify Windows exe."""

a = Analysis(
    ['src/anotify/client.py'],
    pathex=[],
    binaries=[],
    hiddenimports=['websockets', 'httpx'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='anotify',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep console for log visibility
    disable_windowed_traceback=False,
    icon=None,
)
