"""Unit tests for interlocks.crash.consent — transport consent resolution."""

from __future__ import annotations

from pathlib import Path

from interlocks.config import CrashReports, InterlockConfig
from interlocks.crash.consent import ConsentGate


def _cfg(crash_reports: CrashReports) -> InterlockConfig:
    placeholder = Path("/")
    return InterlockConfig(
        project_root=placeholder,
        src_dir=placeholder,
        test_dir=placeholder,
        test_runner="pytest",
        test_invoker="python",
        crash_reports=crash_reports,
    )


def test_env_off_beats_config_on() -> None:
    cfg = _cfg("on")
    env = {"INTERLOCKS_CRASH_REPORTS": "off"}
    assert ConsentGate.allow_transport(cfg, env) is False


def test_env_on_beats_config_off() -> None:
    cfg = _cfg("off")
    env = {"INTERLOCKS_CRASH_REPORTS": "on"}
    assert ConsentGate.allow_transport(cfg, env) is True


def test_config_off_with_no_env_returns_false() -> None:
    cfg = _cfg("off")
    env: dict[str, str] = {}
    assert ConsentGate.allow_transport(cfg, env) is False


def test_config_on_with_no_env_returns_true() -> None:
    cfg = _cfg("on")
    env: dict[str, str] = {}
    assert ConsentGate.allow_transport(cfg, env) is True


def test_auto_with_ci_true_suppresses() -> None:
    cfg = _cfg("auto")
    env = {"CI": "true"}
    assert ConsentGate.allow_transport(cfg, env) is False


def test_auto_local_no_ci_allows() -> None:
    cfg = _cfg("auto")
    env: dict[str, str] = {}
    assert ConsentGate.allow_transport(cfg, env) is True


def test_auto_with_ci_one_allows() -> None:
    # Only the literal string "true" suppresses — CI=1 (common in some CIs)
    # MUST still allow, because we do not want to silently swallow crashes for
    # users whose CI sets a non-"true" value.
    cfg = _cfg("auto")
    env = {"CI": "1"}
    assert ConsentGate.allow_transport(cfg, env) is True
