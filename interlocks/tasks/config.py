"""`interlocks config` — print the full `[tool.interlocks]` reference.

Read-only. One screen of output that lists every key with its type, default,
description, and current resolved value. Designed for agents driving setup who
need a single command answering "what can I configure?".
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import (
    CONFIG_KEY_GROUP_ORDER,
    CONFIG_KEYS,
    find_project_root,
    kv_with_source,
    load_optional_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from interlocks.config import ConfigKeyDoc, InterlockConfig


def cmd_config() -> None:
    start = time.monotonic()
    project_root = find_project_root()
    pyproject = project_root / "pyproject.toml"
    cfg = load_optional_config()

    ui.command_banner("config", cfg)

    ui.section("Status")
    _print_status(cfg, pyproject_present=pyproject.is_file())

    ui.section("Resolved values")
    _print_resolved(cfg)

    ui.section("Config keys")
    _print_keys()

    ui.section("Precedence")
    _print_precedence()

    ui.section("Examples")
    _print_examples()

    ui.section("Next steps")
    _print_next_steps(cfg, pyproject_present=pyproject.is_file())

    ui.command_footer(start)


def _print_status(cfg: InterlockConfig | None, *, pyproject_present: bool) -> None:
    rows: list[tuple[str, str]] = []
    if pyproject_present and cfg is not None:
        rows.append(("pyproject.toml", cfg.relpath(cfg.project_root / "pyproject.toml")))
    elif pyproject_present:
        rows.append(("pyproject.toml", "(unreadable — falling back to defaults)"))
    else:
        rows.append(("pyproject.toml", "(none — run `interlocks init`)"))
    if cfg is not None:
        preset_label = cfg.preset or "(none)"
        preset_source = cfg.value_sources.get("preset", "bundled-default")
        rows.append(("preset", f"{preset_label} ({preset_source})"))
    else:
        rows.append(("preset", "(none) (bundled-default)"))
    ui.kv_block(rows)


_RESOLVED_KEYS: tuple[str, ...] = tuple(k.name for k in CONFIG_KEYS)


def _print_resolved(cfg: InterlockConfig | None) -> None:
    if cfg is None:
        ui.kv_block([(key, "(defaults — pyproject.toml unreadable)") for key in _RESOLVED_KEYS])
        return
    ui.kv_block([kv_with_source(cfg, key, _resolved_value(cfg, key)) for key in _RESOLVED_KEYS])


_RESOLVED_RENDERERS: dict[str, Callable[[InterlockConfig], object]] = {
    "preset": lambda cfg: cfg.preset or "(none)",
    "src_dir": lambda cfg: cfg.src_dir_arg,
    "test_dir": lambda cfg: cfg.test_dir_arg,
    "features_dir": lambda cfg: (
        cfg.features_dir_arg if cfg.features_dir_arg is not None else "(none)"
    ),
    "pytest_args": lambda cfg: list(cfg.pytest_args) if cfg.pytest_args else "[]",
    "acceptance_runner": lambda cfg: (
        cfg.acceptance_runner if cfg.acceptance_runner is not None else "(auto)"
    ),
    "audit_severity_threshold": lambda cfg: cfg.audit_severity_threshold or "(none)",
    "ci_evidence_path": lambda cfg: cfg.relpath(cfg.ci_evidence_path),
    "acceptance_trace_path": lambda cfg: cfg.relpath(cfg.acceptance_trace_path),
    "acceptance_budget_path": lambda cfg: cfg.relpath(cfg.acceptance_budget_path),
}


def _resolved_value(cfg: InterlockConfig, key: str) -> object:
    renderer = _RESOLVED_RENDERERS.get(key)
    if renderer is not None:
        return renderer(cfg)
    return getattr(cfg, key)


def _print_keys() -> None:
    name_width = max(len(k.name) for k in CONFIG_KEYS)
    type_width = max(len(k.type) for k in CONFIG_KEYS)
    default_width = max(len(k.default) for k in CONFIG_KEYS)
    for group in CONFIG_KEY_GROUP_ORDER:
        keys = [k for k in CONFIG_KEYS if k.group == group]
        if not keys:
            continue
        print(f"  {group}")
        for key in keys:
            print(_format_key_row(key, name_width, type_width, default_width))


def _format_key_row(
    key: ConfigKeyDoc, name_width: int, type_width: int, default_width: int
) -> str:
    return (
        f"    {key.name:<{name_width}}  "
        f"{key.type:<{type_width}}  "
        f"{key.default:<{default_width}}  "
        f"{key.description}"
    )


_PRECEDENCE_LINES: tuple[str, ...] = (
    "  1. CLI flags (--min=, --max=, --max-runtime=, ...)",
    "  2. [tool.interlocks] in nearest pyproject.toml",
    "  3. Preset defaults (baseline|strict|legacy)",
    "  4. Bundled defaults",
)


def _print_precedence() -> None:
    for line in _PRECEDENCE_LINES:
        print(line)


_EXAMPLE_LINES: tuple[str, ...] = (
    "  Apply preset:        interlocks presets set baseline",
    "  Override threshold:  [tool.interlocks]",
    '                       preset = "baseline"',
    "                       coverage_min = 85",
    '  Pin runner/invoker:  test_runner = "pytest"',
    '                       test_invoker = "uv"',
)


def _print_examples() -> None:
    for line in _EXAMPLE_LINES:
        print(line)


def _print_next_steps(cfg: InterlockConfig | None, *, pyproject_present: bool) -> None:
    steps: list[str] = []
    if not pyproject_present:
        steps.append("Scaffold a project:  interlocks init")
    if cfg is not None and cfg.preset is None:
        steps.append("Pick a preset:       interlocks presets")
        steps.append("Set one:             interlocks presets set baseline")
    steps.append("See full help:       interlocks help")
    for step in steps:
        print(f"  {step}")
