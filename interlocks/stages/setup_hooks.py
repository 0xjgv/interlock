"""Setup-hooks stage — writes git pre-commit + Claude Code Stop hooks."""

from __future__ import annotations

import time
from pathlib import Path

from interlocks import ui
from interlocks.config import load_optional_config
from interlocks.hook_setup import install_hooks


def cmd_hooks() -> None:
    start = time.monotonic()
    ui.command_banner("setup-hooks", load_optional_config())
    ui.section("Setup Hooks")
    try:
        install_hooks(Path())
    finally:
        ui.stage_footer(time.monotonic() - start)
