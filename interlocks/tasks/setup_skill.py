"""Install the bundled Claude Code SKILL.md into the consumer repo.

Copies ``interlocks/defaults/skill/SKILL.md`` to
``.claude/skills/interlocks/SKILL.md`` in the current working directory.
Idempotent: a byte-identical copy is a no-op; a divergent copy is overwritten
(the file is tool-managed, not user-edited). Stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from interlocks.defaults_path import path as defaults_path
from interlocks.runner import ok, section, warn_skip
from interlocks.setup_state import SKILL_DEST


def cmd_setup_skill() -> None:
    section("Install Claude Code skill")
    install_skill(Path.cwd())


def install_skill(project_root: Path | None = None) -> None:
    bundled = defaults_path("skill/SKILL.md").read_text(encoding="utf-8")
    dest = (project_root or Path.cwd()) / SKILL_DEST
    try:
        existing = dest.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    if existing == bundled:
        warn_skip(f"{SKILL_DEST} already installed — skipped")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(bundled, encoding="utf-8")
    ok(f"{'updated' if existing is not None else 'installed'} {SKILL_DEST}")
