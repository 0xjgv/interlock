"""Crash boundary + redacted local capture for interlocks-internal bugs.

The boundary lives in :mod:`interlocks.crash.boundary` and is the single place
where interlocks classifies uncaught exceptions into:

- ``SystemExit`` / ``KeyboardInterrupt`` / ``GeneratorExit`` — re-raised.
- :class:`InterlockUserError` — printed and exits 2; never captured.
- Anything else originating in ``interlocks/`` — captured, then re-raised so
  Python emits the canonical traceback and exits 1.

Do NOT install ``sys.excepthook``. Do NOT add ``try/except Exception`` around
full-task dispatch. The boundary is a single context-manager wired in
``interlocks/cli.py``.
"""

from __future__ import annotations

from interlocks.config import InterlockUserError
from interlocks.crash.boundary import CrashBoundary

__all__ = ["CrashBoundary", "InterlockUserError"]
