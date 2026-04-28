"""Tests for `acceptance_trace_path`, `acceptance_budget_path`, `enforce_acceptance_budget`.

Covers task 7.3 of `acceptance-coverage-ratchet`:
- defaults track filesystem presence of the budget file
- explicit `false` overrides auto-detect
- custom paths resolve against the project root and feed auto-detect
- `interlocks config` output advertises all three keys
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from interlocks.config import load_config
from interlocks.tasks.config import cmd_config
from tests.conftest import TmpProjectFactory

_DEFAULT_BUDGET_REL = Path(".interlocks/acceptance_budget.json")
_DEFAULT_TRACE_REL = Path(".interlocks/trace.json")


def _write_budget(root: Path, rel: Path = _DEFAULT_BUDGET_REL) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    return target


def _pyproject_with_interlocks(body: str) -> str:
    return (
        '[project]\nname = "tmpproj"\nversion = "0.0.0"\nrequires-python = ">=3.13"\n\n'
        f"[tool.interlocks]\n{body}\n"
    )


def _src_files() -> Mapping[str, str]:
    return {"src/tmpproj/__init__.py": '"""Tmp project."""\n'}


# ── enforce_acceptance_budget auto-detect ──────────────────────────────


def test_enforce_acceptance_budget_defaults_true_when_budget_file_present(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(src_files=_src_files())
    _write_budget(root)
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.enforce_acceptance_budget is True
    assert cfg.value_sources["enforce_acceptance_budget"] == "auto-detected"


def test_enforce_acceptance_budget_defaults_false_when_budget_file_absent(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(src_files=_src_files())
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.enforce_acceptance_budget is False
    assert cfg.value_sources["enforce_acceptance_budget"] == "auto-detected"


def test_explicit_false_overrides_auto_detect_even_when_file_exists(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(
        src_files=_src_files(),
        pyproject=_pyproject_with_interlocks("enforce_acceptance_budget = false"),
    )
    _write_budget(root)
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.enforce_acceptance_budget is False
    assert cfg.value_sources["enforce_acceptance_budget"] == "project-configured"


def test_explicit_true_recorded_as_project_source(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(
        src_files=_src_files(),
        pyproject=_pyproject_with_interlocks("enforce_acceptance_budget = true"),
    )
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.enforce_acceptance_budget is True
    assert cfg.value_sources["enforce_acceptance_budget"] == "project-configured"


# ── path overrides ────────────────────────────────────────────────────


def test_custom_acceptance_budget_path_resolves_and_feeds_auto_detect(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(
        src_files=_src_files(),
        pyproject=_pyproject_with_interlocks('acceptance_budget_path = ".custom/budget.json"'),
    )
    custom = root / ".custom" / "budget.json"
    custom.parent.mkdir(parents=True)
    custom.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.acceptance_budget_path == custom.resolve()
    assert cfg.value_sources["acceptance_budget_path"] == "project-configured"
    # Auto-detect tracks the custom path, not the default location.
    assert cfg.enforce_acceptance_budget is True
    assert cfg.value_sources["enforce_acceptance_budget"] == "auto-detected"


def test_custom_acceptance_budget_path_auto_detect_false_when_custom_missing(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(
        src_files=_src_files(),
        pyproject=_pyproject_with_interlocks('acceptance_budget_path = ".custom/budget.json"'),
    )
    # Default-location budget exists, but custom path was overridden — auto-detect must
    # follow the configured path, not the default.
    _write_budget(root)
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.acceptance_budget_path == (root / ".custom" / "budget.json").resolve()
    assert cfg.enforce_acceptance_budget is False


def test_custom_acceptance_trace_path_resolves(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(
        src_files=_src_files(),
        pyproject=_pyproject_with_interlocks('acceptance_trace_path = ".custom/trace.json"'),
    )
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.acceptance_trace_path == (root / ".custom" / "trace.json").resolve()
    assert cfg.value_sources["acceptance_trace_path"] == "project-configured"


def test_default_paths_resolve_under_project_root(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tmp_project(src_files=_src_files())
    monkeypatch.chdir(root)

    cfg = load_config()

    assert cfg.acceptance_trace_path == (root / _DEFAULT_TRACE_REL).resolve()
    assert cfg.acceptance_budget_path == (root / _DEFAULT_BUDGET_REL).resolve()
    assert cfg.value_sources["acceptance_trace_path"] == "bundled-default"
    assert cfg.value_sources["acceptance_budget_path"] == "bundled-default"


# ── `interlocks config` rendering ─────────────────────────────────────


def test_cmd_config_lists_all_three_acceptance_budget_keys(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_tmp_project(src_files=_src_files())
    _write_budget(root)
    monkeypatch.chdir(root)

    cmd_config()

    out = capsys.readouterr().out
    # Each key must surface with its name (covers the "Config keys" reference table
    # AND the "Resolved values" block — both render the key name).
    for key in ("acceptance_trace_path", "acceptance_budget_path", "enforce_acceptance_budget"):
        assert key in out
    # Type column for the docs row (doc table renders type after key name).
    assert ".interlocks/trace.json" in out
    assert ".interlocks/acceptance_budget.json" in out
    # Resolved value source surfaces — auto-detect on, file exists.
    assert "True (auto-detected)" in out
    # Description text is present (covers the third doc column).
    assert "Trace map written by `interlocks acceptance`" in out
    assert "Budget file storing the allowed untraced public-symbol set" in out
    assert "Block CI when current untraced symbols exceed the budget" in out
