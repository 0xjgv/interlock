"""Integration tests for interlocks.tasks.typecheck.

``cmd_typecheck`` targets whatever ``load_config().src_dir`` resolves to. The
fixture here creates a flat ``interlocks/`` package so autodetect picks it up. A
subprocess with ``cwd=tmp_project`` would find the tmp dir's ``interlocks/``
before the installed package (ModuleNotFoundError on ``interlocks.cli``), so we
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
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_typecheck_clean_exits_zero(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from interlocks.tasks.typecheck import cmd_typecheck

    (tmp_project / "interlocks" / "mod.py").write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_typecheck()  # returns without raising SystemExit


def test_typecheck_violating_exits_nonzero(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.typecheck import cmd_typecheck

    (tmp_project / "interlocks" / "mod.py").write_text(VIOLATING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as excinfo:
        cmd_typecheck()
    assert excinfo.value.code != 0


# ─────────────── bundled pyrightconfig fallback ─────────────────────

_BARE_PYPROJECT = textwrap.dedent("""\
    [project]
    name = "bare"
    version = "0.0.0"
    requires-python = ">=3.13"
""")


def test_typecheck_injects_bundled_config_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare project: task must pass --project <bundled-pyrightconfig>."""
    from interlocks.tasks.typecheck import task_typecheck

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cmd = task_typecheck().cmd
    assert "--project" in cmd
    cfg_path = Path(cmd[cmd.index("--project") + 1])
    assert cfg_path.name == "pyrightconfig.json"
    assert cfg_path.is_file()


def test_typecheck_omits_config_when_project_has_tool_basedpyright(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[tool.basedpyright] in project pyproject: task must NOT inject --project."""
    from interlocks.tasks.typecheck import task_typecheck

    monkeypatch.chdir(tmp_project)
    assert "--project" not in task_typecheck().cmd


def test_typecheck_omits_config_when_project_has_pyrightconfig_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pyrightconfig.json in project root: task must NOT inject --project."""
    from interlocks.tasks.typecheck import task_typecheck

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text("{}\n", encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "--project" not in task_typecheck().cmd
