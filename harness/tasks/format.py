"""Format code with ruff."""

from __future__ import annotations

from harness.runner import run


def cmd_format(files: list[str] | None = None, *, no_exit: bool = False) -> None:
    target = files or ["."]
    run("Format code", ["uv", "run", "ruff", "format", *target], no_exit=no_exit)
