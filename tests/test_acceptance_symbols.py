"""Tests for ``interlocks.acceptance_symbols.iter_public_symbols``."""

from __future__ import annotations

import sys
import textwrap
from dataclasses import replace

import pytest

from interlocks.acceptance_symbols import iter_public_symbols
from interlocks.config import InterlockConfig, load_config
from tests.conftest import TmpProjectFactory


def _pyproject(pkg_name: str) -> str:
    """Pyproject placing ``src_dir`` at the project root (top-level package layout)."""
    return textwrap.dedent(
        f"""\
        [project]
        name = "{pkg_name}"
        version = "0.0.0"
        requires-python = ">=3.13"

        [tool.interlocks]
        src_dir = "{pkg_name}"
        """
    )


def _make_project(
    make_tmp_project: TmpProjectFactory,
    pkg_name: str,
    src_files: dict[str, str],
) -> InterlockConfig:
    project = make_tmp_project(
        pyproject=_pyproject(pkg_name),
        src_files=src_files,
        test_files={},
    )
    cfg = load_config(project)
    return replace(cfg, project_root=project, src_dir=project / pkg_name)


@pytest.fixture(autouse=True)
def _purge_synthetic_modules() -> None:
    """Drop ``pkg_*`` modules from ``sys.modules`` so per-test packages stay isolated."""
    yield
    for name in list(sys.modules):
        if name.startswith("pkg_"):
            sys.modules.pop(name, None)


def test_top_level_public_function_included(make_tmp_project: TmpProjectFactory) -> None:
    cfg = _make_project(
        make_tmp_project,
        "pkg_func",
        {
            "pkg_func/__init__.py": "",
            "pkg_func/cmd.py": "def cmd_check() -> None:\n    return None\n",
        },
    )
    symbols = set(iter_public_symbols(cfg))
    assert ("pkg_func.cmd", "cmd_check") in symbols


def test_underscore_prefixed_attribute_excluded(make_tmp_project: TmpProjectFactory) -> None:
    cfg = _make_project(
        make_tmp_project,
        "pkg_priv",
        {
            "pkg_priv/__init__.py": "",
            "pkg_priv/util.py": (
                "def public() -> None:\n    return None\n\n\n"
                "def _helper() -> None:\n    return None\n"
            ),
        },
    )
    symbols = set(iter_public_symbols(cfg))
    assert ("pkg_priv.util", "public") in symbols
    assert ("pkg_priv.util", "_helper") not in symbols


def test_public_class_included_with_no_method_entries(
    make_tmp_project: TmpProjectFactory,
) -> None:
    cfg = _make_project(
        make_tmp_project,
        "pkg_cls",
        {
            "pkg_cls/__init__.py": "",
            "pkg_cls/pipe.py": (
                "class Pipeline:\n"
                "    def run(self) -> None:\n"
                "        return None\n\n"
                "    def stop(self) -> None:\n"
                "        return None\n"
            ),
        },
    )
    symbols = set(iter_public_symbols(cfg))
    assert ("pkg_cls.pipe", "Pipeline") in symbols
    method_entries = {entry for entry in symbols if entry[1] in {"run", "stop"}}
    assert method_entries == set()


def test_reexported_symbol_attributed_to_origin_only(
    make_tmp_project: TmpProjectFactory,
) -> None:
    cfg = _make_project(
        make_tmp_project,
        "pkg_reexport",
        {
            "pkg_reexport/__init__.py": "",
            "pkg_reexport/b.py": "def foo() -> None:\n    return None\n",
            "pkg_reexport/a.py": "from pkg_reexport.b import foo\n",
        },
    )
    symbols = set(iter_public_symbols(cfg))
    assert ("pkg_reexport.b", "foo") in symbols
    assert ("pkg_reexport.a", "foo") not in symbols


def test_import_failing_module_skipped_with_stderr_nudge(
    make_tmp_project: TmpProjectFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = _make_project(
        make_tmp_project,
        "pkg_broken",
        {
            "pkg_broken/__init__.py": "",
            "pkg_broken/ok.py": "def ok_fn() -> None:\n    return None\n",
            "pkg_broken/bad.py": "raise ImportError('synthetic boom')\n",
        },
    )
    symbols = set(iter_public_symbols(cfg))
    captured = capsys.readouterr()

    assert ("pkg_broken.ok", "ok_fn") in symbols
    assert all(qualname != "pkg_broken.bad" for qualname, _ in symbols)
    assert "interlocks: skipping pkg_broken.bad: synthetic boom" in captured.err


def test_non_import_error_at_import_time_skipped(
    make_tmp_project: TmpProjectFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Index/Type/etc. errors raised at module top-level should also be skipped.

    The enumerator widened ``except ImportError`` → ``except Exception`` because
    pytest-bdd-style scaffolds (e.g. ``scenarios()`` outside a session) raise
    non-ImportError exceptions at import time. This test locks in that wider
    contract so the enumerator can't quietly narrow back without a tripwire.
    """
    cfg = _make_project(
        make_tmp_project,
        "pkg_index_boom",
        {
            "pkg_index_boom/__init__.py": "",
            "pkg_index_boom/ok.py": "def ok_fn() -> None:\n    return None\n",
            "pkg_index_boom/bad.py": "STACK: list[int] = []\n_ = STACK[-1]\n",
        },
    )
    symbols = set(iter_public_symbols(cfg))
    captured = capsys.readouterr()

    assert ("pkg_index_boom.ok", "ok_fn") in symbols
    assert all(qualname != "pkg_index_boom.bad" for qualname, _ in symbols)
    assert "interlocks: skipping pkg_index_boom.bad" in captured.err
