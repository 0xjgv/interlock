"""Run tests with unittest."""

from __future__ import annotations

from harness.paths import TEST_DIR
from harness.runner import run


def cmd_test() -> None:
    run("Run tests", ["uv", "run", "python", "-m", "unittest", "discover", "-s", TEST_DIR, "-q"])
