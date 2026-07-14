import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOAST = ROOT / "desktop" / "src" / "toast.html"
FONT_DIR = TOAST.parent / "assets" / "fonts"


def _style(path: Path) -> str:
    match = re.search(r"<style>(.*?)</style>", path.read_text(), re.DOTALL)
    assert match
    return match.group(1)


def test_bundled_nerd_font_assets_are_web_optimized_and_licensed():
    for name in ("jbm-nerd-regular.woff2", "jbm-nerd-bold.woff2"):
        payload = (FONT_DIR / name).read_bytes()
        assert payload[:4] == b"wOF2"
        assert len(payload) < 1_500_000

    license_text = (FONT_DIR / "OFL.txt").read_text()
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text


def test_toast_uses_bundled_nerd_font_for_ui_chrome():
    css = _style(TOAST)
    assert "url('assets/fonts/jbm-nerd-regular.woff2') format('woff2')" in css
    assert "url('assets/fonts/jbm-nerd-bold.woff2') format('woff2')" in css
    assert "--font-nerd:'anotify Nerd Font','JetBrainsMono Nerd Font','JetBrainsMono NF'" in css
    assert "--font-ui:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif" in css
    nerd_selectors = (
        ".title,.event-tag,.source-mark,.agent,.host,.time,.ctx,.act,.resolved,.hint"
        "{font-family:var(--font-nerd)}"
    )
    assert nerd_selectors in css
    assert ".summary{margin-top:4px;font-family:var(--font-ui)" in css
    full_prefix = (
        ".full{margin:0 0 10px;padding:8px 9px;border-radius:8px;"
        "background:rgba(255,255,255,.55);font-family:var(--font-ui)"
    )
    assert full_prefix in css
    assert ".ttf" not in css
