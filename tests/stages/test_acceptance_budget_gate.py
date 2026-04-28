"""Stage tests for the acceptance budget gate (`evaluate_acceptance_budget`).

Mixes unit-level coverage (direct calls into the gate from a constructed
``InterlockConfig``) with subprocess integration tests that drive
``interlocks ci`` / ``interlocks check`` end-to-end. The unit-level tests are
fast and exercise every classification branch; the subprocess tests pin down
exit codes and stderr surfacing through the real CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from interlocks.acceptance_budget import (
    Budget,
    compute_signature,
    derive_repo_secret,
    load_budget,
    write_budget,
)
from interlocks.acceptance_gate import evaluate_acceptance_budget
from interlocks.config import clear_cache, load_config
from tests.conftest import TmpProjectFactory

# ─────────────── shared scaffolding helpers ─────────────────────


_PYPROJECT_BUDGET = textwrap.dedent(
    """\
    [project]
    name = "tmppkg"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.interlocks]
    src_dir = "tmppkg"
    """
)

_PYPROJECT_BUDGET_OFF = textwrap.dedent(
    """\
    [project]
    name = "tmppkg"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.interlocks]
    src_dir = "tmppkg"
    enforce_acceptance_budget = false
    """
)

_PYPROJECT_BUDGET_BEHAVE = textwrap.dedent(
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

_PYPROJECT_CHECK_OPTIN = textwrap.dedent(
    """\
    [project]
    name = "tmppkg"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.interlocks]
    src_dir = "tmppkg"
    run_acceptance_in_check = true
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


@pytest.fixture(autouse=True)
def _purge_tmppkg_modules() -> Iterator[None]:
    """Drop ``tmppkg.*`` from ``sys.modules`` around each test.

    ``iter_public_symbols`` calls ``importlib.import_module``; once a tmp
    project has been imported, swapping the on-disk source between tests
    leaves the cached module in place and returns stale public symbols. We
    purge before AND after each test to keep the in-process gate tests
    isolated from each other.
    """
    _drop_tmppkg()
    try:
        yield
    finally:
        _drop_tmppkg()


def _drop_tmppkg() -> None:
    for name in [m for m in sys.modules if m == "tmppkg" or m.startswith("tmppkg.")]:
        sys.modules.pop(name, None)


def _make_project(
    factory: TmpProjectFactory,
    *,
    pyproject: str = _PYPROJECT_BUDGET,
    core_src: str = _CORE_SRC,
    with_feature: bool = True,
) -> Path:
    project = factory(
        pyproject=pyproject,
        src_files={
            "tmppkg/__init__.py": _INIT_SRC,
            "tmppkg/core.py": core_src,
        },
        test_files={"__init__.py": ""},
    )
    if with_feature:
        features = project / "tests" / "features"
        features.mkdir(parents=True, exist_ok=True)
        (features / "smoke.feature").write_text(_FEATURE, encoding="utf-8")
    return project


def _write_trace(project: Path, traced: list[str]) -> None:
    trace_dir = project / ".interlocks"
    trace_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "computed_at": "2026-04-28T12:00:00Z",
        "scenarios": {},
        "traced_symbols_index": traced,
    }
    (trace_dir / "trace.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_signed_budget(project: Path, untraced: dict[str, list[str]]) -> Budget:
    budget_path = project / ".interlocks" / "acceptance_budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    budget = Budget(
        version=1,
        baseline_at="2026-04-28T12:00:00Z",
        untraced=untraced,
        untraced_count=sum(len(v) for v in untraced.values()),
        signature=None,
    )
    secret = derive_repo_secret(project)
    budget = Budget(
        version=budget.version,
        baseline_at=budget.baseline_at,
        untraced=budget.untraced,
        untraced_count=budget.untraced_count,
        signature=compute_signature(budget, secret),
    )
    write_budget(budget_path, budget)
    return budget


# ─────────────── unit-level: evaluate_acceptance_budget ─────────────────────


def test_gate_pass_when_current_matches_budget(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project, core_src=_CORE_SRC_TWO)
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    _write_signed_budget(project, {"tmppkg.core": ["other_fn"]})
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "pass"
    assert outcome.message == ""


def test_gate_fail_on_rise_lists_new_symbol(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project, core_src=_CORE_SRC_TWO)
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    _write_signed_budget(project, {})  # budget empty → other_fn is a rise
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "fail"
    assert outcome.rises == ("tmppkg.core:other_fn",)
    assert "tmppkg.core:other_fn" in outcome.message


def test_gate_shrink_rewrites_budget_and_passes(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project)
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    # Budget claims public_fn is untraced; trace says it's covered → shrink.
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "shrink_passed"
    assert "shrunk by 1" in outcome.message
    assert "tmppkg.core:public_fn" in outcome.message
    rewritten = load_budget(project / ".interlocks" / "acceptance_budget.json")
    assert rewritten is not None
    assert rewritten.untraced == {}
    assert rewritten.untraced_count == 0
    assert rewritten.signature is not None and rewritten.signature.startswith("sha256:")


def test_gate_net_zero_swap_fails_listing_new_symbol(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing one symbol while opening another must still fail (asymmetric on set)."""
    project = _make_project(make_tmp_project, core_src=_CORE_SRC_TWO)
    # Trace covers public_fn; other_fn is the new uncovered symbol.
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    # Budget recorded a different missing symbol — same count, different set.
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "fail"
    assert outcome.rises == ("tmppkg.core:other_fn",)


def test_gate_skip_when_budget_file_absent(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project)
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "skip"
    assert outcome.message == ""


def test_gate_skip_when_explicitly_disabled(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project, pyproject=_PYPROJECT_BUDGET_OFF)
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "skip"
    assert outcome.message == ""


def test_gate_fail_on_tampering(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project)
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})
    # Hand-edit: append a symbol without re-signing.
    budget_path = project / ".interlocks" / "acceptance_budget.json"
    raw = json.loads(budget_path.read_text(encoding="utf-8"))
    raw["untraced"].setdefault("tmppkg.core", []).append("ghost")
    raw["untraced_count"] = 2
    budget_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "fail"
    assert "budget tampering detected" in outcome.message


def test_gate_fail_on_missing_signature(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project)
    budget_path = project / ".interlocks" / "acceptance_budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = Budget(
        version=1,
        baseline_at="2026-04-28T12:00:00Z",
        untraced={"tmppkg.core": ["public_fn"]},
        untraced_count=1,
        signature=None,
    )
    write_budget(budget_path, unsigned)
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "fail"
    assert "budget signature missing" in outcome.message


def test_gate_behave_runner_skips_with_nudge(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(make_tmp_project, pyproject=_PYPROJECT_BUDGET_BEHAVE)
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})
    monkeypatch.chdir(project)
    clear_cache()

    outcome = evaluate_acceptance_budget(load_config())

    assert outcome.kind == "skip"
    assert outcome.behave_skip is True
    assert "behave runner" in outcome.message
    assert "pytest-bdd only" in outcome.message


# ─────────────── integration: subprocess CI / check ─────────────────────


def _run_ci(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "ci"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_check(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "check"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


# Scaffolding for the subprocess tests — ci runs the full gate pipeline and we
# need it to *only* fail on the gate, not on lint/typecheck/etc. Cheaper to
# stub `cmd_ci` with a minimal in-process call than to satisfy every check.


_INPROCESS_RUN = textwrap.dedent(
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


def _run_gate_only(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Drive the gate via the same code paths cmd_ci uses, in a child process.

    This isolates the gate from format/lint/typecheck/etc. which the full
    `interlocks ci` would also run. The same exit + stderr semantics are
    asserted (the helper just calls `apply_budget_gate`).
    """
    return subprocess.run(
        [sys.executable, "-P", "-c", _INPROCESS_RUN],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_subprocess_ci_fails_on_rise(make_tmp_project: TmpProjectFactory) -> None:
    project = _make_project(make_tmp_project, core_src=_CORE_SRC_TWO)
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    _write_signed_budget(project, {})

    result = _run_gate_only(project)

    assert result.returncode != 0, f"expected failure: stderr={result.stderr}"
    assert "tmppkg.core:other_fn" in result.stderr


def test_subprocess_ci_shrink_rewrites_and_passes(make_tmp_project: TmpProjectFactory) -> None:
    project = _make_project(make_tmp_project)
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})

    result = _run_gate_only(project)

    assert result.returncode == 0, f"stderr={result.stderr}"
    assert "shrunk by 1" in result.stderr
    rewritten = load_budget(project / ".interlocks" / "acceptance_budget.json")
    assert rewritten is not None
    assert rewritten.untraced == {}
    assert rewritten.signature is not None


def test_subprocess_ci_silent_skip_pre_adoption(make_tmp_project: TmpProjectFactory) -> None:
    project = _make_project(make_tmp_project)

    result = _run_gate_only(project)

    assert result.returncode == 0
    # Silent skip → nothing on stderr from the gate.
    assert "acceptance budget" not in result.stderr
    assert "behave runner" not in result.stderr


def test_subprocess_ci_silent_skip_when_disabled(make_tmp_project: TmpProjectFactory) -> None:
    project = _make_project(make_tmp_project, pyproject=_PYPROJECT_BUDGET_OFF)
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})

    result = _run_gate_only(project)

    assert result.returncode == 0
    assert "acceptance budget" not in result.stderr
    assert "tampering" not in result.stderr


def test_subprocess_ci_fails_on_tampering(make_tmp_project: TmpProjectFactory) -> None:
    project = _make_project(make_tmp_project)
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})
    budget_path = project / ".interlocks" / "acceptance_budget.json"
    raw = json.loads(budget_path.read_text(encoding="utf-8"))
    raw["untraced"].setdefault("tmppkg.core", []).append("ghost")
    raw["untraced_count"] = 2
    budget_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    result = _run_gate_only(project)

    assert result.returncode != 0
    assert "budget tampering detected" in result.stderr


def test_subprocess_ci_fails_on_missing_signature(make_tmp_project: TmpProjectFactory) -> None:
    project = _make_project(make_tmp_project)
    budget_path = project / ".interlocks" / "acceptance_budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    write_budget(
        budget_path,
        Budget(
            version=1,
            baseline_at="2026-04-28T12:00:00Z",
            untraced={"tmppkg.core": ["public_fn"]},
            untraced_count=1,
            signature=None,
        ),
    )

    result = _run_gate_only(project)

    assert result.returncode != 0
    assert "budget signature missing" in result.stderr


def test_subprocess_ci_behave_runner_nudges_and_passes(
    make_tmp_project: TmpProjectFactory,
) -> None:
    project = _make_project(make_tmp_project, pyproject=_PYPROJECT_BUDGET_BEHAVE)
    _write_signed_budget(project, {"tmppkg.core": ["public_fn"]})

    result = _run_gate_only(project)

    assert result.returncode == 0, f"stderr={result.stderr}"
    assert "behave runner" in result.stderr
    assert "pytest-bdd only" in result.stderr


# ─────────────── check stage opt-in ─────────────────────


def test_check_skips_gate_when_opt_in_off(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default `run_acceptance_in_check=false` → check ignores budget rise."""
    project = _make_project(make_tmp_project, core_src=_CORE_SRC_TWO)
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    _write_signed_budget(project, {})  # rise present

    from interlocks.stages import check as check_mod

    monkeypatch.setattr(check_mod, "cmd_fix", lambda: None)
    monkeypatch.setattr(check_mod, "cmd_format", lambda: None)
    monkeypatch.setattr(check_mod, "run_tasks", lambda tasks: None)
    monkeypatch.setattr(check_mod, "run", lambda task, **_kw: None)
    monkeypatch.setattr(check_mod, "cmd_crap_cached_advisory", lambda: None)
    monkeypatch.setattr(check_mod, "print_suppressions_report", lambda: None)
    gate_calls: list[object] = []
    monkeypatch.setattr(
        check_mod,
        "evaluate_acceptance_budget",
        lambda cfg: gate_calls.append(cfg) or pytest.fail("gate should not run"),
    )

    monkeypatch.chdir(project)
    clear_cache()
    check_mod.cmd_check()

    assert gate_calls == []


def test_check_enforces_gate_when_opt_in_on(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run_acceptance_in_check=true` → check fails on rise like ci does."""
    project = _make_project(
        make_tmp_project, pyproject=_PYPROJECT_CHECK_OPTIN, core_src=_CORE_SRC_TWO
    )
    _write_trace(project, traced=["tmppkg.core:public_fn"])
    _write_signed_budget(project, {})

    from interlocks.stages import check as check_mod

    monkeypatch.setattr(check_mod, "cmd_fix", lambda: None)
    monkeypatch.setattr(check_mod, "cmd_format", lambda: None)
    monkeypatch.setattr(check_mod, "run_tasks", lambda tasks: None)
    monkeypatch.setattr(check_mod, "run", lambda task, **_kw: None)
    monkeypatch.setattr(check_mod, "cmd_crap_cached_advisory", lambda: None)
    monkeypatch.setattr(check_mod, "print_suppressions_report", lambda: None)

    monkeypatch.chdir(project)
    clear_cache()
    with pytest.raises(SystemExit) as exc:
        check_mod.cmd_check()
    assert exc.value.code == 1
