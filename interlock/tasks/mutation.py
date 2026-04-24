"""Mutation testing via mutmut."""

from __future__ import annotations

import subprocess
import sys

from interlock.config import InterlockConfig, load_config
from interlock.git import changed_py_files_vs_main
from interlock.metrics import MutationSummary, coverage_line_rate, read_mutation_summary
from interlock.runner import (
    arg_value,
    fail,
    ok,
    python_m,
    warn_skip,
)


def _mutant_in_changed(mutant_key: str, changed: set[str]) -> bool:
    """Mutant keys look like `interlock.foo.x_bar__mutmut_1`; match vs `interlock/foo.py`.

    The trailing dot-component is the mutmut-mangled function name (``x_<name>``),
    which isn't part of the module file path — strip it before resolving.
    """
    head = mutant_key.split("__mutmut_", 1)[0]
    module = head.rsplit(".", 1)[0]
    rel = module.replace(".", "/") + ".py"
    return any(c == rel or c.endswith("/" + rel) for c in changed)


def _run_mutmut(mutmut: list[str], timeout: int) -> bool:
    """Run `mutmut run`, SIGTERM after `timeout`. Return True if it completed on its own."""
    with subprocess.Popen([*mutmut, "run"]) as proc:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            return False
        return True


def _print_survivors(survived: list[str], changed: set[str] | None) -> None:
    shown = [s for s in survived if changed is None or _mutant_in_changed(s, changed)][:20]
    if not shown:
        return
    print(f"    surviving mutants ({len(shown)} shown):")
    for key in shown:
        print(f"      {key}")


def _resolve_min_score(cfg: InterlockConfig) -> float | None:
    """CLI ``--min-score=`` wins; else ``cfg.mutation_min_score`` when enforcing; else None."""
    min_score_arg = arg_value("--min-score=", "")
    if min_score_arg:
        return float(min_score_arg)
    if cfg.enforce_mutation:
        return cfg.mutation_min_score
    return None


def _report_mutation(
    summary: MutationSummary, min_score: float | None, *, completed: bool, changed: set[str] | None
) -> bool:
    """Print ok/fail row + survivors. Return True when the gate failed."""
    total = summary.killed + summary.survived + summary.timeout
    failed = min_score is not None and summary.score < min_score
    partial = "" if completed else " (partial — timeout)"
    if failed:
        fail(f"Mutation: score {summary.score:.1f}% below threshold {min_score:.1f}%{partial}")
    else:
        ok(f"Mutation: score {summary.score:.1f}% (killed {summary.killed}/{total}){partial}")
    _print_survivors(summary.survivors, changed)
    return failed


def cmd_mutation() -> None:
    """Mutation score via mutmut (reads ``[tool.mutmut]``).

    CLI flags ``--min-coverage=`` / ``--max-runtime=`` / ``--min-score=`` win;
    otherwise thresholds come from ``cfg.mutation_min_coverage`` /
    ``cfg.mutation_max_runtime`` / ``cfg.mutation_min_score`` (defaults
    70.0 / 600 / 80.0, overridable via ``[tool.interlock]``). Advisory by default;
    set ``enforce_mutation = true`` to exit 1 when score < ``mutation_min_score``.
    """
    cfg = load_config()
    min_cov = float(arg_value("--min-coverage=", str(cfg.mutation_min_coverage)))
    rate = coverage_line_rate()
    if rate is None:
        warn_skip("mutation: no coverage data — run `interlock coverage` first")
        return
    pct = rate * 100
    if pct < min_cov:
        warn_skip(f"mutation: suite coverage {pct:.1f}% < {min_cov}%")
        return

    timeout = int(arg_value("--max-runtime=", str(cfg.mutation_max_runtime)))
    min_score = _resolve_min_score(cfg)
    changed = changed_py_files_vs_main() if "--changed-only" in sys.argv else None

    completed = _run_mutmut(python_m("mutmut"), timeout)

    summary = read_mutation_summary()
    if summary is None:
        warn_skip("mutation: .mutmut-cache/ missing after run")
        return

    if _report_mutation(summary, min_score, completed=completed, changed=changed):
        sys.exit(1)
