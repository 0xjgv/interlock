"""Shared fixtures: make `load_config` see each test's CWD instead of a stale cache entry."""

from __future__ import annotations

import pytest

from harness import config as harness_config


@pytest.fixture(autouse=True)
def _isolate_harness_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Clear config cache + point XDG_CONFIG_HOME at an empty tmp dir.

    Without the env isolation, tests would pick up any real
    ``~/.config/harness/config.toml`` on the dev machine.
    """
    harness_config.clear_cache()
    empty = tmp_path_factory.mktemp("empty_xdg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(empty))
