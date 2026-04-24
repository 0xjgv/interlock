"""Remove cache and build artifacts."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from interlock import ui
from interlock.config import load_config
from interlock.runner import Task, run, tool


def cmd_clean() -> None:
    """Remove cache and build artifacts."""
    start = time.monotonic()
    ui.banner(load_config())
    ui.section("Cleaning Up")
    try:
        for name in [
            ".ruff_cache",
            "build",
            "dist",
            "htmlcov",
            ".coverage",
            "mutants",
            ".mutmut-cache",
            "mutmut-junit.xml",
        ]:
            p = Path(name)
            if p.is_dir():
                shutil.rmtree(p)
            elif p.is_file():
                p.unlink()
        for p in Path().rglob("__pycache__"):
            shutil.rmtree(p)
        run(Task("Ruff clean", tool("ruff", "clean"), label="clean", display="ruff clean"))
    finally:
        ui.stage_footer(time.monotonic() - start)
