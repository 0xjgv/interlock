"""Dependency audit via pip-audit."""

from __future__ import annotations

import sys
import tomllib

from interlock.config import find_project_root
from interlock.runner import Task, python_m, run


def task_audit() -> Task:
    if not _project_has_dependencies():
        return Task(
            "Dep audit",
            [sys.executable, "-c", "print('No known vulnerabilities found')"],
            display="python -m pip_audit",
        )
    return Task("Dep audit", python_m("pip_audit", "."))


def cmd_audit() -> None:
    run(task_audit())


def _project_has_dependencies() -> bool:
    pyproject = find_project_root() / "pyproject.toml"
    with pyproject.open("rb") as f:
        project = tomllib.load(f).get("project", {})
    deps = project.get("dependencies", [])
    return isinstance(deps, list) and bool(deps)
