"""Complexity gate via lizard. Called by stages/ci; not exposed in TASKS."""

from __future__ import annotations

from harness.config import load_config
from harness.runner import Task, run, tool


def task_complexity() -> Task:
    cfg = load_config()
    targets = [cfg.src_dir_arg]
    if cfg.test_dir_arg and cfg.test_dir_arg != cfg.src_dir_arg:
        targets.append(cfg.test_dir_arg)
    return Task(
        "Complexity (lizard)",
        tool("lizard", *targets, "-C", "15", "-a", "7", "-L", "100", "-i", "0"),
    )


def cmd_complexity() -> None:
    run(task_complexity())
