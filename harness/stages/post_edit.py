"""Post-edit stage — format if source files have uncommitted changes (Claude Code hook)."""

from __future__ import annotations

from harness.git import changed_py_files
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format


def cmd_post_edit() -> None:
    """Format if source files have uncommitted changes (Claude Code hook)."""
    if not changed_py_files():
        return
    cmd_fix(no_exit=True)
    cmd_format(no_exit=True)
