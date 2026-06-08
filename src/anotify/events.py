"""Event classification — derive a small visual *kind* from a notification.

This is the single source of truth shared by the menu-bar icon, the desktop
client, and (in future) the pet and custom popups, so every visual surface
reacts to the same canonical states instead of each re-inventing keyword logic.

Kinds intentionally map onto the bundled asset states (``02_new_message``,
``03_approval_required``, ``04_task_complete``, ``06_error``, ``01_default``).
"""

from __future__ import annotations

KIND_ERROR = "error"
KIND_APPROVAL = "approval"
KIND_COMPLETE = "complete"
KIND_MESSAGE = "message"
KIND_INFO = "info"

KINDS: tuple[str, ...] = (KIND_ERROR, KIND_APPROVAL, KIND_COMPLETE, KIND_MESSAGE, KIND_INFO)

# Ordered — earlier wins. Error is checked first so "failed to complete" reads
# as an error rather than a completion.
_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("error", "fail", "failed", "crash", "exception", "traceback"), KIND_ERROR),
    (("approval", "approve", "permission", "confirm", "authorize", "review"), KIND_APPROVAL),
    (("complete", "completed", "done", "success", "succeeded", "finished", "passed"),
     KIND_COMPLETE),
    (("message", "msg", "reply", "new "), KIND_MESSAGE),
)


def classify(
    title: str = "", message: str = "", source: str = "", priority: str = "medium"
) -> str:
    """Return one of :data:`KINDS` for a notification.

    Matches keywords across source/title/message; a ``critical`` priority with
    no clearer signal falls back to the error state.
    """
    text = f"{source} {title} {message}".lower()
    for keywords, kind in _RULES:
        if any(k in text for k in keywords):
            return kind
    if priority == "critical":
        return KIND_ERROR
    return KIND_INFO
