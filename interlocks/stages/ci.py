"""CI stage."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import MutationCIMode, load_config
from interlocks.runner import run_tasks
from interlocks.tasks.acceptance import task_acceptance
from interlocks.tasks.arch import task_arch
from interlocks.tasks.complexity import task_complexity
from interlocks.tasks.coverage import task_coverage
from interlocks.tasks.crap import cmd_crap
from interlocks.tasks.deps import task_deps
from interlocks.tasks.format_check import task_format_check
from interlocks.tasks.lint import task_lint
from interlocks.tasks.mutation import cmd_mutation
from interlocks.tasks.typecheck import task_typecheck


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
    if _should_run_mutation(cfg.mutation_ci_mode, run_in_ci=cfg.run_mutation_in_ci):
        cmd_mutation(changed_only=cfg.mutation_ci_mode == "incremental")
    ui.stage_footer(time.monotonic() - start)


def _should_run_mutation(mode: MutationCIMode, *, run_in_ci: bool) -> bool:
    """Back-compat: when no mode is set, fall back to legacy ``run_mutation_in_ci``."""
    return mode != "off" or run_in_ci
