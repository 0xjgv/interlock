# interlocks

Zero-config Python quality CLI: lint, format, typecheck, test, coverage, acceptance, audit, deps, arch, CRAP, mutation. Self-dogfooded.

## Stack

- Python 3.13, uv-managed
- ruff, basedpyright, coverage.py, pytest + pytest-bdd, interlock-mutmut, deptry, import-linter, pip-audit, lizard

## Structure

- `interlocks/cli.py` — entrypoint (also `il`/`ils`/`ilock`/`ilocks`)
- `interlocks/stages/` — composite stages (`check`, `ci`, `nightly`, `pre-commit`)
- `interlocks/tasks/` — single-purpose gates (one per subcommand)
- `interlocks/defaults/` — bundled tool configs (ruff, pyright, coverage, importlinter)
- `tests/features/` + `tests/step_defs/` — pytest-bdd acceptance over public CLI

## Commands

- After edits: `interlocks check`
- Pre-commit (auto via hook): `interlocks pre-commit`
- CI (PR): `interlocks ci`
- Nightly (cron): `interlocks nightly`
- List subcommands + thresholds: `interlocks help`
- List config keys + resolved values: `interlocks config`

## Configuration

- All overrides live under `[tool.interlocks]` in `pyproject.toml`. Run `interlocks config` for the full key list — do not duplicate defaults here.
- Precedence: CLI flag > `[tool.interlocks]` > bundled defaults in `interlocks/defaults/`.
- Project's own `[tool.<tool>]` or sidecar (`ruff.toml`, `.coveragerc`, `pyrightconfig.json`, `.importlinter`) replaces the bundled default for that tool.

## Patterns

- New gate → add task under `interlocks/tasks/`, register in stage composition, cover with a Gherkin scenario in `tests/features/interlock_cli.feature`.
- Thresholds resolve through `interlocks/config.py`. Never read defaults inline — go through the resolver so CLI flags + pyproject overrides win.

## Docs

- `README.md` — user-facing overview
- `STRATEGY.md` — product positioning + roadmap
- `AGENTS.md` — agent-specific guidance
- `PYPI_RELEASE_CHECKLIST.md` — release procedure

<important>
You own this product and the codebase.
</important>