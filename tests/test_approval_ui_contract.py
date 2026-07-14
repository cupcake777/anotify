from pathlib import Path

TOAST = Path(__file__).resolve().parents[1] / "desktop" / "src" / "toast.html"


def test_approval_payloads_map_to_request_and_keep_choices():
    html = TOAST.read_text()

    approval_id_mapping = (
        "n.approval_id=String(n.approval_id||approval.id||approval.approval_id||'').trim()"
    )
    assert approval_id_mapping in html
    assert "n.action=n.action||approval.command||approval.action||''" in html
    assert "n.target=n.target||approval.description||approval.target||''" in html
    assert "raw==='approval'" in html
    assert "LABELS={default:'Notification',request:'Request',completed:'Completed'}" in html
    assert '>Accept</button>' in html
    assert '>Deny</button>' in html


def test_request_actions_are_hidden_until_expanded():
    html = TOAST.read_text()

    assert ".actionbar{grid-column:1/-1;display:none" in html
    assert ".toast.open .actionbar{display:flex}" in html
    assert "other.classList.remove('open')" in html


def test_request_response_uses_native_bridge_and_waits_for_resolution():
    html = TOAST.read_text()

    assert "respond_approval" in html
    assert "approvalId:n.approval_id" in html
    assert "callbackUrl:n.callback_url||null" in html
    assert "showApprovalSubmitted(el)" in html
    assert "showApprovalResolved(p.approval_id,p.choice)" in html
    assert "Waiting for agent confirmation" in html
    assert "Not submitted:" in html


def test_notification_rendering_escapes_untrusted_text():
    html = TOAST.read_text()

    assert "function esc(v)" in html
    assert "${esc(n.title||'Agent notification')}" in html
    assert "${esc(summary)}" in html
    assert "<pre class=\"full\">${esc(full)}</pre>" in html
    assert "${esc(source.agent)}" in html


def test_request_bypasses_dnd_but_default_and_completed_do_not():
    html = TOAST.read_text()

    assert "if(dndState&&n.toast_type!=='request')return" in html


def test_duplicate_events_are_suppressed_before_rendering():
    html = TOAST.read_text()

    assert "recentToasts=new Map()" in html
    assert "function seenToast(n)" in html
    assert "n.toast_type==='silent'||seenToast(n)" in html
