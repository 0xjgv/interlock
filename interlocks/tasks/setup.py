"""Unified local setup command for interlocks integrations."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import find_project_root, load_optional_config
from interlocks.hook_setup import install_hooks
from interlocks.runner import fail_skip
from interlocks.setup_state import SetupArtifactStatus, setup_artifact_statuses
from interlocks.tasks.agents import install_agent_docs
from interlocks.tasks.setup_skill import install_skill

if TYPE_CHECKING:
    from pathlib import Path


def cmd_setup() -> None:
    start = time.monotonic()
    check_only = _parse_check_flag()
    project_root = find_project_root()

    ui.command_banner("setup", load_optional_config())
    if check_only:
        _cmd_setup_check(project_root)
    else:
        _cmd_setup_install(project_root)
    ui.command_footer(start)


def _parse_check_flag() -> bool:
    args = [arg for arg in sys.argv[2:] if arg not in {"--quiet", "--verbose"}]
    if not args:
        return False
    if args == ["--check"]:
        return True
    fail_skip("usage: interlocks setup [--check]")


def _cmd_setup_install(project_root: Path) -> None:
    ui.section("Setup")
    install_hooks(project_root)
    install_agent_docs(project_root)
    install_skill(project_root)

    ui.section("Status")
    _render_status(setup_artifact_statuses(project_root))

    ui.section("Next Steps")
    ui.message_list([
        "Run `interlocks doctor` to inspect full project readiness.",
        "Run `interlocks check` after edits.",
    ])


def _cmd_setup_check(project_root: Path) -> None:
    ui.section("Setup Check")
    statuses = setup_artifact_statuses(project_root)
    _render_status(statuses)
    if all(status.installed for status in statuses):
        ui.section("Next Steps")
        ui.message_list(["Local integrations are installed and current."])
        return
    ui.section("Next Steps")
    ui.message_list(["Run `interlocks setup` to install or refresh local integrations."])
    sys.exit(1)


def _render_status(statuses: list[SetupArtifactStatus]) -> None:
    for status in statuses:
        state: ui.State = "ok" if status.installed else "fail"
        ui.row(
            status.label,
            status.target,
            "installed" if status.installed else "missing/stale",
            state=state,
        )
