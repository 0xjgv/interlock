"""Check stage."""

from __future__ import annotations

import time

from interlock import ui
from interlock.config import load_config
from interlock.reports.suppressions import print_suppressions_report
from interlock.runner import reset_results, results_snapshot, run, run_tasks, warn_skip
from interlock.tasks.acceptance import task_acceptance
from interlock.tasks.crap import cmd_crap_cached_advisory
from interlock.tasks.deps import task_deps
from interlock.tasks.fix import cmd_fix
from interlock.tasks.format import cmd_format
from interlock.tasks.test import task_test
from interlock.tasks.typecheck import task_typecheck


def cmd_check() -> None:
    """Fix, format (serial — both mutate files), then typecheck + test in parallel.

    ``deps`` runs advisory at the end: fast feedback on dep hygiene without
    halting the edit loop on deptry noise. CI is where it gates.
    """
    start = time.monotonic()
    cfg = load_config()
    reset_results()
    ui.banner(cfg)
    try:
        ui.section("Quality Checks")
        cmd_fix()
        cmd_format()
        ui.section("Parallel")
        parallel = [task_typecheck()]
        test_task = task_test()
        if test_task is None:
            warn_skip("test: no test dir detected — run `interlock init` to scaffold tests/")
        else:
            parallel.append(test_task)
        if cfg.run_acceptance_in_check:
            acceptance = task_acceptance()
            if acceptance is not None:
                parallel.append(acceptance)
        run_tasks(parallel)
        ui.section("Advisory")
        run(task_deps(), no_exit=True)
        cmd_crap_cached_advisory()
    finally:
        print_suppressions_report()
        _print_footer(time.monotonic() - start)


def _print_footer(elapsed: float) -> None:
    """Verdict line when quiet (agent/LLM path); standard stage footer otherwise."""
    if not ui.is_quiet():
        ui.stage_footer(elapsed)
        return
    results = results_snapshot()
    fails = [label for label, ok in results if not ok]
    if not fails:
        print(f"check: ok — {len(results)} tasks, {elapsed:.1f}s")
        return
    detail = ", ".join(fails)
    print(f"check: FAILED — {detail} ({len(fails)} of {len(results)}) — {elapsed:.1f}s")
