"""Workarounds for gshock_api quirks.

The library subscribes to every notify characteristic on connect. The watch can
send an unsolicited packet (e.g. WATCH_NAME) before we issue the matching
request, and the IO handler then raises ``RuntimeError("...result is not set")``
inside the D-Bus callback. Ignore those packets instead of crashing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from gshock_api import message_dispatcher

_original_on_received = message_dispatcher.MessageDispatcher.on_received


def _safe_on_received(data: bytes, protocol: Any = None) -> None:
    try:
        _original_on_received(data, protocol)
    except RuntimeError:
        # No request is waiting for this notification; drop it.
        return


def install() -> None:
    message_dispatcher.MessageDispatcher.on_received = staticmethod(_safe_on_received)


def configure_logging() -> Path:
    """Send library logs to a file instead of stderr (which corrupts the TUI)."""
    state_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "casio-watch"
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "casio.log"

    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return log_path
