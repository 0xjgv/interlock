"""Integration tests for harness.tasks.lint."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.ruff]
    target-version = "py313"
    line-length = 99

    [tool.ruff.lint]
    select = ["E", "F"]
""")

CLEAN = "x = 1\n"
VIOLATING = "x = y\n"  # F821 undefined-name


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("source", "expected_rc"), [(CLEAN, 0), (VIOLATING, 1)])
def test_lint_cli(tmp_project: Path, source: str, expected_rc: int) -> None:
    (tmp_project / "sample.py").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "lint"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc
