"""Register interlocks usage in agent-facing markdown (AGENTS.md, CLAUDE.md).

Idempotent: appends a canonical ``<important>`` block to the bottom of each
file only when no existing ``interlocks`` reference is present. Creates the
file if missing. Operates on the current working directory and does not need a
``pyproject.toml`` so it runs in any repo. Stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from interlocks.defaults_path import path as defaults_path
from interlocks.runner import ok, section, warn_skip

_TARGETS: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md")


def cmd_agents() -> None:
    section("Register interlocks in agent docs")
    block = defaults_path("agents_block.md").read_text(encoding="utf-8")
    cwd = Path.cwd()
    for name in _TARGETS:
        _ensure_block(cwd / name, block)


def _ensure_block(path: Path, block: str) -> None:
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        ok(f"created {path.name} with interlocks block")
        return
    text = path.read_text(encoding="utf-8")
    if "interlocks" in text.lower():
        warn_skip(f"{path.name} already references interlocks — skipped")
        return
    suffix = "" if text.endswith("\n") else "\n"
    path.write_text(f"{text}{suffix}\n{block}", encoding="utf-8")
    ok(f"appended interlocks block to {path.name}")
