"""Shared fixtures: make `load_config` see each test's CWD instead of a stale cache entry."""

from __future__ import annotations

import pytest

from harness import config as harness_config


@pytest.fixture(autouse=True)
def _clear_harness_config_cache() -> None:
    harness_config.clear_cache()
