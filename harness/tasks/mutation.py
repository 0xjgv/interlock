"""Mutation testing via mutmut. Advisory."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from harness.git import changed_py_files_vs_main
from harness.runner import GREEN, RED, RESET, arg_value, warn_skip

_MUTMUT = ["uv", "run", "--with", "mutmut", "mutmut"]
_RESULT_LINE_PREFIX = "    "


def _mutmut_available() -> bool:
    return (
        subprocess.run(
            [*_MUTMUT, "--version"], capture_output=True, text=True, check=False
        ).returncode
        == 0
    )


def _coverage_line_rate() -> float | None:
    """Regenerate coverage.xml from .coverage and return overall line-rate (0..1)."""
    subprocess.run(
        ["uv", "run", "coverage", "xml", "-o", "coverage.xml", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    cov_file = Path("coverage.xml")
    if not cov_file.exists():
        return None
    try:
        root = ET.parse(cov_file).getroot()
    except ET.ParseError:
        return None
    rate = root.get("line-rate")
    return float(rate) if rate is not None else None


def _parse_results(stdout: str) -> dict[str, list[str]]:
    """Group mutant keys by status from `mutmut results --all=true` output."""
    by_status: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        if not line.startswith(_RESULT_LINE_PREFIX) or ": " not in line:
            continue
        key, _, status = line.strip().partition(": ")
        by_status.setdefault(status, []).append(key)
    return by_status


def _mutant_in_changed(mutant_key: str, changed: set[str]) -> bool:
    """Mutant keys look like `harness.foo.bar__mutmut_1`; match vs `harness/foo.py`."""
    module = mutant_key.split("__mutmut_", 1)[0]
    rel = module.replace(".", "/") + ".py"
    return any(c == rel or c.endswith("/" + rel) for c in changed)


def _run_mutmut(timeout: int) -> bool:
    """Run `mutmut run`, SIGTERM after `timeout`. Return True if it completed on its own."""
    proc = subprocess.Popen([*_MUTMUT, "run"])
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return False
    return True


def cmd_mutation() -> None:
    """Mutation score on `harness/`. Advisory unless --min-score is set."""
    if not _mutmut_available():
        warn_skip("mutation: mutmut not available (pass --with mutmut via uv)")
        return

    min_cov = float(arg_value("--min-coverage=", "70"))
    rate = _coverage_line_rate()
    if rate is None or rate * 100 < min_cov:
        warn_skip(f"mutation: suite coverage < {min_cov}% — run `harness coverage` first")
        return

    timeout = int(arg_value("--max-runtime=", "600"))
    min_score_str = arg_value("--min-score=", "")
    changed = changed_py_files_vs_main() if "--changed-only" in sys.argv else None

    completed = _run_mutmut(timeout)

    res = subprocess.run(
        [*_MUTMUT, "results", "--all=true"],
        capture_output=True,
        text=True,
        check=False,
    )
    by_status = _parse_results(res.stdout)

    killed = len(by_status.get("killed", []))
    survived = by_status.get("survived", [])
    timed_out = len(by_status.get("timeout", []))
    total = killed + len(survived) + timed_out
    score = (killed / total * 100) if total else 0.0

    partial = "" if completed else " (partial — timeout)"
    if min_score_str:
        threshold = float(min_score_str)
        if score < threshold:
            print(
                f"  {RED}✗{RESET} Mutation: score {score:.1f}% "
                f"below threshold {threshold:.1f}%{partial}"
            )
            _print_survivors(survived, changed)
            sys.exit(1)

    print(f"  {GREEN}✓{RESET} Mutation: score {score:.1f}% (killed {killed}/{total}){partial}")
    _print_survivors(survived, changed)


def _print_survivors(survived: list[str], changed: set[str] | None) -> None:
    if not survived:
        return
    shown = [s for s in survived if changed is None or _mutant_in_changed(s, changed)]
    if not shown:
        return
    print(f"    surviving mutants ({len(shown)} shown):")
    for key in shown[:20]:
        print(f"      {key}")
