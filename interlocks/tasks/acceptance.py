"""Gherkin acceptance tests via pytest-bdd (default) or behave (auto-detected).

Zero-config contract: when no ``features/`` directory exists and no override is
set, ``task_acceptance()`` returns ``None`` and ``cmd_acceptance`` prints a
skip nudge — safe on any foreign repo. Stage wrappers must guard on the same
``None`` signal to stay silent in CI.

``cmd_acceptance`` also dispatches the ``baseline`` and ``status`` subcommands
(``interlocks acceptance baseline [--force]`` / ``interlocks acceptance
status``) by reading ``sys.argv``. Top-level CLI dispatch is hand-rolled and
strips flags before lookup, so subcommands must be parsed locally.
"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 - intentional: trace-freshness check shells `git log`.
import sys
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from interlocks.acceptance_budget import (
    Budget,
    compute_signature,
    compute_untraced,
    derive_repo_secret,
    write_budget,
)
from interlocks.acceptance_status import AcceptanceStatus, classify_acceptance, remediation_message
from interlocks.acceptance_symbols import iter_public_symbols
from interlocks.config import InterlockConfig, invoker_prefix, load_config
from interlocks.detect import detect_acceptance_runner
from interlocks.runner import Task, fail_skip, ok, run, warn_skip

if TYPE_CHECKING:
    from pathlib import Path

# Spec-pinned nudge string; mirrored in `interlocks acceptance status` output
# (acceptance_status section) and `acceptance-symbol-trace/spec.md` (D11).
BEHAVE_TRACE_NUDGE = "interlocks: behave runner: trace recording unavailable (pytest-bdd only)"


def task_acceptance() -> Task | None:
    """Build the acceptance Task when the project is RUNNABLE; otherwise None.

    The classifier-driven enforcement decision (fail vs. skip) lives at the
    caller — stages and ``cmd_acceptance`` — so this function neither prints
    nor exits.
    """
    cfg = load_config()
    if classify_acceptance(cfg) is not AcceptanceStatus.RUNNABLE:
        return None
    runner = detect_acceptance_runner(cfg)
    features_dir = cfg.features_dir
    features_arg = cfg.features_dir_arg
    if runner is None or features_dir is None or features_arg is None:
        return None
    if runner == "behave":
        return _behave_task(cfg, features_arg)
    return _pytest_bdd_task(cfg, features_dir, features_arg)


def cmd_acceptance() -> None:
    """Dispatch acceptance subcommands or run the suite.

    ``main()`` in ``cli.py`` strips flag-like args before dict-lookup, so the
    subcommand token (``baseline`` / ``status``) appears at ``sys.argv[2]`` (or
    later if the user prefixed flags). We re-scan ``sys.argv`` here rather than
    plumbing args through the dispatcher.
    """
    sub = _subcommand_from_argv()
    if sub == "baseline":
        _cmd_acceptance_baseline(force=_force_flag_from_argv())
        return
    if sub == "status":
        _cmd_acceptance_status()
        return
    _cmd_acceptance_run()


def _cmd_acceptance_run() -> None:
    cfg = load_config()
    status = classify_acceptance(cfg)
    if status is AcceptanceStatus.DISABLED:
        warn_skip("acceptance: disabled via acceptance_runner = 'off'")
        return
    if status is AcceptanceStatus.OPTIONAL_MISSING:
        warn_skip(
            "acceptance: no features/ directory — run `interlocks init-acceptance` to scaffold one"
        )
        return
    if status in {
        AcceptanceStatus.MISSING_FEATURES_DIR,
        AcceptanceStatus.MISSING_FEATURE_FILES,
        AcceptanceStatus.MISSING_SCENARIOS,
    }:
        fail_skip(remediation_message(status, cfg.features_dir))
        return
    task = task_acceptance()
    if task is None:
        warn_skip(
            "acceptance: no features/ directory — run `interlocks init-acceptance` to scaffold one"
        )
        return
    # D11 / spec: behave path has no trace plugin support. Name the dark
    # gate explicitly on stderr so adopters see it instead of silently
    # losing budget enforcement. Check the *detected* runner — config-set
    # `acceptance_runner` may be None when behave is auto-detected from the
    # canonical `features/steps/` + `environment.py` shape.
    if detect_acceptance_runner(cfg) == "behave":
        print(BEHAVE_TRACE_NUDGE, file=sys.stderr)
    run(task)


def _subcommand_from_argv() -> str | None:
    """Return ``baseline`` / ``status`` if present after ``acceptance`` in argv.

    ``main()`` strips flags before dispatch, so ``args[0]`` is ``acceptance``
    and ``args[1]`` (if any) is the subcommand. We re-scan ``sys.argv`` directly
    so this helper stays decoupled from the dispatcher and is testable in
    isolation.
    """
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) >= 2 and args[0] == "acceptance":
        return args[1]
    return None


def _force_flag_from_argv() -> bool:
    return "--force" in sys.argv[1:]


def _cmd_acceptance_baseline(*, force: bool) -> None:
    """Snapshot the current untraced public-symbol set into the budget file.

    Refuses to overwrite an existing budget unless ``--force``; refuses to run
    without a fresh trace map. Writes ``Budget`` with a deterministic signature
    and atomic semantics.
    """
    cfg = load_config()
    budget_path = cfg.acceptance_budget_path
    trace_path = cfg.acceptance_trace_path

    if budget_path.exists() and not force:
        fail_skip(
            f"acceptance baseline: refusing to overwrite {cfg.relpath(budget_path)} "
            "— pass --force to re-baseline"
        )
        return

    trace_payload = _read_trace_or_fail(cfg, trace_path)
    _ensure_trace_fresh_or_fail(cfg, trace_path, trace_payload)
    traced_index = _traced_index_from_trace(trace_payload)

    untraced = compute_untraced(iter_public_symbols(cfg), traced_index)
    untraced_count = sum(len(attrs) for attrs in untraced.values())
    budget = Budget(
        version=1,
        baseline_at=_now_iso_utc(),
        untraced=untraced,
        untraced_count=untraced_count,
        signature=None,
    )
    repo_secret = derive_repo_secret(cfg.project_root)
    signed = replace(budget, signature=compute_signature(budget, repo_secret))
    write_budget(budget_path, signed)
    ok(
        f"acceptance baseline: wrote {cfg.relpath(budget_path)} "
        f"({untraced_count} untraced symbol{'s' if untraced_count != 1 else ''})"
    )


def _cmd_acceptance_status() -> None:
    """Read-only summary of trace map + budget. Always exits 0."""
    cfg = load_config()
    print(f"acceptance status (project: {cfg.relpath(cfg.project_root)})")
    if cfg.acceptance_runner == "behave":
        print("  behave runner: trace recording unavailable (pytest-bdd only)")

    trace_payload = _read_trace_silent(cfg.acceptance_trace_path)
    public_total: int | None = None
    if trace_payload is None:
        print(f"  trace map: missing ({cfg.relpath(cfg.acceptance_trace_path)})")
        print(
            f"  Run `interlocks acceptance` to populate {cfg.relpath(cfg.acceptance_trace_path)}"
        )
    else:
        scenario_count = _scenario_count_from_trace(trace_payload)
        traced_index = _traced_index_from_trace(trace_payload)
        traced_count = len(traced_index)
        public_total = sum(1 for _ in iter_public_symbols(cfg))
        untraced_count = max(0, public_total - traced_count)
        print(f"  scenarios:        {scenario_count}")
        print(f"  traced symbols:   {traced_count}")
        print(f"  untraced symbols: {untraced_count}")

    _print_budget_delta(cfg, trace_payload, public_total=public_total)


def _print_budget_delta(
    cfg: InterlockConfig,
    trace_payload: dict[str, object] | None,
    *,
    public_total: int | None,
) -> None:
    """Append the budget summary; render ``budget delta`` only when both files exist.

    ``public_total`` is reused from the caller when the trace map exists to
    avoid re-walking ``src_dir`` (importing every module is non-trivial).
    """
    budget_path = cfg.acceptance_budget_path
    if not budget_path.exists():
        print(f"  budget:           absent ({cfg.relpath(budget_path)})")
        return
    try:
        raw = json.loads(budget_path.read_text(encoding="utf-8"))
        budget_count = int(raw.get("untraced_count", 0))
    except (OSError, ValueError, TypeError):
        print(f"  budget:           unreadable ({cfg.relpath(budget_path)})")
        return
    print(f"  budget untraced:  {budget_count} ({cfg.relpath(budget_path)})")
    if trace_payload is None or public_total is None:
        return
    traced_count = len(_traced_index_from_trace(trace_payload))
    current_untraced = max(0, public_total - traced_count)
    delta = current_untraced - budget_count
    sign = "+" if delta > 0 else ""
    print(f"  delta vs budget:  {sign}{delta}")


def _read_trace_or_fail(cfg: InterlockConfig, trace_path: Path) -> dict[str, object]:
    payload = _read_trace_silent(trace_path)
    if payload is None:
        fail_skip(
            f"acceptance baseline: trace map missing at {cfg.relpath(trace_path)} "
            "— run `interlocks acceptance` first"
        )
        msg = "unreachable"
        raise RuntimeError(msg)  # pragma: no cover - fail_skip raises SystemExit
    return payload


def _read_trace_silent(trace_path: Path) -> dict[str, object] | None:
    if not trace_path.exists():
        return None
    try:
        raw = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _ensure_trace_fresh_or_fail(
    cfg: InterlockConfig, trace_path: Path, trace_payload: dict[str, object]
) -> None:
    """Fail when ``computed_at`` predates the latest commit touching ``src_dir``.

    Falls back to "skip the freshness check" when ``git`` is unavailable, the
    project isn't a repo, or ``src_dir`` has no commits — the trace file's
    existence still gates the command.
    """
    last_commit_iso = _git_last_commit_iso(cfg.project_root, cfg.src_dir)
    if last_commit_iso is None:
        return  # git unavailable or no commits — file presence is sufficient
    computed_at = trace_payload.get("computed_at")
    if not isinstance(computed_at, str):
        fail_skip(
            f"acceptance baseline: trace map at {cfg.relpath(trace_path)} has no "
            "`computed_at` — run `interlocks acceptance` first"
        )
        return
    computed_dt = _parse_iso(computed_at)
    commit_dt = _parse_iso(last_commit_iso)
    if computed_dt is None or commit_dt is None:
        return  # malformed timestamps — let later validation catch it
    if computed_dt < commit_dt:
        fail_skip(
            f"acceptance baseline: trace map at {cfg.relpath(trace_path)} is stale "
            f"(computed_at={computed_at} < last src_dir commit={last_commit_iso}) "
            "— run `interlocks acceptance` first"
        )


def _git_last_commit_iso(project_root: Path, src_dir: Path) -> str | None:
    """Return ISO-8601 commit time of the latest commit touching ``src_dir``.

    Returns ``None`` when ``git`` is missing, the project isn't a repo, or the
    path has no recorded commits — callers treat that as "freshness unknown,
    don't block".
    """
    try:
        relative_src = str(src_dir.relative_to(project_root))
    except ValueError:
        relative_src = str(src_dir)
    try:
        result = subprocess.run(  # noqa: S603 - args are literal except `relative_src`, project-local.
            ["git", "log", "-1", "--format=%cI", "--", relative_src],  # noqa: S607
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    line = result.stdout.strip()
    return line or None


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; return ``None`` on malformed input."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _now_iso_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _traced_index_from_trace(payload: dict[str, object]) -> list[str]:
    raw = payload.get("traced_symbols_index")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _scenario_count_from_trace(payload: dict[str, object]) -> int:
    scenarios = payload.get("scenarios")
    if isinstance(scenarios, dict):
        return len(scenarios)
    return 0


def _pytest_bdd_task(cfg: InterlockConfig, features_dir: Path, features_arg: str) -> Task:
    # pytest-bdd scenarios live in step-def files (``test_*.py`` with
    # ``scenarios(...)``) — pointing pytest at ``features/`` alone finds nothing.
    # We pass every acceptance path pytest needs to collect; exit 5 ("nothing
    # collected") stays benign for freshly-scaffolded projects.
    targets = _pytest_bdd_targets(cfg, features_dir, features_arg)
    cmd = [*invoker_prefix(cfg), "pytest", *targets, "-q", *cfg.pytest_args]
    return Task(
        "Acceptance (pytest-bdd)",
        cmd,
        test_summary=True,
        allowed_rcs=(0, 5),
        label="acceptance",
        display="pytest-bdd",
        env=_trace_env(cfg),
    )


def _trace_env(cfg: InterlockConfig) -> dict[str, str]:
    """Env signals consumed by ``interlocks.acceptance_trace_plugin`` (D1, D2).

    The plugin auto-loads via the ``pytest11`` entry-point declared in
    ``pyproject.toml``; we deliberately skip injecting ``-p
    interlocks.acceptance_trace_plugin`` because the entry-point already
    handles loading and the plugin is inert unless ``INTERLOCKS_TRACE=1``.

    We do NOT strip ``--cov`` here: §3 picked Option A (``sys.monitoring``
    with a distinct tool ID, see ``acceptance_trace_plugin._activate_monitoring``),
    so coverage.py and the trace recorder coexist on Python ≥3.12 without
    interference. Option B's ``--cov`` stripping is moot under the current
    Python minimum (≥3.13).
    """
    trace_path = cfg.acceptance_trace_path
    if not trace_path.is_absolute():
        trace_path = cfg.project_root / trace_path
    return {
        "INTERLOCKS_TRACE": "1",
        "INTERLOCKS_TRACE_PATH": str(trace_path),
        "INTERLOCKS_TRACE_SRC_PREFIX": cfg.src_dir.name,
    }


def _pytest_bdd_targets(cfg: InterlockConfig, features_dir: Path, features_arg: str) -> list[str]:
    """Directories pytest must collect for pytest-bdd to bind features → steps.

    Canonical scaffold drops step-defs as a sibling of ``features/``; pick that
    up automatically when present so ``interlocks acceptance`` stays self-contained.
    """
    dirs = [features_arg]
    step_defs = features_dir.parent / "step_defs"
    if step_defs.is_dir():
        dirs.append(cfg.relpath(step_defs))
    return dirs


def _behave_task(cfg: InterlockConfig, features_arg: str) -> Task:
    cmd = [*invoker_prefix(cfg), "behave", features_arg]
    return Task("Acceptance (behave)", cmd, label="acceptance", display="behave")
