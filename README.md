# pyharness

A zero-config Python quality harness: lint, format, typecheck, test, coverage, audit, dep hygiene, architectural contracts — all behind `harness <task>`.

## Install

```
pipx install pyharness   # or: uv tool install pyharness
```

All tools (ruff, basedpyright, coverage, lizard, mutmut, pip-audit, deptry, import-linter, pytest) ship with the CLI.

## Usage

Run inside any Python project:

```
harness help         # show commands + detected project config
harness check        # fix + format + typecheck + test
harness ci           # read-only lint + format check + typecheck + deps + arch + coverage + complexity
harness pre-commit   # staged-only checks (install via `harness setup-hooks`)
harness coverage --min=80
harness audit                        # CVE scan via pip-audit
harness deps                         # dep hygiene (unused/missing/transitive) via deptry
harness arch                         # architectural contracts via import-linter (default: src ↛ tests)
harness crap --max=30                # advisory complexity × coverage gate
harness mutation --max-runtime=600   # advisory mutation score
```

## Configuration

`harness` walks up from your current directory to the nearest `pyproject.toml` and auto-detects:

- **project root** — first directory with `pyproject.toml` (pytest-style rootdir walk)
- **test runner** — `pytest` if `[tool.pytest.*]`, `pytest.ini`, `<test_dir>/conftest.py`, or pytest is declared/importable; otherwise `unittest`
- **test dir** — first existing of `tests/`, `test/`, `src/tests/`
- **source dir** — `[tool.uv.build-backend] module-name`, Hatch/Setuptools packages, `src/<pkg>`, or the first top-level `__init__.py`-bearing dir
- **test invoker** — `uv run` when `uv.lock` is present at the root, else `python -m`

Override any of these via `[tool.harness]` in your `pyproject.toml` (all keys optional):

```toml
[tool.harness]
# Paths / runners
src_dir = "mypkg"
test_dir = "tests"
test_runner = "pytest"         # or "unittest"
test_invoker = "python"        # or "uv"
pytest_args = ["-q", "-x"]

# Thresholds (single source of truth — every gate reads these)
coverage_min = 80              # `harness coverage` fail-under
crap_max = 30.0                # `harness crap` CRAP ceiling
complexity_max_ccn = 15        # lizard CCN cap
complexity_max_args = 7        # lizard argument count cap
complexity_max_loc = 100       # lizard LOC cap
mutation_min_coverage = 70.0   # `harness mutation` skip if suite coverage is lower
mutation_max_runtime = 600     # `harness mutation` seconds before SIGTERM
```

Run `harness help` to see what was auto-detected and which thresholds are in effect.

### Precedence cascade

Every setting is resolved in this order, highest wins:

1. **CLI flags** — `--min=`, `--max=`, `--max-runtime=`, etc.
2. **Project `[tool.harness]`** in the nearest `pyproject.toml`
3. **User-global `~/.config/harness/config.toml`** (respects `$XDG_CONFIG_HOME`) — same keys as `[tool.harness]` but at the root (no `[tool.harness]` wrapper)
4. **Bundled defaults** — the values shown above, plus `harness/defaults/` configs for ruff, coverage, basedpyright, and import-linter when the target project has none of its own

Example `~/.config/harness/config.toml`:

```toml
coverage_min = 85
crap_max = 25.0
```

### Bundled tool defaults

When the target project has no configuration for a given tool, harness injects its bundled default. This lets `harness lint`, `harness typecheck`, `harness coverage`, and `harness arch` work in a brand-new repo with no setup.

| Task | Detected via | Bundled fallback | Injected flag |
|------|-------------|------------------|---------------|
| `lint` / `fix` / `format` / `format-check` | `[tool.ruff]` or `ruff.toml` / `.ruff.toml` | `harness/defaults/ruff.toml` | `--config` |
| `typecheck` | `[tool.basedpyright]` or `pyrightconfig.{json,toml}` | `harness/defaults/pyrightconfig.json` | `--project` |
| `coverage` | `[tool.coverage.*]` or `.coveragerc` | `harness/defaults/coveragerc` | `--rcfile=` |
| `arch` | `[tool.importlinter]` or `.importlinter` / `setup.cfg` | `harness/defaults/importlinter_template.ini` (default src ↛ tests contract) | `--config` |
| `deps` | `[tool.deptry]` | none — deptry's built-ins apply | — |
| `mutation` | `[tool.mutmut]` | none — mutmut reads project `pyproject.toml` only | — |
