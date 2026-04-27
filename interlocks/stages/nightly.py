"""Nightly stage: coverage + audit + enforced mutation."""

from __future__ import annotations

import time

from interlocks import ui
from interlocks.config import load_config
from interlocks.tasks.audit import cmd_audit
from interlocks.tasks.coverage import cmd_coverage
from interlocks.tasks.mutation import cmd_mutation


def cmd_nightly() -> None:
    """Long-running gates: coverage + audit + mutation (always blocking on score)."""
    start = time.monotonic()
    cfg = load_config()
    ui.banner(cfg)
    ui.section("Nightly")
    cmd_coverage()
    cmd_audit(allow_network_skip=True)
    # Force blocking regardless of `enforce_mutation`: nightly exists to fail the run.
    cmd_mutation(min_score_default=cfg.mutation_min_score)
    ui.stage_footer(time.monotonic() - start)
