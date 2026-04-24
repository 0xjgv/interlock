# Repository Guidelines

## Project Structure & Module Organization

Core package code lives in `interlock/`. The CLI entrypoint is `interlock/cli.py`, shared process execution is in `interlock/runner.py`, stage orchestration is in `interlock/stages/`, and task commands live in `interlock/tasks/`. Bundled configuration templates and examples are stored in `interlock/defaults/` and shipped as package data.

Tests live in `tests/`, with focused task and stage coverage under `tests/tasks/` and `tests/stages/`. BDD feature files are in `tests/features/`, with step definitions in `tests/step_defs/`. Website documentation assets live under `docs/`.

## Build, Test, and Development Commands

- `uv run interlock check` - primary post-edit workflow: fixes, formatting, type checks, tests, and suppression reporting.
- `uv run interlock ci` - read-only CI parity suite: lint, format check, typecheck, dependency hygiene, complexity, architecture, coverage, and tests.
- `uv run interlock pre-commit` - runs the staged-file checks used by the git hook.
- `uv run interlock setup-hooks` - installs the repository git hooks.
- `uv run python -m unittest discover -s tests` - direct unittest discovery for quick smoke iteration.
- `uv run pytest -q` - direct pytest run, including pytest-bdd tests.

## Coding Style & Naming Conventions

Target Python `3.13`. Use 4-space indentation, explicit type hints in production code, and `snake_case` for modules, functions, and variables. Keep task commands named `cmd_<task>` to match CLI dispatch.

Ruff owns linting, import ordering, and formatting. Line length is `99`; first-party imports are `interlock`. Avoid adding new tools unless already represented in `pyproject.toml`.

## Testing Guidelines

Add or update tests for every behavior change. Use `test_<feature>.py` filenames and `test_<behavior>` test methods or functions. Prefer focused unit tests; add BDD coverage for CLI-level behavior or user workflows.

Coverage is measured with `coverage.py`, branch coverage is enabled, and `fail_under = 80`. Before finishing code changes, run `uv run interlock check`; use `uv run interlock ci` when release or CI parity matters.

## Commit & Pull Request Guidelines

Git history follows Conventional Commits, for example `feat(website): docs content` and `chore(v1.0): consolidate release history`. Keep commits focused and describe the user-visible reason for the change.

Pull requests should summarize behavior changes, list validation performed, and call out risks or follow-up work. Link issues when applicable. Include screenshots only for website or visual documentation changes.

## Security & Configuration Tips

Do not commit secrets, generated credentials, or machine-specific configuration. Prefer the repository’s `interlock` commands over ad hoc tool invocations so local checks stay aligned with CI.
