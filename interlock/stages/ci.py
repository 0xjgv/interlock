"""CI stage."""

from __future__ import annotations

import time

from interlock import ui
from interlock.config import load_config
from interlock.runner import run_tasks
from interlock.tasks.acceptance import task_acceptance
from interlock.tasks.arch import task_arch
from interlock.tasks.complexity import task_complexity
from interlock.tasks.coverage import task_coverage
from interlock.tasks.crap import cmd_crap
from interlock.tasks.deps import task_deps
from interlock.tasks.format_check import task_format_check
from interlock.tasks.lint import task_lint
from interlock.tasks.mutation import cmd_mutation
from interlock.tasks.typecheck import task_typecheck


def cmd_ci() -> None:
    """Full verification: format_check, lint, complexity, deps, arch, typecheck, coverage,
    CRAP, (optionally) mutation."""
    start = time.monotonic()
    cfg = load_config()
    ui.banner(cfg)
    ui.section("CI Checks")
    tasks = [
        task_format_check(),
        task_lint(),
        task_complexity(),
        task_deps(),
        task_typecheck(),
        task_coverage(),
    ]
    for optional in (task_arch(), task_acceptance()):
        if optional is not None:
            tasks.append(optional)
    run_tasks(tasks)
    # CRAP/mutation read coverage.xml produced by task_coverage — keep sequential.
    ui.section("Gates")
    cmd_crap()
    if cfg.run_mutation_in_ci:
        cmd_mutation()
    ui.stage_footer(time.monotonic() - start)
