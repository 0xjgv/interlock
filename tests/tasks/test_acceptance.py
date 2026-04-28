"""Integration + unit tests for `interlocks acceptance`."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "acc-probe"
    version = "0.0.0"
    requires-python = ">=3.13"
    """
)

_PASSING_FEATURE = textwrap.dedent(
    """\
    Feature: Math sanity
      Scenario: Two plus three
        Given the number 2
        When I add 3
        Then the result is 5
    """
)

_FAILING_FEATURE = textwrap.dedent(
    """\
    Feature: Math sanity
      Scenario: Broken addition
        Given the number 2
        When I add 3
        Then the result is 99
    """
)

_STEP_DEFS = textwrap.dedent(
    """\
    from pytest_bdd import given, parsers, scenarios, then, when

    scenarios("../features/example.feature")


    @given(parsers.parse("the number {value:d}"), target_fixture="value")
    def _value(value):
        return value


    @when(parsers.parse("I add {addend:d}"), target_fixture="result")
    def _add(value, addend):
        return value + addend


    @then(parsers.parse("the result is {expected:d}"))
    def _check(result, expected):
        assert result == expected
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    return tmp_path


def _run_cli(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


def test_acceptance_noop_without_features(tmp_project: Path) -> None:
    """Empty foreign project: exit 0 + skip nudge, never a crash."""
    result = _run_cli(tmp_project, "acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "acceptance:" in result.stdout


def _scaffold_feature(project: Path, feature_body: str) -> None:
    (project / "tests" / "features").mkdir(parents=True)
    (project / "tests" / "features" / "example.feature").write_text(feature_body, encoding="utf-8")
    (project / "tests" / "step_defs").mkdir()
    (project / "tests" / "step_defs" / "test_example.py").write_text(_STEP_DEFS, encoding="utf-8")


@pytest.mark.slow
def test_acceptance_passes_on_valid_scenario(tmp_project: Path) -> None:
    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    result = _run_cli(tmp_project, "acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "[acceptance]" in result.stdout


@pytest.mark.slow
def test_acceptance_fails_on_broken_scenario(tmp_project: Path) -> None:
    _scaffold_feature(tmp_project, _FAILING_FEATURE)
    result = _run_cli(tmp_project, "acceptance")
    assert result.returncode != 0


def test_task_acceptance_returns_none_without_features(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    monkeypatch.chdir(tmp_project)
    clear_cache()
    assert mod.task_acceptance() is None


def test_task_acceptance_pytest_bdd_allows_rc_5(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pytest exits 5 when it collects nothing — must be treated as pass."""
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    monkeypatch.chdir(tmp_project)
    clear_cache()
    task = mod.task_acceptance()
    assert task is not None
    assert task.description == "Acceptance (pytest-bdd)"
    assert 5 in task.allowed_rcs


def test_task_acceptance_off_override_skips(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    (tmp_project / "tests" / "features").mkdir(parents=True)
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + '\n[tool.interlocks]\nacceptance_runner = "off"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    clear_cache()
    assert mod.task_acceptance() is None


def test_task_acceptance_behave_branch(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    features = tmp_project / "features"
    (features / "steps").mkdir(parents=True)
    (features / "environment.py").write_text("", encoding="utf-8")
    (features / "smoke.feature").write_text(_PASSING_FEATURE, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    clear_cache()
    task = mod.task_acceptance()
    assert task is not None
    assert task.description == "Acceptance (behave)"
    assert "behave" in task.cmd


def test_cmd_acceptance_optional_missing_warns_and_exits_zero(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Default policy: missing features/ → skip nudge, no SystemExit, exit 0."""
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    monkeypatch.chdir(tmp_project)
    clear_cache()

    called: list[object] = []
    monkeypatch.setattr(mod, "run", called.append)

    mod.cmd_acceptance()

    out = capsys.readouterr().out
    assert "no features/ directory" in out
    assert "interlocks init-acceptance" in out
    assert called == []


def test_cmd_acceptance_required_missing_exits_one(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`require_acceptance = true` + missing features/ → SystemExit(1) with remediation."""
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\nrequire_acceptance = true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    clear_cache()

    with pytest.raises(SystemExit) as exc:
        mod.cmd_acceptance()
    assert exc.value.code == 1
    assert "interlocks init-acceptance" in capsys.readouterr().out


def test_cmd_acceptance_runnable_calls_run(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RUNNABLE classification → run(task_acceptance()) with the pytest-bdd description."""
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    monkeypatch.chdir(tmp_project)
    clear_cache()

    called: list[object] = []
    monkeypatch.setattr(mod, "run", called.append)

    mod.cmd_acceptance()

    assert len(called) == 1
    task = called[0]
    assert hasattr(task, "description")
    assert task.description == "Acceptance (pytest-bdd)"  # type: ignore[attr-defined]


# ── Section 4 wiring: trace plugin env signals ─────────────────────────────


def test_pytest_bdd_task_sets_trace_env_signals(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_pytest_bdd_task` returns a Task whose env carries trace-plugin signals.

    Section 4.1 — the pytest subprocess inherits env via `Task.env`; the
    trace plugin (auto-loaded via the `pytest11` entry-point) is inert
    unless `INTERLOCKS_TRACE=1`.
    """
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    monkeypatch.chdir(tmp_project)
    clear_cache()

    task = mod.task_acceptance()
    assert task is not None
    assert task.env is not None
    assert task.env["INTERLOCKS_TRACE"] == "1"
    # Path must be absolute (resolved against project_root) so subprocess
    # CWD changes do not relocate the trace map.
    trace_path = Path(task.env["INTERLOCKS_TRACE_PATH"])
    assert trace_path.is_absolute()
    assert trace_path.name == "trace.json"
    # Src prefix matches `cfg.src_dir.name`; in this fixture there is no
    # explicit package layout so it resolves to the tmp project dir name.
    assert task.env["INTERLOCKS_TRACE_SRC_PREFIX"]
    assert task.env["INTERLOCKS_TRACE_SRC_PREFIX"] == tmp_project.name


def test_pytest_bdd_task_does_not_inject_dash_p_flag(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No redundant `-p interlocks.acceptance_trace_plugin` — entry-point auto-loads.

    Section 4.1 design choice: the `pytest11` entry-point in pyproject.toml
    handles plugin registration; an explicit `-p` would be redundant and
    fragile (needs `-p no:cacheprovider`-style escaping in some pytest
    configs). Env gating (`INTERLOCKS_TRACE=1`) is what activates the
    recorder, not flag presence.
    """
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    monkeypatch.chdir(tmp_project)
    clear_cache()

    task = mod.task_acceptance()
    assert task is not None
    assert "-p" not in task.cmd
    assert "interlocks.acceptance_trace_plugin" not in task.cmd


def test_pytest_bdd_task_keeps_cov_flag_under_option_a(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Option A (sys.monitoring) coexists with coverage; do not strip `--cov`.

    Section 4.2 — Option B's `--cov` stripping is moot under the project's
    Python ≥3.13 minimum because the trace plugin claims a distinct
    sys.monitoring tool ID. Coverage.py and the recorder observe events
    independently. If a project sets `--cov` via `pytest_args`, the flag
    is forwarded verbatim.
    """
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT
        + '\n[tool.interlocks]\npytest_args = ["--cov=acc_probe", "--cov-report=term"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    clear_cache()

    task = mod.task_acceptance()
    assert task is not None
    assert "--cov=acc_probe" in task.cmd
    assert "--cov-report=term" in task.cmd


def test_behave_task_omits_trace_env_signals(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behave runner has no trace-plugin support → no env signals leak in.

    Section 4.3 — behave is not a pytest invocation; the trace plugin
    cannot record there. Keep `Task.env` as None (or trace-free) so we do
    not advertise a feature we cannot deliver.
    """
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    features = tmp_project / "features"
    (features / "steps").mkdir(parents=True)
    (features / "environment.py").write_text("", encoding="utf-8")
    (features / "smoke.feature").write_text(_PASSING_FEATURE, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    clear_cache()

    task = mod.task_acceptance()
    assert task is not None
    assert task.description == "Acceptance (behave)"
    # Either None or a dict with no trace keys — both are acceptable; the
    # invariant is: no INTERLOCKS_TRACE signal goes to behave.
    if task.env is not None:
        assert "INTERLOCKS_TRACE" not in task.env


def test_cmd_acceptance_behave_prints_nudge_to_stderr(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Section 4.3 — behave path must name the dark-gate nudge on stderr.

    Per spec D11 / acceptance-symbol-trace requirement "Behave runner gap
    is named, not silent": the nudge string identifies the gap so adopters
    do not silently lose budget enforcement.
    """
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    features = tmp_project / "features"
    (features / "steps").mkdir(parents=True)
    (features / "environment.py").write_text("", encoding="utf-8")
    (features / "smoke.feature").write_text(_PASSING_FEATURE, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    clear_cache()

    monkeypatch.setattr(mod, "run", lambda _task: None)
    mod.cmd_acceptance()

    captured = capsys.readouterr()
    assert "behave runner: trace recording unavailable (pytest-bdd only)" in captured.err


def test_cmd_acceptance_pytest_bdd_does_not_print_behave_nudge(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The behave nudge belongs to the behave path only — pytest-bdd is silent."""
    from interlocks.config import clear_cache
    from interlocks.tasks import acceptance as mod

    _scaffold_feature(tmp_project, _PASSING_FEATURE)
    monkeypatch.chdir(tmp_project)
    clear_cache()

    monkeypatch.setattr(mod, "run", lambda _task: None)
    mod.cmd_acceptance()

    captured = capsys.readouterr()
    assert "behave runner" not in captured.err
