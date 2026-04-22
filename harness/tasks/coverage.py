"""Tests under coverage with threshold + uncovered listing."""

from __future__ import annotations

from harness.config import build_coverage_test_command, invoker_prefix, load_config
from harness.runner import Task, arg_value, run


def task_coverage(*, min_pct: int | None = None) -> Task:
    """Run tests under coverage and report against ``min_pct`` (default: ``--min=N`` or 0)."""
    if min_pct is None:
        min_pct = int(arg_value("--min=", "0"))
    cfg = load_config()
    return Task(
        f"Coverage >= {min_pct}%",
        [*invoker_prefix(cfg), "coverage", "report", "--show-missing", f"--fail-under={min_pct}"],
        pre_cmds=(build_coverage_test_command(cfg),),
        test_summary=True,
    )


def cmd_coverage(*, min_pct: int | None = None) -> None:
    run(task_coverage(min_pct=min_pct))
