"""CRAP complexity x coverage gate."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from harness.config import load_config
from harness.git import changed_py_files_vs_main
from harness.metrics import compute_crap_rows, iter_py_files, lizard_functions, parse_coverage
from harness.runner import (
    arg_value,
    fail,
    fail_skip,
    generate_coverage_xml,
    ok,
    warn_skip,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from harness.config import HarnessConfig

_CRAP_ADVISORY_LIMIT = 5


def cmd_crap() -> None:
    """CRAP = ccn^2 * (1-cov)^3 + ccn per function — lizard + coverage XML.

    Threshold precedence: ``--max=N`` on argv > ``cfg.crap_max`` (default 30.0,
    overridable via ``[tool.harness] crap_max``). Blocking depends on
    ``cfg.enforce_crap``.
    """
    cfg = load_config()
    max_crap = float(arg_value("--max=", str(cfg.crap_max)))
    changed = changed_py_files_vs_main() if "--changed-only" in sys.argv else None

    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        fail_skip("CRAP: coverage.xml not generated — run `harness coverage` first")
    cov_map = parse_coverage(cov_file)
    fns = lizard_functions(cfg.src_dir_arg)
    offenders = compute_crap_rows(fns, cov_map, max_crap=max_crap, changed=changed)

    if not offenders:
        ok(f"CRAP: all functions below {max_crap}")
        return
    offenders.sort(key=lambda r: r.crap, reverse=True)
    for row in offenders[:20]:
        print(
            f"    CRAP={row.crap:6.1f}  CCN={row.ccn:3d}  "
            f"cov={row.coverage * 100:5.1f}%  "
            f"{row.name}@{row.start}-{row.end}@{row.path}"
        )
    message = f"CRAP: {len(offenders)} function(s) exceed {max_crap}"
    if cfg.enforce_crap:
        fail_skip(message)
    fail(message)


def cmd_crap_cached_advisory() -> None:
    """Print fast advisory CRAP output from fresh cached coverage, or a skip hint."""
    cfg = load_config()
    cov_cache = Path(".coverage")
    if not cov_cache.exists():
        warn_skip("CRAP skipped: no coverage cache; run `harness coverage` to enable it")
        return
    if _coverage_cache_is_stale(cov_cache, cfg):
        warn_skip("CRAP skipped: coverage cache is stale; run `harness coverage` to refresh it")
        return

    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        warn_skip("CRAP skipped: coverage.xml not generated; run `harness coverage` to refresh it")
        return

    cov_map = parse_coverage(cov_file)
    offenders = compute_crap_rows(
        lizard_functions(cfg.src_dir_arg), cov_map, max_crap=cfg.crap_max
    )
    offenders.sort(key=lambda r: r.crap, reverse=True)
    if not offenders:
        ok(f"CRAP: all functions below {cfg.crap_max} (cached coverage)")
        return
    for row in offenders[:_CRAP_ADVISORY_LIMIT]:
        print(
            f"    CRAP={row.crap:6.1f}  CCN={row.ccn:3d}  "
            f"cov={row.coverage * 100:5.1f}%  "
            f"{row.name}@{row.start}-{row.end}@{row.path}"
        )
    if len(offenders) > _CRAP_ADVISORY_LIMIT:
        print(f"    … {len(offenders) - _CRAP_ADVISORY_LIMIT} more")
    fail(f"CRAP: {len(offenders)} function(s) exceed {cfg.crap_max} (cached advisory)")


def _coverage_cache_is_stale(cov_cache: Path, cfg: HarnessConfig) -> bool:
    try:
        cov_mtime = cov_cache.stat().st_mtime
    except OSError:
        return True
    return any(_newer_than(path, cov_mtime) for path in _coverage_inputs(cfg))


def _coverage_inputs(cfg: HarnessConfig) -> Iterator[Path]:
    yield cfg.project_root / "pyproject.toml"
    for root in (cfg.src_dir, cfg.test_dir):
        if root.is_file() and root.suffix == ".py":
            yield root
        elif root.is_dir():
            yield from iter_py_files(root)


def _newer_than(path: Path, mtime: float) -> bool:
    try:
        return path.stat().st_mtime > mtime
    except OSError:
        return False
