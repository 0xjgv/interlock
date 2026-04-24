"""Setup-hooks stage — writes git pre-commit + Claude Code Stop hooks."""

from __future__ import annotations

import json
import shlex
import sys
import time
from pathlib import Path

from interlock import ui
from interlock.config import load_config
from interlock.runner import ok
from interlock.setup_state import is_post_edit_command


def _reset_invalid_container[T: (dict[str, object], list[object])](
    parent: dict[str, object], key: str, empty: T
) -> T:
    """Return ``parent[key]`` when it matches ``type(empty)``; reset to ``empty`` otherwise."""
    value = parent.setdefault(key, empty)
    if isinstance(value, type(empty)):
        return value  # pyright: ignore[reportReturnType]
    parent[key] = empty
    return empty


def _keep_existing_hook(hook: object, new_command: str) -> bool:
    """Keep non-command hooks; drop duplicates of ``new_command`` or prior post-edit entries."""
    if not isinstance(hook, dict):
        return True
    if hook.get("type") != "command":
        return True
    existing = hook.get("command")
    if existing == new_command:
        return False
    return not is_post_edit_command(existing)


def _ensure_stop_hook(settings: dict[str, object], command: str) -> dict[str, object]:
    hooks = _reset_invalid_container(settings, "hooks", {})
    stop_entries = _reset_invalid_container(hooks, "Stop", [])
    merged_hooks: list[object] = [
        hook
        for entry in stop_entries
        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list)
        for hook in entry["hooks"]
        if _keep_existing_hook(hook, command)
    ]
    merged_hooks.append({"type": "command", "command": command})
    hooks["Stop"] = [{"hooks": merged_hooks}]
    return settings


def cmd_hooks() -> None:
    start = time.monotonic()
    ui.banner(load_config())
    ui.section("Setup Hooks")
    try:
        python = shlex.quote(sys.executable)

        hook = Path(".git/hooks/pre-commit")
        hook.parent.mkdir(parents=True, exist_ok=True)
        script = f"#!/bin/sh\nexec {python} -m interlock.cli pre-commit\n"
        hook.write_text(script, encoding="utf-8")
        hook.chmod(0o755)
        ok("Installed pre-commit hook")

        settings_path = Path(".claude/settings.json")
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing = _ensure_stop_hook(existing, f"{python} -m interlock.cli post-edit")
        settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        ok("Installed Claude Code Stop hook")
    finally:
        ui.stage_footer(time.monotonic() - start)
