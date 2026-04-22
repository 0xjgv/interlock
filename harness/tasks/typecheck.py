"""Type-check with basedpyright."""

from __future__ import annotations

from harness.config import load_config
from harness.runner import Task, run, tool


def task_typecheck() -> Task:
    cfg = load_config()
    return Task("Type check", tool("basedpyright", cfg.src_dir_arg))


def cmd_typecheck() -> None:
    run(task_typecheck())
