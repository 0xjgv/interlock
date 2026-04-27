"""Tests for static `interlocks evaluate` report."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from interlocks.config import InterlockConfig, load_config
from interlocks.tasks import evaluate as evaluate_mod
from interlocks.tasks.evaluate import EvaluationItem, cmd_evaluate, evaluate
from tests.conftest import TmpProjectFactory


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


def _project(
    make_tmp_project: TmpProjectFactory,
    *,
    pyproject: str | None = None,
    test_files: dict[str, str] | None = None,
    feature: str | None = _FEATURE,
    workflow: str | None = _WORKFLOW,
) -> Path:
    project = make_tmp_project(
        pyproject=_pyproject() if pyproject is None else pyproject,
        src_files=_SRC_FILES,
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
    return project


def _report_for(project: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(project)
    return evaluate(load_config())


def _item(cfg: InterlockConfig, category: str) -> EvaluationItem:
    report = evaluate(cfg)
    return next(item for item in report.items if item.category == category)


def test_all_pass_project_scores_24_of_24(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report_for(_project(make_tmp_project), monkeypatch)

    assert report.total == 24
    assert report.max_total == 24
    assert report.verdict == "HEALTHY"
    assert all(item.score == 3 for item in report.items)


def test_comment_before_scenario_counts_as_traceability(tmp_path: Path) -> None:
    feature = tmp_path / "checkout.feature"
    feature.write_text(
        textwrap.dedent(
            """\
            Feature: checkout

              # req: checkout-paid
              Scenario: paid order succeeds
                Given buyer has cart
            """
        ),
        encoding="utf-8",
    )

    assert evaluate_mod._feature_scenarios_with_traceability(feature) == (1, 1)


def test_missing_feature_files_scores_acceptance_lower_and_emits_next_action(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, feature=None)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 0
    assert item.next_action == "Run `interlocks init-acceptance` to scaffold feature files."


def test_feature_file_with_no_scenarios_scores_acceptance_one(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, feature="Feature: checkout\n")
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert "Add at least one Scenario" in (item.next_action or "")


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


def test_scenario_without_traceability_tag_lowers_acceptance_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, feature=_UNTRACED_FEATURE)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert item.next_action is not None
    assert "@req-*" in item.next_action


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
    assert evaluate_mod._verdict(24, 24) == "HEALTHY"
    assert evaluate_mod._verdict(17, 24) == "GAPS"
    assert evaluate_mod._verdict(0, 24) == "NEEDS WORK"
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
    assert "0 / 24" in out


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
