"""Integration tests for harness.tasks.typecheck.

``cmd_typecheck`` targets whatever ``load_config().src_dir`` resolves to. The
fixture here creates a flat ``harness/`` package so autodetect picks it up. A
subprocess with ``cwd=tmp_project`` would find the tmp dir's ``harness/``
before the installed package (ModuleNotFoundError on ``harness.cli``), so we
invoke the function directly under ``monkeypatch.chdir``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.basedpyright]
    pythonVersion = "3.13"
    typeCheckingMode = "standard"
    reportMissingTypeStubs = false
""")

CLEAN = "def add(a: int, b: int) -> int:\n    return a + b\n"
VIOLATING = "def bad() -> int:\n    return 'not an int'\n"  # return-type mismatch


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "harness"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_typecheck_clean_exits_zero(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.tasks.typecheck import cmd_typecheck

    (tmp_project / "harness" / "mod.py").write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_typecheck()  # returns without raising SystemExit


def test_typecheck_violating_exits_nonzero(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.tasks.typecheck import cmd_typecheck

    (tmp_project / "harness" / "mod.py").write_text(VIOLATING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as excinfo:
        cmd_typecheck()
    assert excinfo.value.code != 0
