"""Tests under coverage with threshold + uncovered listing.

Reads ``--min=N`` from ``sys.argv`` at call time. Preserved verbatim from the original
cli.py:191 — ``sys.argv`` is process-global, unmodified by ``main()`` dispatch.
"""

from __future__ import annotations

import sys

from harness.paths import TEST_DIR
from harness.runner import run


def cmd_coverage() -> None:
    """Run tests under coverage with threshold + uncovered listing."""
    min_pct = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--min=")), "0"))
    run(
        "Coverage (run)",
        ["uv", "run", "coverage", "run", "-m", "unittest", "discover", "-s", TEST_DIR, "-q"],
    )
    run(
        f"Coverage >= {min_pct}%",
        ["uv", "run", "coverage", "report", "--show-missing", f"--fail-under={min_pct}"],
    )
