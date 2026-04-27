"""Tests for explicit dependency freshness task."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from interlocks.tasks import deps_freshness as freshness_mod


@dataclass
class _StubProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def test_deps_freshness_passes_when_no_outdated_packages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(freshness_mod, "capture", lambda _cmd: _StubProc(0, "[]"))

    freshness_mod.cmd_deps_freshness()

    assert "dependencies current" in capsys.readouterr().out


def test_deps_freshness_fails_when_packages_are_outdated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        freshness_mod,
        "capture",
        lambda _cmd: _StubProc(0, '[{"name":"pkg","version":"1.0","latest_version":"2.0"}]'),
    )

    with pytest.raises(SystemExit) as exc:
        freshness_mod.cmd_deps_freshness()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "1 outdated package" in out
    assert "pkg: 1.0 -> 2.0" in out


def test_deps_freshness_fails_on_lookup_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(freshness_mod, "capture", lambda _cmd: _StubProc(2, stderr="network down"))

    with pytest.raises(SystemExit) as exc:
        freshness_mod.cmd_deps_freshness()

    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "package-index lookup failed" in out
    assert "network down" in out
