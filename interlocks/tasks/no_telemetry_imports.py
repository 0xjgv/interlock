"""Lint gate: forbid telemetry-SDK imports inside ``interlocks/``.

This gate is the regression fence for the never-leave-the-machine guarantee
documented in the crash-reporter design. It greps the project's own
``interlocks/`` source tree for the SDKs and SDK options that capture local
variables, argv, env, or perform automated network egress. A match exits
non-zero; a clean tree prints an ``ok`` row.

Scope: this gate guards interlocks-against-itself only. When invoked from a
user codebase whose root has no ``interlocks/`` directory, it warns-and-skips
rather than scanning the user's source. We never apply these patterns to code
we don't own.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from interlocks.config import load_config
from interlocks.metrics import iter_py_files
from interlocks.runner import Task, fail_skip, ok, warn_skip

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Case-sensitive substring matches. Dumb on purpose: cheap, auditable, and
# false positives are easily resolved by renaming or relocating the offender.
#
# Patterns are assembled from atoms so this very file (which must list each
# pattern as data) does not match itself. A literal banned-import string
# would otherwise trip the scanner on its own source line.
_SDK_NAMES: tuple[str, ...] = ("sentry" + "_sdk", "posthog")
_LOCALS_FLAGS: tuple[str, ...] = (
    "include_local_variables",
    "capture_locals",
    "default_integrations",
    "with_locals",
)
_BANNED_PATTERNS: tuple[str, ...] = (
    *(f"import {name}" for name in _SDK_NAMES),
    *(f"from {name}" for name in _SDK_NAMES),
    *(f"{flag}=True" for flag in _LOCALS_FLAGS),
)

# ``defaults/`` ships third-party tool configs that may legitimately mention
# these strings; the gate is about *our* code, not vendored configs. Build
# caches and virtualenvs are pruned by ``iter_py_files``.
_SKIP_TOP_LEVEL: frozenset[str] = frozenset({"defaults"})


def _iter_scannable(source_root: Path) -> Iterator[Path]:
    """``.py`` files under ``source_root``, excluding the ``defaults/`` subtree."""
    for path in iter_py_files(source_root):
        if path.relative_to(source_root).parts[0] not in _SKIP_TOP_LEVEL:
            yield path


def _relpath(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _scan(project_root: Path) -> list[str]:
    """Return ``"<relpath>:<line>: <pattern>"`` rows for every banned hit.

    Files unreadable as UTF-8 are skipped silently — they cannot host Python
    imports we'd care about, and hard-failing on encoding would be louder
    than useful. Empty list when ``project_root/interlocks`` does not exist.
    """
    source_root = project_root / "interlocks"
    if not source_root.is_dir():
        return []
    violations: list[str] = []
    for path in sorted(_iter_scannable(source_root)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Fast-reject: avoid the per-line/per-pattern inner loop on the 99% clean case.
        if not any(pattern in text for pattern in _BANNED_PATTERNS):
            continue
        rel = _relpath(path, project_root)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in _BANNED_PATTERNS:
                if pattern in line:
                    violations.append(f"{rel}:{lineno}: {pattern}")
    return violations


def _count_files(project_root: Path) -> int:
    source_root = project_root / "interlocks"
    if not source_root.is_dir():
        return 0
    return sum(1 for _ in _iter_scannable(source_root))


def cmd_no_telemetry_imports() -> None:
    """Scan ``interlocks/`` for banned telemetry-SDK strings; exit non-zero on hit."""
    cfg = load_config()
    source_root = cfg.project_root / "interlocks"
    if not source_root.is_dir():
        warn_skip("no_telemetry_imports: no interlocks/ source dir; nothing to scan")
        return
    violations = _scan(cfg.project_root)
    if violations:
        for row in violations[:-1]:
            print(f"  ✗ no_telemetry_imports: {row}")
        fail_skip(f"no_telemetry_imports: {violations[-1]}")
    file_count = _count_files(cfg.project_root)
    ok(f"no_telemetry_imports: {file_count} files clean")


def task_no_telemetry_imports() -> Task:
    """Return the composable ``Task`` form for stage registration.

    ``-P`` skips prepending the CWD onto ``sys.path``. The gate runs from a
    project whose own source root may be a directory literally named
    ``interlocks/`` (the dogfood case); without ``-P`` that local namespace
    package would shadow the installed ``interlocks`` and break the import.
    """
    return Task(
        "No telemetry imports",
        [sys.executable, "-P", "-m", "interlocks.tasks.no_telemetry_imports"],
        label="no_telemetry_imports",
        display="no-telemetry-imports",
    )


if __name__ == "__main__":
    cmd_no_telemetry_imports()
