# Repository Guidelines

## Project Structure & Module Organization

Core package code lives in `interlocks/`. The CLI entrypoint is `interlocks/cli.py`, shared process execution is in `interlocks/runner.py`, stage orchestration is in `interlocks/stages/`, and task commands live in `interlocks/tasks/`. Bundled configuration templates and examples are stored in `interlocks/defaults/` and shipped as package data.

Tests live in `tests/`, with focused task and stage coverage under `tests/tasks/` and `tests/stages/`. BDD feature files are in `tests/features/`, with step definitions in `tests/step_defs/`. Website documentation assets live under `docs/`.

## Build, Test, and Development Commands

- `uv run interlocks check` - primary post-edit workflow: fixes, formatting, type checks, tests, and suppression reporting.
- `uv run interlocks ci` - read-only CI parity suite: lint, format check, typecheck, dependency hygiene, complexity, architecture, coverage, and tests.
- `uv run interlocks pre-commit` - runs the staged-file checks used by the git hook.
- `uv run interlocks setup-hooks` - installs the repository git hooks.
- `uv run python -m unittest discover -s tests` - direct unittest discovery for quick smoke iteration.
- `uv run pytest -q` - direct pytest run, including pytest-bdd tests.

## Coding Style & Naming Conventions

Target Python `3.13`. Use 4-space indentation, explicit type hints in production code, and `snake_case` for modules, functions, and variables. Keep task commands named `cmd_<task>` to match CLI dispatch.

Ruff owns linting, import ordering, and formatting. Line length is `99`; first-party imports are `interlocks`. Avoid adding new tools unless already represented in `pyproject.toml`.

## Testing Guidelines

Add or update tests for every behavior change. Use `test_<feature>.py` filenames and `test_<behavior>` test methods or functions. Prefer focused unit tests; add BDD coverage for CLI-level behavior or user workflows.

Coverage is measured with `coverage.py`, branch coverage is enabled, and `fail_under = 80`. Before finishing code changes, run `uv run interlocks check`; use `uv run interlocks ci` when release or CI parity matters.

## Commit & Pull Request Guidelines

Git history follows Conventional Commits, for example `feat(website): docs content` and `chore(v1.0): consolidate release history`. Keep commits focused and describe the user-visible reason for the change.

Pull requests should summarize behavior changes, list validation performed, and call out risks or follow-up work. Link issues when applicable. Include screenshots only for website or visual documentation changes.

## Security & Configuration Tips

Do not commit secrets, generated credentials, or machine-specific configuration. Prefer the repository’s `interlocks` commands over ad hoc tool invocations so local checks stay aligned with CI.
