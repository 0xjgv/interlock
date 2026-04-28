"""Tests for `interlocks acceptance baseline` and `interlocks acceptance status`.

The subcommands are dispatched inside ``cmd_acceptance`` based on ``sys.argv``;
tests exercise the helpers directly with ``sys.argv`` patched so the dispatch
mirrors a real ``interlocks acceptance baseline`` / ``... status`` invocation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from interlocks.acceptance_budget import (
    Budget,
    derive_repo_secret,
    load_budget,
    verify_signature,
    write_budget,
)
from interlocks.config import clear_cache
from interlocks.tasks import acceptance as mod

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "acc_cli_probe"
    version = "0.0.0"
    requires-python = ">=3.13"
    """
)

_FEATURE = textwrap.dedent(
    """\
    Feature: smoke
      Scenario: pings
        Given a precondition
    """
)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, **_GIT_ENV, "HOME": str(cwd)}
    subprocess.run(
        ["git", *args],  # noqa: S607
        cwd=str(cwd),
        check=True,
        capture_output=True,
        env=env,
    )


def _scaffold_project(tmp_path: Path) -> Path:
    """Materialise an isolated project with the canonical pytest-bdd layout.

    Includes a tiny package with one public function so ``iter_public_symbols``
    has something to enumerate.
    """
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = project / "acc_cli_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Probe package."""\n', encoding="utf-8")
    (pkg / "core.py").write_text(
        '"""Core module."""\n\n\ndef public_fn() -> int:\n    return 1\n',
        encoding="utf-8",
    )
    features = project / "tests" / "features"
    features.mkdir(parents=True)
    (features / "smoke.feature").write_text(_FEATURE, encoding="utf-8")
    return project


def _write_trace(
    project: Path,
    *,
    computed_at: str | None = None,
    traced: list[str] | None = None,
    scenarios: dict[str, dict[str, object]] | None = None,
) -> Path:
    """Write a stub trace.json with the schema documented in design D9."""
    trace_dir = project / ".interlocks"
    trace_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "computed_at": computed_at or _now_iso(),
        "scenarios": scenarios
        if scenarios is not None
        else {
            "deadbeefcafef00d": {
                "feature": "tests/features/smoke.feature",
                "title": "pings",
                "symbols": ["acc_cli_probe.core:public_fn"],
            }
        },
        "traced_symbols_index": traced if traced is not None else ["acc_cli_probe.core:public_fn"],
    }
    path = trace_dir / "trace.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stale_iso() -> str:
    """Return an ISO-8601 timestamp guaranteed older than any HEAD commit."""
    return (datetime.now(tz=UTC) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh project with trace-friendly sources, chdir-d for ``load_config``."""
    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    return project


def _patch_argv(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", *args])


# ─────────────── baseline ─────────────────────


def test_baseline_writes_budget_with_signature(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_trace(tmp_project)
    _patch_argv(monkeypatch, "acceptance", "baseline")

    mod.cmd_acceptance()

    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    assert budget_path.exists()
    loaded = load_budget(budget_path)
    assert loaded is not None
    assert loaded.version == 1
    assert loaded.baseline_at.endswith("Z")
    assert isinstance(loaded.untraced, dict)
    assert loaded.untraced_count == sum(len(v) for v in loaded.untraced.values())
    assert loaded.signature is not None and loaded.signature.startswith("sha256:")
    secret = derive_repo_secret(tmp_project)
    assert verify_signature(loaded, secret) == "ok"


def test_baseline_refuses_overwrite_without_force(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_trace(tmp_project)
    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    pre_existing = Budget(
        version=1,
        baseline_at="2026-01-01T00:00:00Z",
        untraced={"sentinel": ["existing"]},
        untraced_count=1,
        signature="sha256:sentinel",
    )
    write_budget(budget_path, pre_existing)
    original_bytes = budget_path.read_bytes()

    _patch_argv(monkeypatch, "acceptance", "baseline")

    with pytest.raises(SystemExit) as exc:
        mod.cmd_acceptance()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "acceptance_budget.json" in combined
    assert "--force" in combined
    assert budget_path.read_bytes() == original_bytes


def test_baseline_force_overwrites_existing(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_trace(tmp_project)
    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    pre_existing = Budget(
        version=1,
        baseline_at="2020-01-01T00:00:00Z",
        untraced={"sentinel.module": ["never_real"]},
        untraced_count=1,
        signature="sha256:stale-but-irrelevant",
    )
    write_budget(budget_path, pre_existing)

    _patch_argv(monkeypatch, "acceptance", "baseline", "--force")

    mod.cmd_acceptance()

    loaded = load_budget(budget_path)
    assert loaded is not None
    # Sentinel from the pre-existing file did not survive: real public_fn untraced
    # set replaces it. Pre-existing baseline_at also gets replaced with a fresh one.
    assert loaded.baseline_at != "2020-01-01T00:00:00Z"
    assert "sentinel.module" not in loaded.untraced
    secret = derive_repo_secret(tmp_project)
    assert verify_signature(loaded, secret) == "ok"


def test_baseline_blocks_when_trace_missing(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No trace.json scaffolded.
    _patch_argv(monkeypatch, "acceptance", "baseline")

    with pytest.raises(SystemExit) as exc:
        mod.cmd_acceptance()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "interlocks acceptance" in out
    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    assert not budget_path.exists()


def test_baseline_blocks_on_stale_trace(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Trace `computed_at` predating HEAD on src_dir -> refuse to baseline."""
    # Initialise a git repo with a single commit touching the src dir so the
    # HEAD-on-src lookup yields a real timestamp newer than the stub trace.
    _git(tmp_project, "init", "--initial-branch=main")
    _git(tmp_project, "add", ".")
    _git(tmp_project, "commit", "-m", "initial")
    _write_trace(tmp_project, computed_at=_stale_iso())

    _patch_argv(monkeypatch, "acceptance", "baseline")

    with pytest.raises(SystemExit) as exc:
        mod.cmd_acceptance()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "stale" in out.lower() or "interlocks acceptance" in out
    budget_path = tmp_project / ".interlocks" / "acceptance_budget.json"
    assert not budget_path.exists()


# ─────────────── status ─────────────────────


def test_status_prints_summary_with_trace_and_budget(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_trace(tmp_project)
    _patch_argv(monkeypatch, "acceptance", "baseline")
    mod.cmd_acceptance()  # seed budget

    _patch_argv(monkeypatch, "acceptance", "status")
    mod.cmd_acceptance()

    out = capsys.readouterr().out
    assert "scenarios:" in out
    assert "traced symbols:" in out
    assert "untraced symbols:" in out
    assert "budget untraced:" in out
    assert "delta vs budget:" in out


def test_status_nudges_when_trace_missing(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_argv(monkeypatch, "acceptance", "status")
    mod.cmd_acceptance()  # must NOT raise

    out = capsys.readouterr().out
    assert "trace map" in out.lower()
    assert "interlocks acceptance" in out


def test_status_names_behave_gap(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + '\n[tool.interlocks]\nacceptance_runner = "behave"\n',
        encoding="utf-8",
    )
    clear_cache()
    _patch_argv(monkeypatch, "acceptance", "status")

    mod.cmd_acceptance()

    out = capsys.readouterr().out
    assert "behave runner: trace recording unavailable (pytest-bdd only)" in out


def test_status_runs_without_features_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status must not depend on classify_acceptance — read-only over artifacts."""
    project = tmp_path / "bare"
    project.mkdir()
    (project / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = project / "acc_cli_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(project)
    clear_cache()
    _patch_argv(monkeypatch, "acceptance", "status")

    mod.cmd_acceptance()

    out = capsys.readouterr().out
    assert "trace map" in out.lower()


# ─────────────── argv dispatch sanity ─────────────────────


def test_cmd_acceptance_with_no_subcommand_runs_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default ``interlocks acceptance`` (no sub) still routes to suite runner."""
    project = tmp_path / "noop"
    project.mkdir()
    (project / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (project / "tests").mkdir()
    monkeypatch.chdir(project)
    clear_cache()
    _patch_argv(monkeypatch, "acceptance")

    called: list[object] = []
    monkeypatch.setattr(mod, "run", called.append)

    mod.cmd_acceptance()

    # No features dir → warn_skip path; ``run`` never invoked.
    assert called == []
