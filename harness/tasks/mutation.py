"""Mutation testing via mutmut. Advisory — never exits non-zero."""

from __future__ import annotations

from harness.runner import run


def cmd_mutation() -> None:
    """Run mutmut. Advisory — not wired into ci.

    mutmut 3.x takes no --paths-to-mutate flag; it defaults to `src/` and reads
    `[tool.mutmut]` in pyproject.toml for customization.
    """
    run("Mutation (mutmut)", ["uv", "run", "mutmut", "run"], no_exit=True)
    run("Mutation results", ["uv", "run", "mutmut", "results"], no_exit=True)
