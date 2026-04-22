"""Run tests."""

from __future__ import annotations

from harness.config import build_test_command, load_config
from harness.runner import Task, run


def task_test() -> Task:
    cfg = load_config()
    return Task("Run tests", build_test_command(cfg), test_summary=True)


def cmd_test() -> None:
    run(task_test())
