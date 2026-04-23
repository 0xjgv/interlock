"""CRAP complexity x coverage gate."""

from __future__ import annotations

import sys

from harness.config import load_config
from harness.git import changed_py_files_vs_main
from harness.metrics import compute_crap_rows, lizard_functions, parse_coverage
from harness.runner import (
    arg_value,
    fail,
    fail_skip,
    generate_coverage_xml,
    ok,
)


def cmd_crap() -> None:
    """CRAP = ccn^2 * (1-cov)^3 + ccn per function — lizard + coverage XML.

    Threshold precedence: ``--max=N`` on argv > ``cfg.crap_max`` (default 30.0,
    overridable via ``[tool.harness] crap_max``). Blocking by default; set
    ``enforce_crap = false`` to keep it advisory.
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
