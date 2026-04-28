"""Tests for static `interlocks evaluate` report."""

from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

import pytest

from interlocks.config import InterlockConfig, load_config
from interlocks.tasks import evaluate as evaluate_mod
from interlocks.tasks.evaluate import EvaluationItem, cmd_evaluate, evaluate
from tests.conftest import TmpProjectFactory


@pytest.fixture(autouse=True)
def _isolate_pkg_module() -> None:
    """Drop cached `pkg` modules so per-test source trees re-import cleanly.

    `iter_public_symbols` adds `<project_root>` to `sys.path` and imports each
    discovered module. Because every `_project()` writes its own `pkg/`
    package under a different `tmp_path`, leftover cache entries from a prior
    test would otherwise resolve to the wrong directory.
    """
    for name in list(sys.modules):
        if name == "pkg" or name.startswith("pkg."):
            del sys.modules[name]


def _pyproject(
    *,
    branch: bool = True,
    mutation_mode: str = "full",
    run_mutation_in_ci: bool | None = None,
    importlinter: bool = True,
) -> str:
    legacy_mutation_line = ""
    if run_mutation_in_ci is not None:
        value = str(run_mutation_in_ci).lower()
        legacy_mutation_line = f"run_mutation_in_ci = {value}\n"
    body = f"""\
    [project]
    name = "pkg"
    version = "0.0.0"
    requires-python = ">=3.13"

    [dependency-groups]
    dev = ["pytest>=9", "pytest-bdd>=8"]

    [tool.interlocks]
    preset = "strict"
    src_dir = "pkg"
    test_dir = "tests"
    test_runner = "pytest"
    test_invoker = "python"
    mutation_ci_mode = "{mutation_mode}"
    evaluate_dependency_freshness = true
    audit_severity_threshold = "high"
    pr_ci_runtime_budget_seconds = 600
    {legacy_mutation_line}
    [tool.coverage.run]
    source = ["pkg"]
    branch = {str(branch).lower()}

    [tool.mutmut]
    paths_to_mutate = ["pkg/"]
    tests_dir = ["tests/"]
    """
    if importlinter:
        body += """\

        [tool.importlinter]
        root_packages = ["pkg", "tests"]

        [[tool.importlinter.contracts]]
        name = "Production does not import tests"
        type = "forbidden"
        source_modules = ["pkg"]
        forbidden_modules = ["tests"]
        """
    return textwrap.dedent(body)


_SRC_FILES = {"pkg/__init__.py": ""}
_TEST_FILES = {"test_smoke.py": "def test_ok() -> None:\n    assert True\n"}
_FEATURE = """\
Feature: checkout

  @req-checkout
  Scenario: paid order succeeds
    Given buyer has cart
    When buyer pays
    Then order is created
"""
_UNTRACED_FEATURE = """\
Feature: checkout

  Scenario: paid order succeeds
    Given buyer has cart
    When buyer pays
    Then order is created
"""
_WORKFLOW = """\
name: ci
on: [push]
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - run: uv run interlocks ci
"""


_SENTINEL = object()


# lizard forgives the parameter count - test scaffolding helper, each kwarg
# names an independent toggle and bundling them obscures call sites.
def _project(
    make_tmp_project: TmpProjectFactory,
    *,
    pyproject: str | None = None,
    src_files: dict[str, str] | None = None,
    test_files: dict[str, str] | None = None,
    feature: str | None = _FEATURE,
    workflow: str | None = _WORKFLOW,
    trace_map: object = _SENTINEL,
) -> Path:
    project = make_tmp_project(
        pyproject=_pyproject() if pyproject is None else pyproject,
        src_files=_SRC_FILES if src_files is None else src_files,
        test_files=_TEST_FILES if test_files is None else test_files,
    )
    if feature is not None:
        feature_path = project / "tests" / "features" / "checkout.feature"
        feature_path.parent.mkdir(parents=True, exist_ok=True)
        feature_path.write_text(textwrap.dedent(feature), encoding="utf-8")
    if workflow is not None:
        workflow_path = project / ".github" / "workflows" / "ci.yml"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(textwrap.dedent(workflow), encoding="utf-8")
    _write_ci_evidence(project)
    if trace_map is _SENTINEL:
        # Default: trace map matches the public surface so the acceptance item
        # scores 3 unless the test explicitly opts out by passing trace_map=None.
        _write_trace_map(project, traced_index=_default_traced_index(project))
    elif trace_map is not None:
        assert isinstance(trace_map, list)
        _write_trace_map(project, traced_index=trace_map)
    return project


def _default_traced_index(project: Path) -> list[str]:
    """Return the trace-map index that matches the empty `pkg` source tree."""
    return []


def _write_trace_map(project: Path, *, traced_index: list[str]) -> None:
    path = project / ".interlocks" / "trace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "computed_at": "2026-04-28T12:00:00Z",
        "scenarios": {},
        "traced_symbols_index": traced_index,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_ci_evidence(
    project: Path,
    *,
    elapsed_seconds: float = 30.0,
    created_at: float | None = None,
    passed: bool = True,
) -> None:
    path = project / ".interlocks" / "ci.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "command": "interlocks ci",
        "elapsed_seconds": elapsed_seconds,
        "created_at": time.time() if created_at is None else created_at,
        "passed": passed,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _report_for(project: Path, monkeypatch: pytest.MonkeyPatch) -> evaluate_mod.EvaluationReport:
    monkeypatch.chdir(project)
    return evaluate(load_config())


def _item(cfg: InterlockConfig, category: str) -> EvaluationItem:
    report = evaluate(cfg)
    return next(item for item in report.items if item.category == category)


def test_all_pass_project_scores_33_of_33(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report_for(_project(make_tmp_project), monkeypatch)

    assert report.total == 33
    assert report.max_total == 33
    assert report.verdict == "HEALTHY"
    assert all(item.score == 3 for item in report.items)


def test_missing_trace_map_scores_acceptance_zero_with_baseline_hint(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, trace_map=None)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 0
    assert item.next_action == "Run `interlocks acceptance baseline` to seed it."
    assert item.detail.startswith("No trace map at ")


def test_acceptance_disabled_scores_as_not_ci_wired(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\nacceptance_runner = "off"\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert item.next_action == (
        "Enable acceptance runner so `interlocks ci` can run feature scenarios."
    )


# ─────────────── trace-map completeness scoring (D10 / spec § 9) ──────────


_PUBLIC_SRC_FILES = {
    "pkg/__init__.py": "",
    "pkg/api.py": "def alpha() -> int:\n    return 1\n\n\ndef beta() -> int:\n    return 2\n",
}


def test_full_trace_map_scores_acceptance_three(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        src_files=_PUBLIC_SRC_FILES,
        trace_map=["pkg.api:alpha", "pkg.api:beta"],
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 3
    assert item.next_action is None
    assert "Trace map covers all 2 public symbol(s)" in item.detail


def test_partial_trace_map_scores_acceptance_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        src_files=_PUBLIC_SRC_FILES,
        trace_map=["pkg.api:alpha"],
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 2
    assert item.detail == "1/2 public symbol(s) traced."
    assert item.next_action is not None
    assert "interlocks acceptance baseline --force" in item.next_action


def test_empty_trace_map_scores_acceptance_one(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        src_files=_PUBLIC_SRC_FILES,
        trace_map=[],
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert item.detail == "Trace map exists but no symbols recorded."
    assert item.next_action == "Run `interlocks acceptance` to populate the trace map."


def test_missing_trace_map_scores_acceptance_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        src_files=_PUBLIC_SRC_FILES,
        trace_map=None,
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 0
    assert item.next_action == "Run `interlocks acceptance baseline` to seed it."
    assert "trace.json" in item.detail


def test_req_markers_no_longer_affect_acceptance_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two scenarios that differ only in `# req:` / `@req-*` markers score identically."""
    feature_with_markers = """\
    Feature: api

      @req-alpha
      Scenario: alpha is reachable
        Given the api is loaded
        When I call alpha
        Then a value is returned

      # req: beta
      Scenario: beta is reachable
        Given the api is loaded
        When I call beta
        Then a value is returned
    """
    feature_without_markers = """\
    Feature: api

      Scenario: alpha is reachable
        Given the api is loaded
        When I call alpha
        Then a value is returned

      Scenario: beta is reachable
        Given the api is loaded
        When I call beta
        Then a value is returned
    """
    traced = ["pkg.api:alpha", "pkg.api:beta"]

    with_markers = _project(
        make_tmp_project,
        src_files=_PUBLIC_SRC_FILES,
        feature=feature_with_markers,
        trace_map=traced,
    )
    monkeypatch.chdir(with_markers)
    score_with = _item(load_config(), "acceptance").score

    without_markers = _project(
        make_tmp_project,
        src_files=_PUBLIC_SRC_FILES,
        feature=feature_without_markers,
        trace_map=traced,
    )
    monkeypatch.chdir(without_markers)
    score_without = _item(load_config(), "acceptance").score

    assert score_with == score_without == 3


def test_missing_tests_lowers_unit_test_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, test_files={})
    monkeypatch.chdir(project)

    item = _item(load_config(), "unit-tests")

    assert item.score == 0
    assert "Add test_*.py" in (item.next_action or "")


def test_coveragerc_branch_setting_is_read_when_pyproject_coverage_absent(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        '[tool.coverage.run]\nsource = ["pkg"]\nbranch = true\n\n',
        "",
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    (project / ".coveragerc").write_text("[run]\nbranch = false\n", encoding="utf-8")
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 2
    assert item.next_action == "Enable branch coverage in [tool.coverage.run]."


def test_coverage_min_zero_scores_coverage_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'preset = "strict"\n',
        'preset = "strict"\ncoverage_min = 0\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 0
    assert item.next_action == "Set coverage_min to at least 80."


def test_coverage_min_below_80_scores_coverage_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'preset = "strict"\n',
        'preset = "strict"\ncoverage_min = 79\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 2
    assert item.next_action == "Raise coverage_min to at least 80."


def test_missing_branch_coverage_lowers_coverage_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, pyproject=_pyproject(branch=False))
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 2
    assert item.next_action == "Enable branch coverage in [tool.coverage.run]."


def test_missing_mutmut_config_lowers_mutation_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        '[tool.mutmut]\npaths_to_mutate = ["pkg/"]\ntests_dir = ["tests/"]\n',
        "",
    )
    project = _project(make_tmp_project, pyproject=pyproject, test_files={})
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 0
    assert "[tool.mutmut]" in (item.next_action or "")


def test_mutation_ci_without_enforcement_scores_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\nenforce_mutation = false\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 2
    assert item.next_action == "Set enforce_mutation = true and mutation_min_score > 0."


def test_mutation_off_lowers_mutation_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        pyproject=_pyproject(mutation_mode="off", run_mutation_in_ci=False),
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 1
    assert item.next_action == 'Set mutation_ci_mode = "incremental" or "full".'


def test_advisory_crap_lowers_complexity_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\nenforce_crap = false\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "complexity")

    assert item.score == 2
    assert item.next_action == "Set enforce_crap = true."


def test_missing_complexity_thresholds_score_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\ncomplexity_max_ccn = 0\ncomplexity_max_args = 0\n'
        "complexity_max_loc = 0\ncrap_max = 0\n",
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "complexity")

    assert item.score == 0
    assert item.next_action == "Set positive complexity_max_* and crap_max thresholds."


def test_missing_import_linter_contracts_lowers_dependency_rules_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, pyproject=_pyproject(importlinter=False))
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps")

    assert item.score == 0
    assert "importlinter" in (item.next_action or "")


def test_default_arch_contract_scores_dependency_rules_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        pyproject=_pyproject(importlinter=False),
        test_files={"__init__.py": "", **_TEST_FILES},
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps")

    assert item.score == 2
    assert item.next_action == "Add forbidden, layers, or acyclic import-linter contracts."


def test_import_linter_sidecar_contract_scores_dependency_rules_three(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, pyproject=_pyproject(importlinter=False))
    (project / ".importlinter").write_text(
        textwrap.dedent(
            """\
            [importlinter]
            root_package = pkg

            [importlinter:contract:no-tests]
            name = Production does not import tests
            type = forbidden
            source_modules = pkg
            forbidden_modules = tests
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps")

    assert item.score == 3


def test_audit_absent_from_ci_lowers_security_score(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from interlocks.tasks import evaluate as evaluate_mod

    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        evaluate_mod,
        "_ci_source_contains",
        lambda needle: needle != "task_audit(",
    )

    item = _item(load_config(), "security")

    assert item.score == 2
    assert item.next_action == "Wire task_audit() into `interlocks ci`."


def test_audit_not_exposed_scores_security_zero(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(evaluate_mod, "_cli_source_contains", lambda _needle: False)

    item = _item(load_config(), "security")

    assert item.score == 0
    assert item.next_action == "Expose `interlocks audit` and task_audit()."


def test_deps_absent_from_ci_lowers_security_score(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        evaluate_mod,
        "_ci_source_contains",
        lambda needle: needle != "task_deps(",
    )

    item = _item(load_config(), "security")

    assert item.score == 2
    assert item.next_action == "Wire task_deps() into `interlocks ci`."


# ─────────────── added gap-closure policies ─────────────────────


def test_dependency_freshness_absent_policy_scores_separately(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace("evaluate_dependency_freshness = true\n", "")
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps-freshness")

    assert item.score == 0
    assert item.next_action is not None
    assert "interlocks deps-freshness" in item.next_action
    assert _item(load_config(), "security").score == 3


def test_dependency_freshness_configured_scores_without_live_lookup(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks import deps_freshness as deps_freshness_mod

    def fail_if_called(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("evaluate must not perform package-index lookup")

    monkeypatch.setattr(deps_freshness_mod, "freshness_cmd", fail_if_called)
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps-freshness")

    assert item.score == 3


def test_audit_severity_missing_threshold_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace('audit_severity_threshold = "high"\n', "")
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "audit-severity")

    assert item.score == 2
    assert item.next_action == (
        'Set audit_severity_threshold = "high" for explicit high-severity policy.'
    )


def test_audit_severity_configured_scores_full(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)

    item = _item(load_config(), "audit-severity")

    assert item.score == 3


def test_audit_severity_without_audit_scores_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(evaluate_mod, "_cli_source_contains", lambda _needle: False)

    item = _item(load_config(), "audit-severity")

    assert item.score == 0
    assert item.next_action == "Expose `interlocks audit` before configuring severity policy."


def test_pr_speed_missing_budget_scores_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace("pr_ci_runtime_budget_seconds = 600\n", "")
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 0
    assert item.next_action == (
        "Set pr_ci_runtime_budget_seconds to declare the PR CI runtime budget."
    )


def test_pr_speed_budget_without_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    (project / ".interlocks" / "ci.json").unlink()
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action is not None
    assert "write timing evidence" in item.next_action


def test_pr_speed_stale_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    _write_ci_evidence(project, created_at=time.time() - 25 * 3600)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action is not None
    assert "Refresh stale CI timing evidence" in item.next_action


def test_pr_speed_passing_evidence_scores_full(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 3


def test_pr_speed_failing_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    _write_ci_evidence(project, passed=False)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action == "Fix failing `interlocks ci` evidence before scoring PR speed."


def test_closure_guidance_covers_task_stage_and_standalone_paths(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        pyproject=_pyproject(mutation_mode="off")
        .replace("evaluate_dependency_freshness = true\n", "")
        .replace(
            'preset = "strict"\n',
            'preset = "strict"\ncoverage_min = 0\nenforce_mutation = false\n',
        ),
        feature=_UNTRACED_FEATURE,
        trace_map=None,  # force missing-trace-map branch so acceptance has a closure
    )
    monkeypatch.chdir(project)
    cfg = load_config()

    acceptance = _item(cfg, "acceptance")
    coverage = _item(cfg, "coverage")
    mutation = _item(cfg, "mutation")
    freshness = _item(cfg, "deps-freshness")

    assert acceptance.closure is not None
    assert acceptance.closure.command == "interlocks acceptance baseline"
    assert acceptance.closure.kind == "task"
    assert "trace.json" in acceptance.closure.rationale
    assert coverage.closure is not None
    assert coverage.closure.command == "interlocks ci"
    assert coverage.closure.kind == "stage"
    assert mutation.closure is not None
    assert mutation.closure.command == "interlocks nightly"
    assert mutation.closure.kind == "stage"
    assert freshness.closure is not None
    assert freshness.closure.command == "interlocks deps-freshness"
    assert freshness.closure.kind == "task"


def test_next_actions_include_closure_command(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(make_tmp_project, feature=_UNTRACED_FEATURE, trace_map=None)
    monkeypatch.chdir(project)

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "[acceptance] Run `interlocks acceptance baseline`" in out
    assert "Close with `interlocks acceptance baseline` (task)" in out


def test_action_workflow_without_local_command_scores_ci_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = """\
    name: ci
    on: [push]
    jobs:
      ci:
        runs-on: ubuntu-latest
        steps:
          - uses: 0xjgv/interlocks@v1
    """
    project = _project(make_tmp_project, workflow=workflow)
    monkeypatch.chdir(project)

    item = _item(load_config(), "ci")

    assert item.score == 2
    assert item.next_action == "Make workflow command explicitly reproducible as `interlocks ci`."


def test_unrelated_workflow_scores_ci_one(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = """\
    name: ci
    on: [push]
    jobs:
      ci:
        runs-on: ubuntu-latest
        steps:
          - run: pytest
    """
    project = _project(make_tmp_project, workflow=workflow)
    monkeypatch.chdir(project)

    item = _item(load_config(), "ci")

    assert item.score == 1
    assert item.next_action == "Add `interlocks ci` to a GitHub Actions workflow."


def test_source_contains_returns_false_for_missing_file(tmp_path: Path) -> None:
    assert evaluate_mod._source_contains(tmp_path / "missing.py", "needle") is False


def test_verdicts_cover_all_bands() -> None:
    assert evaluate_mod._verdict(33, 33) == "HEALTHY"
    assert evaluate_mod._verdict(23, 33) == "GAPS"
    assert evaluate_mod._verdict(0, 33) == "NEEDS WORK"
    assert evaluate_mod._verdict(0, 0) == "NEEDS WORK"


def test_workflow_missing_interlocks_ci_lowers_ci_enforcement_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, workflow=None)
    monkeypatch.chdir(project)

    item = _item(load_config(), "ci")

    assert item.score == 0
    assert item.next_action == "Add .github/workflows CI that runs `interlocks ci`."


def test_cmd_evaluate_handles_malformed_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [valid\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "command=evaluate" in out
    assert "pyproject.toml unreadable" in out
    assert "0 / 33" in out


def test_cmd_evaluate_prints_report_sections(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(make_tmp_project, feature=None, workflow=None)
    monkeypatch.chdir(project)

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "command=evaluate" in out
    assert "── Checklist" in out
    assert "── Score" in out
    assert "── Next Actions" in out
    assert "total" in out


def test_cmd_evaluate_exits_zero_even_for_low_score(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(make_tmp_project, test_files={}, feature=None, workflow=None)
    monkeypatch.chdir(project)

    cmd_evaluate()
