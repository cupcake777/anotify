import base64
import io
import re
from pathlib import Path

from PIL import Image

TOAST = Path(__file__).resolve().parents[1] / "desktop" / "src" / "toast.html"
SPRITES = TOAST.parent / "assets" / "sprites"


def _sprites(html: str) -> dict[str, str]:
    match = re.search(r"^const SPRITES=(\{.*\});$", html, re.MULTILINE)
    assert match, "the three official sprite strips must be embedded"
    pattern = r'"(default|request|completed)"\s*:\s*"data:image/png;base64,([^\"]+)"'
    return dict(re.findall(pattern, match.group(1)))


def test_three_official_eight_frame_sprite_strips_are_embedded():
    html = TOAST.read_text()
    sprites = _sprites(html)

    assert set(sprites) == {"default", "request", "completed"}
    for payload in sprites.values():
        image = Image.open(io.BytesIO(base64.b64decode(payload)))
        assert image.size == (1024, 128)
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema() == (0, 255)
        for frame_index in range(8):
            frame = image.crop((frame_index * 128, 0, (frame_index + 1) * 128, 128))
            bbox = frame.getchannel("A").getbbox()
            assert bbox is not None
            assert bbox[2] - bbox[0] >= 112
            assert bbox[3] - bbox[1] >= 112
            assert all(0 <= edge <= 128 for edge in bbox)

    assert "const ICONS" not in html
    assert "const FRAME_COUNT=8" in html
    assert "class Sprite" in html
    assert "class=\"sprite" in html
    assert "requestAnimationFrame" not in html
    assert "class=\"prog" not in html


def test_selected_sprite_mapping_matches_user_choice():
    html = TOAST.read_text()
    sprites = _sprites(html)

    expected = {
        "default": SPRITES / "bird_idle_8f.png",
        "request": SPRITES / "bird_message_8f.png",
        "completed": SPRITES / "bird_complete_8f.png",
    }
    for kind, path in expected.items():
        assert base64.b64decode(sprites[kind]) == path.read_bytes()


def test_per_type_sprite_sizes_and_anchors_match_vision_gate():
    html = TOAST.read_text()

    assert "const SPRITE_SIZES={default:44,request:64,completed:64}" in html
    assert "default:[[1,2],[1,4],[1,4],[1,1],[1,2],[1,2],[1,2],[2,2]]" in html
    assert "request:[[-1,-1],[0,-1],[5,1],[-2,7],[-2,9],[2,9],[-2,9],[5,1]]" in html
    assert "completed:[[2,-1],[3,3],[5,-1],[5,-1],[2,6],[3,6],[5,6],[5,6]]" in html
    assert "this.type=type;this.size=SPRITE_SIZES[type]" in html
    assert "this.el.style.width=`${this.size}px`" in html
    assert "this.el.style.height=`${this.size}px`" in html
    assert "this.el.style.backgroundSize=`${FRAME_COUNT*this.size}px ${this.size}px`" in html
    assert "-${frame*this.size}px 0" in html
    assert "const [x,y]=SPRITE_OFFSETS[this.type][frame]" in html
    assert "translate(calc(-50% + ${x}px),calc(-50% + ${y}px))" in html


def test_sprite_animation_loops_at_a_readable_speed():
    html = TOAST.read_text()

    assert "const FRAME_MS=180" in html
    assert "frame=(frame+1)%FRAME_COUNT" in html
    assert "frame>=FRAME_COUNT" not in html
    assert "this.stop();this.setFrame(0);return" not in html


def test_artwork_fills_a_compact_avatar_frame():
    html = TOAST.read_text()

    assert "grid-template-columns:44px 1fr" in html
    assert ".avatar{align-self:start;position:relative;width:44px;height:44px" in html
    assert ".sprite{position:absolute;left:50%;top:50%;width:52px;height:52px" in html
    assert "transform:translate(-50%,-50%)" in html


def test_no_dynamic_attention_effects_remain():
    html = TOAST.read_text()

    assert "avatar-glow" not in html
    assert "@keyframes glow" not in html
    assert ".toast.attention" not in html
    assert ".toast.crit" not in html
    assert "urgency" not in html


def test_three_type_contract_and_legacy_mapping_are_explicit():
    html = TOAST.read_text()

    assert "const LABELS={default:'Notification',request:'Request',completed:'Completed'}" in html
    assert "toast_type='request'" in html
    assert "toast_type='completed'" in html
    assert "toast_type='silent'" in html
    assert "const SILENT_KIND=new Set(['progress','working','update'])" in html
    assert "TERMINAL_KIND.has(raw)||TERMINAL_STATUS.has(status)" in html
    assert "n.toast_type==='silent'" in html


def test_request_is_sticky_and_other_toasts_are_short_lived():
    html = TOAST.read_text()

    assert "const DURATIONS={default:6000,completed:4000}" in html
    assert "sticky=type==='request'" in html
    assert "dur=sticky?0:DURATIONS[type]" in html
    assert "kind==='request'?587:kind==='completed'?784:660" in html
