"""Dependency freshness via explicit package-index lookup."""

from __future__ import annotations

import json
import sys

from interlocks.config import InterlockConfig, invoker_prefix, load_config
from interlocks.runner import capture, fail, ok


def freshness_cmd(cfg: InterlockConfig) -> list[str]:
    return [*invoker_prefix(cfg), "pip", "list", "--outdated", "--format=json"]


def cmd_deps_freshness() -> None:
    cfg = load_config()
    result = capture(freshness_cmd(cfg))
    if result.returncode != 0:
        fail("Dependency freshness: package-index lookup failed")
        output = (result.stdout or "") + (result.stderr or "")
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        sys.exit(result.returncode)

    outdated = _outdated_packages(result.stdout)
    if not outdated:
        ok("Dependency freshness: dependencies current")
        return

    fail(f"Dependency freshness: {len(outdated)} outdated package(s)")
    for package in outdated:
        current = package.get("version", "?")
        latest = package.get("latest_version", "?")
        print(f"  - {package.get('name', '?')}: {current} -> {latest}")
    sys.exit(1)


def _outdated_packages(output: str) -> list[dict[str, object]]:
    try:
        data = json.loads(output or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [package for package in data if isinstance(package, dict)]
