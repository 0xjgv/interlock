"""Print the installed interlocks version.

Utility command — not a gate. ``task_version`` returns ``None`` to keep the
Task-vs-command distinction honest; ``cmd_version`` prints ``__version__``
straight to stdout.
"""

from __future__ import annotations

from interlocks import __version__


def task_version() -> None:
    return None


def cmd_version() -> None:
    print(__version__)
