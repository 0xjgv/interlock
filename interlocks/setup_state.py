"""Shared detectors for local setup artifacts (hooks, CI workflow, acceptance scaffold).

Pure helpers — no UI, no side effects, stdlib-only. Imported by both
``interlocks.stages.setup_hooks`` (the writer) and ``interlocks.tasks.doctor`` (the reader),
so detection and installation stay in lockstep.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from interlocks.config import InterlockConfig


CI_ACTION_NEEDLES: tuple[str, ...] = ("0xjgv/interlocks@", "interlocks/interlocks@")
"""GitHub Actions references that wire ``interlocks`` into a workflow."""

_CI_LOCAL_NEEDLE = "interlocks ci"
_CI_WORKFLOW_NEEDLES: tuple[str, ...] = (_CI_LOCAL_NEEDLE, *CI_ACTION_NEEDLES)


def iter_workflow_bodies(project_root: Path) -> list[str]:
    """Read every ``.github/workflows/*.y*ml`` file body. Empty list when dir is absent."""
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    bodies: list[str] = []
    for path in sorted(workflows_dir.iterdir()):
        if path.suffix not in (".yml", ".yaml"):
            continue
        try:
            bodies.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return bodies


def is_post_edit_command(command: object) -> bool:
    """True when ``command`` is a recognizable ``interlocks post-edit`` invocation."""
    return isinstance(command, str) and (
        command.endswith("interlocks.cli post-edit") or command == "uv run interlocks post-edit"
    )


def pre_commit_hook_installed(project_root: Path) -> bool:
    """True when ``.git/hooks/pre-commit`` exists and invokes ``interlocks pre-commit``."""
    hook = project_root / ".git" / "hooks" / "pre-commit"
    try:
        body = hook.read_text(encoding="utf-8")
    except OSError:
        return False
    return "interlocks.cli pre-commit" in body or "interlocks pre-commit" in body


def claude_stop_hook_installed(project_root: Path) -> bool:
    """True when ``.claude/settings.json`` contains a ``Stop`` hook running ``post-edit``."""
    stop_entries = _stop_entries(project_root / ".claude" / "settings.json")
    for entry in stop_entries:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        if not isinstance(inner, list):
            continue
        if any(
            isinstance(hook, dict) and is_post_edit_command(hook.get("command")) for hook in inner
        ):
            return True
    return False


def _stop_entries(settings_path: Path) -> list[object]:
    """Parse ``settings.json`` and return ``hooks.Stop`` as a list (empty on any miss)."""
    if not settings_path.is_file():
        return []
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return []
    entries = hooks.get("Stop")
    return entries if isinstance(entries, list) else []


def ci_workflow_present(project_root: Path) -> bool:
    """True when any ``.github/workflows/*.y*ml`` references ``interlocks ci`` or the action."""
    return any(
        any(needle in body for needle in _CI_WORKFLOW_NEEDLES)
        for body in iter_workflow_bodies(project_root)
    )


def acceptance_scaffold_present(cfg: InterlockConfig) -> bool:
    """True when acceptance is enabled and at least one ``*.feature`` file exists."""
    if cfg.acceptance_runner == "off":
        return False
    features_dir = cfg.features_dir
    if features_dir is None or not features_dir.is_dir():
        return False
    return any(features_dir.rglob("*.feature"))


def interlock_config_block_present(cfg: InterlockConfig) -> bool:
    """True when the project ``pyproject.toml`` has a ``[tool.interlocks]`` table."""
    tool = cfg.pyproject.get("tool", {})
    return isinstance(tool, dict) and isinstance(tool.get("interlocks"), dict)
