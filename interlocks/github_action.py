"""GitHub Action helper for running interlocks CI and writing job summaries."""

from __future__ import annotations

import os
import shlex
import subprocess  # noqa: S404
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


DEFAULT_COMMAND = "interlocks ci"


def main(argv: Sequence[str] | None = None) -> None:
    """Run the configured interlocks command and exit with its return code."""
    args = list(sys.argv[1:] if argv is None else argv)
    command = _command_from_args(args)
    returncode = run_command(command)
    write_summary(command, returncode)
    raise SystemExit(returncode)


def run_command(command: Sequence[str]) -> int:
    """Run ``command`` without capturing output so raw CI logs stay visible."""
    completed = subprocess.run(command, check=False)  # noqa: S603
    return completed.returncode


def write_summary(command: Sequence[str], returncode: int) -> None:
    """Write a concise GitHub job summary when ``GITHUB_STEP_SUMMARY`` is available."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    result = "passed" if returncode == 0 else f"failed (exit {returncode})"
    body = "\n".join([
        "## interlocks CI",
        "",
        f"- Command: `{shlex.join(command)}`",
        f"- Result: {result}",
        "",
    ])
    with Path(summary_path).open("a", encoding="utf-8") as f:
        f.write(body)


def _command_from_args(args: Sequence[str]) -> list[str]:
    if not args:
        return shlex.split(DEFAULT_COMMAND)
    if args[0] != "--command":
        raise SystemExit("usage: python -m interlocks.github_action [--command 'interlocks ci']")
    if len(args) != 2:
        raise SystemExit("--command requires one command string")
    return shlex.split(args[1])


if __name__ == "__main__":
    main()
