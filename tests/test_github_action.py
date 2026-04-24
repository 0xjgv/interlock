"""Tests for the reusable GitHub Action helper and metadata."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from interlock import github_action


def test_command_from_args_defaults_to_interlock_ci() -> None:
    assert github_action._command_from_args(()) == ["interlock", "ci"]


def test_command_from_args_accepts_command_override() -> None:
    assert github_action._command_from_args(("--command", "interlock ci --verbose")) == [
        "interlock",
        "ci",
        "--verbose",
    ]


def test_write_summary_records_command_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    github_action.write_summary(["interlock", "ci"], 0)

    assert summary.read_text(encoding="utf-8") == (
        "## interlock CI\n\n- Command: `interlock ci`\n- Result: passed\n"
    )


def test_write_summary_records_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    github_action.write_summary(["interlock", "ci"], 2)

    assert "- Result: failed (exit 2)" in summary.read_text(encoding="utf-8")


def test_write_summary_noops_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    github_action.write_summary(["interlock", "ci"], 0)

    assert not list(tmp_path.iterdir())


def test_main_exits_with_command_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check is False
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(github_action.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        github_action.main(["--command", "interlock ci"])

    assert exc.value.code == 7
    assert calls == [["interlock", "ci"]]
    assert "- Result: failed (exit 7)" in summary.read_text(encoding="utf-8")


def test_action_metadata_delegates_to_interlock_ci() -> None:
    action = (Path(__file__).resolve().parent.parent / "action.yml").read_text(encoding="utf-8")

    assert "using: composite" in action
    assert "actions/setup-python@v5" in action
    assert "default: python -m pip install interlock" in action
    assert "default: interlock ci" in action
    assert 'python -m interlock.github_action --command "${{ inputs.command }}"' in action
    assert "ruff" not in action
    assert "coverage run" not in action
