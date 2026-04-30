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
from interlocks.setup_state import AGENT_DOCS, text_references_check_stage


def cmd_agents() -> None:
    section("Register interlocks in agent docs")
    install_agent_docs(Path.cwd())


def install_agent_docs(project_root: Path | None = None) -> None:
    block = defaults_path("agents_block.md").read_text(encoding="utf-8")
    root = project_root or Path.cwd()
    for name in AGENT_DOCS:
        _ensure_block(root / name, block)


def _ensure_block(path: Path, block: str) -> None:
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        ok(f"created {path.name} with interlocks block")
        return
    text = path.read_text(encoding="utf-8")
    if text_references_check_stage(text):
        warn_skip(f"{path.name} already documents interlocks check — skipped")
        return
    suffix = "" if text.endswith("\n") else "\n"
    path.write_text(f"{text}{suffix}\n{block}", encoding="utf-8")
    ok(f"appended interlocks block to {path.name}")
