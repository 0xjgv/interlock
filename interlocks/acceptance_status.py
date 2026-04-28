"""Shared acceptance / Gherkin readiness classifier.

Used by stages, the acceptance task, and `interlocks evaluate` so feature and
scenario counting does not drift between callers.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks.runner import Task

if TYPE_CHECKING:
    from collections.abc import Iterable

    from interlocks.config import InterlockConfig

_SCENARIO_RE = re.compile(r"^\s*Scenario(?: Outline)?:")


class AcceptanceStatus(StrEnum):
    DISABLED = "disabled"
    OPTIONAL_MISSING = "optional_missing"
    MISSING_FEATURES_DIR = "missing_features_dir"
    MISSING_FEATURE_FILES = "missing_feature_files"
    MISSING_SCENARIOS = "missing_scenarios"
    RUNNABLE = "runnable"


def feature_files(features_dir: Path | None) -> list[Path]:
    if features_dir is None or not features_dir.is_dir():
        return []
    return sorted(features_dir.rglob("*.feature"))


def count_scenarios(files: Iterable[Path]) -> int:
    total = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if _SCENARIO_RE.match(line):
                total += 1
    return total


def classify_acceptance(cfg: InterlockConfig) -> AcceptanceStatus:
    if cfg.acceptance_runner == "off":
        return AcceptanceStatus.DISABLED
    features_dir = cfg.features_dir
    required = cfg.require_acceptance
    if features_dir is None or not features_dir.is_dir():
        return (
            AcceptanceStatus.MISSING_FEATURES_DIR
            if required
            else AcceptanceStatus.OPTIONAL_MISSING
        )
    files = feature_files(features_dir)
    if not files:
        return (
            AcceptanceStatus.MISSING_FEATURE_FILES
            if required
            else AcceptanceStatus.OPTIONAL_MISSING
        )
    if count_scenarios(files) == 0:
        return (
            AcceptanceStatus.MISSING_SCENARIOS if required else AcceptanceStatus.OPTIONAL_MISSING
        )
    return AcceptanceStatus.RUNNABLE


def remediation_message(status: AcceptanceStatus, features_dir: Path | None) -> str:
    """Actionable message reused by acceptance command + stage enforcement."""
    scaffold_hint = "run `interlocks init-acceptance` to scaffold one"
    if status is AcceptanceStatus.MISSING_FEATURES_DIR:
        return f"acceptance: features directory not found — {scaffold_hint}"
    if status is AcceptanceStatus.MISSING_FEATURE_FILES:
        target = features_dir if features_dir is not None else Path("tests/features")
        return f"acceptance: no `.feature` files under {target} — {scaffold_hint}"
    if status is AcceptanceStatus.MISSING_SCENARIOS:
        return (
            "acceptance: feature files exist but contain no `Scenario` — add at least one scenario"
        )
    return ""


def required_acceptance_failure_task(status: AcceptanceStatus, features_dir: Path | None) -> Task:
    """Synthetic Task that surfaces a required-acceptance failure inside `run_tasks`."""
    message = remediation_message(status, features_dir)
    payload = f"import sys; sys.stderr.write({message!r} + chr(10)); sys.exit(1)"
    return Task(
        description="Acceptance (required)",
        cmd=["python", "-c", payload],
    )
