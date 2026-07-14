"""Shared test fixtures for anotify."""

from __future__ import annotations

import os
import sys

# Ensure src/ is on path for anotify imports
_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
