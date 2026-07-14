import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "desktop" / "src" / "index.html"
CAPABILITY = ROOT / "desktop" / "src-tauri" / "capabilities" / "default.json"
MAIN_RS = ROOT / "desktop" / "src-tauri" / "src" / "main.rs"
TAURI_CONFIG = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
README = ROOT / "README.md"


def test_window_controls_have_distinct_accessible_actions():
    html = DASHBOARD.read_text()

    assert 'id="minBtn" title="Minimize window" aria-label="Minimize window"' in html
    assert 'id="hideBtn" title="Hide window to tray" aria-label="Hide window"' in html
    assert (
        'id="closeBtn" title="Close window — anotify keeps running in the tray" '
        'aria-label="Close window"'
        in html
    )
    assert "appWindow?.minimize?.()" in html
    assert "appWindow?.hide?.()" in html
    assert "appWindow?.close?.()" in html


def test_close_uses_tauri_permission_and_keeps_tray_process_alive():
    permissions = json.loads(CAPABILITY.read_text())["permissions"]
    rust = MAIN_RS.read_text()

    assert "core:window:allow-close" in permissions
    assert "WindowEvent::CloseRequested" in rust
    assert "api.prevent_close()" in rust
    assert "main.hide()" in rust


def test_ambient_effects_are_subtle_and_motion_safe():
    html = DASHBOARD.read_text()

    assert "@keyframes glowWarm" in html
    assert "@keyframes glowCool" in html
    assert "@keyframes sheenDrift" in html
    assert "backdrop-filter:blur(22px) saturate(1.12)" in html
    assert "@media (prefers-reduced-motion:reduce)" in html
    assert (
        "body::before,body::after,.app::before,.bird img,.dot.ok,.detail-chevron,"
        ".saved{animation:none;transition:none}"
        in html
    )


def test_main_window_uses_real_transparent_rounded_corners():
    html = DASHBOARD.read_text()
    config = json.loads(TAURI_CONFIG.read_text())
    main_window = config["app"]["windows"][0]

    assert config["app"]["macOSPrivateApi"] is True
    assert main_window["label"] == "main"
    assert main_window["decorations"] is False
    assert main_window["transparent"] is True
    assert main_window["shadow"] is False
    assert "html{min-height:100%;overflow:hidden;background:transparent}" in html
    assert "body{min-height:100%;display:flex" in html
    assert "overflow:hidden;border-radius:30px;clip-path:inset(0 round 30px)" in html


def test_readme_hero_uses_approved_app_icon():
    readme = README.read_text()

    assert 'src="desktop/src/assets/brand/07_app_icon.png"' in readme
    assert "assets/banner.png" not in readme
