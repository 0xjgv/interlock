"""Integration test for `cmd_mutation` — advisory mutation score via mutmut."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from interlocks import metrics as metrics_mod
from interlocks.tasks.mutation import (
    _mutant_in_changed,
    _print_survivors,
    cmd_mutation,
)

_MODULE_SRC = textwrap.dedent(
    """\
    def is_positive(x):
        return x > 0
    """
)

_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import is_positive

    class TestIsPositive(unittest.TestCase):
        def test_positive(self):
            self.assertTrue(is_positive(1))
        def test_zero(self):
            self.assertFalse(is_positive(0))
        def test_negative(self):
            self.assertFalse(is_positive(-1))
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "mut-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.mutmut]
    paths_to_mutate = ["mypkg/"]
    tests_dir = ["tests/"]
    """
)


def _run_coverage(cwd: Path) -> None:
    """Run the project's unittest suite under coverage so `.coverage` exists."""
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"]
    subprocess.run(cmd, cwd=cwd, check=True)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Project with `mypkg/mod.py` + covering unittest under `tests/`."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def test_mutation_skips_when_coverage_missing(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No .coverage → cmd_mutation should warn_skip, never SystemExit."""
    monkeypatch.chdir(tmp_project)
    # Defaults (min-coverage=70) apply; no coverage.xml exists → skip path.
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation"])

    cmd_mutation()  # no SystemExit expected

    captured = capsys.readouterr()
    assert "mutation" in captured.out.lower()


@pytest.mark.slow
def test_mutation_runs_and_prints_score(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Happy path: coverage primed, short --max-runtime, mutmut reports a score."""
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    _run_coverage(tmp_project)
    monkeypatch.setattr(
        sys, "argv", ["interlocks", "mutation", "--max-runtime=30", "--min-coverage=0"]
    )

    cmd_mutation()  # advisory — must never SystemExit

    captured = capsys.readouterr()
    assert "Mutation: score" in captured.out


# ─────────────── threshold cascade ─────────────────────


def test_mutation_min_coverage_comes_from_config(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """[tool.interlocks] mutation_min_coverage = 95 → skip message mentions 95.0%."""
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\nmutation_min_coverage = 95\n", encoding="utf-8"
    )
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="0.5"></coverage>')
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation"])

    cmd_mutation()  # advisory — must never SystemExit
    captured = capsys.readouterr()
    assert "95" in captured.out  # threshold surfaced in the skip message


# ─────────────── _mutant_in_changed ─────────────────────


def test_mutant_in_changed_matches_module_path() -> None:
    assert _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"interlocks/git.py"})


def test_mutant_in_changed_handles_nested_modules() -> None:
    assert _mutant_in_changed(
        "interlocks.tasks.mutation.x__parse_results__mutmut_5", {"interlocks/tasks/mutation.py"}
    )


def test_mutant_in_changed_matches_suffix() -> None:
    """Path matches if any changed file ends with '/<module-path>'."""
    assert _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"src/interlocks/git.py"})


def test_mutant_in_changed_misses_unrelated() -> None:
    assert not _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"interlocks/runner.py"})


def test_mutant_in_changed_empty_set_is_miss() -> None:
    assert not _mutant_in_changed("interlocks.git.x_foo__mutmut_1", set())


# ─────────────── _print_survivors ─────────────────────


def test_print_survivors_prints_nothing_when_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors([], None)
    assert capsys.readouterr().out == ""


def test_print_survivors_prints_header_and_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors(["interlocks.a.x__mutmut_1", "interlocks.b.x__mutmut_2"], None)
    out = capsys.readouterr().out
    assert "surviving mutants (2 shown)" in out
    assert "interlocks.a.x__mutmut_1" in out
    assert "interlocks.b.x__mutmut_2" in out


def test_print_survivors_caps_at_twenty(capsys: pytest.CaptureFixture[str]) -> None:
    many = [f"interlocks.a.x__mutmut_{i}" for i in range(30)]
    _print_survivors(many, None)
    out = capsys.readouterr().out
    assert "surviving mutants (20 shown)" in out
    assert "interlocks.a.x__mutmut_0" in out
    assert "interlocks.a.x__mutmut_19" in out
    assert "interlocks.a.x__mutmut_20" not in out


def test_print_survivors_filters_to_changed_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    survivors = ["interlocks.git.x_foo__mutmut_1", "interlocks.runner.x_bar__mutmut_2"]
    _print_survivors(survivors, {"interlocks/git.py"})
    out = capsys.readouterr().out
    assert "interlocks.git.x_foo__mutmut_1" in out
    assert "interlocks.runner.x_bar__mutmut_2" not in out


def test_print_survivors_silent_when_nothing_matches_changed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors(["interlocks.runner.x_foo__mutmut_1"], {"interlocks/git.py"})
    assert capsys.readouterr().out == ""


# ─────────────── coverage fixture (shared with threshold test) ─────────


@pytest.fixture
def primed_coverage_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Return a factory that writes `.coverage` + `coverage.xml` and stubs regeneration."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".coverage").write_text("", encoding="utf-8")
    xml = tmp_path / "coverage.xml"
    monkeypatch.setattr(metrics_mod, "generate_coverage_xml", lambda: xml)

    def _write(body: str) -> Path:
        xml.write_text(body, encoding="utf-8")
        return xml

    return _write
