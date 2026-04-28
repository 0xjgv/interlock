"""Step defs for tests/features/interlock_acceptance_budget.feature.

External-CLI guardrails for the acceptance budget surface (§10.5):

- ``interlocks acceptance baseline`` writes a signed ``.interlocks/acceptance_budget.json``.
- ``interlocks acceptance baseline`` refuses to overwrite without ``--force``.
- ``interlocks acceptance status`` prints scenario / trace / budget summary lines.
- ``interlocks acceptance status`` names the behave gap when the runner is pinned to behave.
- The budget gate (driven via ``apply_budget_gate``, the same entrypoint
  ``interlocks ci`` calls) fails on rises, shrinks budgets on closure, and
  rejects hand-edited (tampered) budget files.

Each scenario builds a self-contained tmp project (a small ``tmppkg`` package
with one public function plus an empty Gherkin feature) and shells out to the
CLI. Steps are wired via pytest-bdd; the actual gate evaluation reuses the
same ``_run_gate_only`` style snippet exercised in ``tests/stages/`` so the
scenarios pin down the shipped CLI behaviour without needing the full ``ci``
pipeline (lint/typecheck/coverage/etc.) to pass on the tmp project.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from interlocks.acceptance_budget import (
    Budget,
    compute_signature,
    derive_repo_secret,
    load_budget,
    write_budget,
)

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_acceptance_budget.feature"))


# ─────────────── tmp-project scaffolding ─────────────────────


_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "tmppkg"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.interlocks]
    src_dir = "tmppkg"
    """
)

_PYPROJECT_BEHAVE = textwrap.dedent(
    """\
    [project]
    name = "tmppkg"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.interlocks]
    src_dir = "tmppkg"
    acceptance_runner = "behave"
    """
)

_INIT_SRC = '"""Tmp pkg."""\n'
_CORE_SRC = textwrap.dedent(
    '''\
    """Core."""


    def public_fn() -> int:
        return 1
    '''
)
_CORE_SRC_TWO = textwrap.dedent(
    '''\
    """Core."""


    def public_fn() -> int:
        return 1


    def other_fn() -> int:
        return 2
    '''
)
_FEATURE = textwrap.dedent(
    """\
    Feature: smoke
      Scenario: pings
        Given a precondition
    """
)


@given("an acceptance-budget tmp project", target_fixture="tmp_project")
def _tmp_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = project / "tmppkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(_INIT_SRC, encoding="utf-8")
    (pkg / "core.py").write_text(_CORE_SRC, encoding="utf-8")
    features = project / "tests" / "features"
    features.mkdir(parents=True)
    (features / "smoke.feature").write_text(_FEATURE, encoding="utf-8")
    return project


# ─────────────── trace + budget seeding ─────────────────────


def _write_trace(project: Path, traced: list[str]) -> None:
    trace_dir = project / ".interlocks"
    trace_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "computed_at": "2026-04-28T12:00:00Z",
        "scenarios": {
            "deadbeefcafef00d": {
                "feature": "tests/features/smoke.feature",
                "title": "pings",
                "symbols": list(traced),
            }
        },
        "traced_symbols_index": traced,
    }
    (trace_dir / "trace.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_signed_budget(project: Path, untraced: dict[str, list[str]]) -> Budget:
    budget_path = project / ".interlocks" / "acceptance_budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = Budget(
        version=1,
        baseline_at="2026-04-28T12:00:00Z",
        untraced=untraced,
        untraced_count=sum(len(v) for v in untraced.values()),
        signature=None,
    )
    secret = derive_repo_secret(project)
    signed = Budget(
        version=unsigned.version,
        baseline_at=unsigned.baseline_at,
        untraced=unsigned.untraced,
        untraced_count=unsigned.untraced_count,
        signature=compute_signature(unsigned, secret),
    )
    write_budget(budget_path, signed)
    return signed


@given("a fresh trace covering the public surface")
def _fresh_trace(tmp_project: Path) -> None:
    _write_trace(tmp_project, traced=["tmppkg.core:public_fn"])


@given(parsers.parse('a trace covering "{symbol}"'))
def _trace_covering(tmp_project: Path, symbol: str) -> None:
    _write_trace(tmp_project, traced=[symbol])


@given("a previously written budget")
def _previously_written_budget(tmp_project: Path) -> None:
    _write_signed_budget(tmp_project, {"tmppkg.core": ["public_fn"]})


@given("a signed budget with no untraced symbols")
def _signed_empty_budget(tmp_project: Path) -> None:
    _write_signed_budget(tmp_project, {})


@given(parsers.parse('a signed budget listing "{symbol}" as untraced'))
def _signed_budget_with(tmp_project: Path, symbol: str) -> None:
    module, attr = symbol.split(":", 1)
    _write_signed_budget(tmp_project, {module: [attr]})


@given(parsers.parse('a second public function "{name}" exists in the source'))
def _second_public_fn(tmp_project: Path, name: str) -> None:
    # _CORE_SRC_TWO already defines `other_fn`; assert the requested name
    # matches the canonical scaffold so a future renamer notices.
    assert name == "other_fn", f"this scaffold only ships other_fn; got {name!r}"
    (tmp_project / "tmppkg" / "core.py").write_text(_CORE_SRC_TWO, encoding="utf-8")


@given(parsers.parse('the tmp project pins acceptance_runner to "{runner}"'))
def _pin_runner(tmp_project: Path, runner: str) -> None:
    assert runner == "behave", f"only behave is wired in this scaffold; got {runner!r}"
    (tmp_project / "pyproject.toml").write_text(_PYPROJECT_BEHAVE, encoding="utf-8")


@given(parsers.parse('the budget file is hand-edited to add "{ghost}" without re-signing'))
def _hand_edit_budget(tmp_project: Path, ghost: str) -> None:
    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    raw = json.loads(budget_path.read_text(encoding="utf-8"))
    raw["untraced"].setdefault("tmppkg.core", []).append(ghost)
    raw["untraced_count"] = sum(len(v) for v in raw["untraced"].values())
    budget_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


# ─────────────── command runners ─────────────────────


_GATE_SNIPPET = textwrap.dedent(
    """\
    import sys
    from interlocks.acceptance_status import AcceptanceStatus, classify_acceptance
    from interlocks.acceptance_gate import apply_budget_gate, evaluate_acceptance_budget
    from interlocks.config import load_config

    cfg = load_config()
    status = classify_acceptance(cfg)
    if status is AcceptanceStatus.RUNNABLE:
        apply_budget_gate(evaluate_acceptance_budget(cfg))
    """
)


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_gate(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-c", _GATE_SNIPPET],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@when(
    parsers.parse('I run "interlocks {subcmd}" in the tmp project'),
    target_fixture="acceptance_result",
)
def _run_acceptance_subcmd(tmp_project: Path, subcmd: str) -> subprocess.CompletedProcess[str]:
    return _run_cli(tmp_project, *subcmd.split())


@when(
    "I run the acceptance budget gate in the tmp project",
    target_fixture="acceptance_result",
)
def _run_budget_gate(tmp_project: Path) -> subprocess.CompletedProcess[str]:
    return _run_gate(tmp_project)


# ─────────────── assertions ─────────────────────


@then(parsers.parse("the acceptance command exits {code:d}"))
def _exits(acceptance_result: subprocess.CompletedProcess[str], code: int) -> None:
    assert acceptance_result.returncode == code, (
        f"expected exit {code}, got {acceptance_result.returncode}\n"
        f"stdout:\n{acceptance_result.stdout}\nstderr:\n{acceptance_result.stderr}"
    )


@then(parsers.parse('the acceptance output contains "{fragment}"'))
def _stdout_contains(acceptance_result: subprocess.CompletedProcess[str], fragment: str) -> None:
    combined = acceptance_result.stdout + acceptance_result.stderr
    assert fragment in combined, (
        f"expected {fragment!r} in stdout/stderr; got:\nstdout:\n"
        f"{acceptance_result.stdout}\nstderr:\n{acceptance_result.stderr}"
    )


@then(parsers.parse('the acceptance stderr contains "{fragment}"'))
def _stderr_contains(acceptance_result: subprocess.CompletedProcess[str], fragment: str) -> None:
    assert fragment in acceptance_result.stderr, (
        f"expected {fragment!r} in stderr; got:\n{acceptance_result.stderr}"
    )


@then("the budget file exists and is signed")
def _budget_signed(tmp_project: Path) -> None:
    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    assert budget_path.exists(), "expected budget file to be written"
    loaded = load_budget(budget_path)
    assert loaded is not None
    assert loaded.signature is not None
    assert loaded.signature.startswith("sha256:")


@then("the budget file now lists no untraced symbols")
def _budget_empty_after_shrink(tmp_project: Path) -> None:
    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    loaded = load_budget(budget_path)
    assert loaded is not None
    assert loaded.untraced == {}
    assert loaded.untraced_count == 0
