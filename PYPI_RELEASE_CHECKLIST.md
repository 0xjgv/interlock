# PyPI Release Runbook

Internal release notes for publishing both packages from this repo.

## Packages

| Package | Source | Version source | Workflow | Production tag |
| --- | --- | --- | --- | --- |
| `interlocks-mutmut` | vendored mutmut fork template | `vendor/mutmut-fork/pyproject.toml` | `release-mutmut.yml` | `mutmut-vX.Y.Z` |
| `interlocks` | root CLI package | `pyproject.toml` | `release.yml` | `vX.Y.Z` |

`interlocks` depends on `interlocks-mutmut`, so publish `interlocks-mutmut` first when bumping the mutmut fork.

## One-time setup

GitHub environments:

- `testpypi-mutmut`
- `pypi-mutmut`
- `testpypi`
- `pypi`

Trusted Publishers:

| Package | Index | Owner/repo | Workflow | Environment |
| --- | --- | --- | --- | --- |
| `interlocks-mutmut` | TestPyPI | `0xjgv/interlocks` | `release-mutmut.yml` | `testpypi-mutmut` |
| `interlocks-mutmut` | PyPI | `0xjgv/interlocks` | `release-mutmut.yml` | `pypi-mutmut` |
| `interlocks` | TestPyPI | `0xjgv/interlocks` | `release.yml` | `testpypi` |
| `interlocks` | PyPI | `0xjgv/interlocks` | `release.yml` | `pypi` |

## Preflight

```bash
git status --short --branch
interlocks check
rm -rf dist
uv build
uvx twine check dist/*
uv run python -m pytest -q tests/test_wheel_install.py -m slow
```

For `interlocks`, confirm no direct Git dependencies remain in root package metadata:

```bash
grep -n "git+" pyproject.toml uv.lock
```

No output expected.

## Publish `interlocks-mutmut`

### TestPyPI

```bash
gh workflow run release-mutmut.yml
gh run list --workflow release-mutmut.yml --limit 1
gh run watch "$(gh run list --workflow release-mutmut.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

### PyPI

```bash
version=$(python - <<'PY'
import tomllib
from pathlib import Path

data = tomllib.loads(Path("vendor/mutmut-fork/pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)

tag="mutmut-v${version}"
git tag --list "$tag"
git ls-remote --tags origin "refs/tags/${tag}"
git tag "$tag"
git push origin "$tag"
gh run watch "$(gh run list --workflow release-mutmut.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

### Smoke-test PyPI package

```bash
uv venv /tmp/interlocks-mutmut-smoke
uv pip install --python /tmp/interlocks-mutmut-smoke/bin/python interlocks-mutmut
/tmp/interlocks-mutmut-smoke/bin/python -c 'import mutmut; print(mutmut.__version__)'
/tmp/interlocks-mutmut-smoke/bin/mutmut --help
```

## Publish `interlocks`

### TestPyPI

```bash
gh workflow run release.yml
gh run list --workflow release.yml --limit 1
gh run watch "$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

### PyPI

```bash
version=$(python - <<'PY'
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)

tag="v${version}"
git tag --list "$tag"
git ls-remote --tags origin "refs/tags/${tag}"
git tag "$tag"
git push origin "$tag"
gh run watch "$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

### Smoke-test PyPI package

```bash
uv venv /tmp/interlocks-smoke
uv pip install --python /tmp/interlocks-smoke/bin/python interlocks
/tmp/interlocks-smoke/bin/interlocks --help
/tmp/interlocks-smoke/bin/il --help
```

## Verify published versions

```bash
python -m pip index versions interlocks-mutmut
python -m pip index versions interlocks
gh release view "mutmut-v${version}"
gh release view "v${version}"
```

## Rerun failed release job

Use only after the failure is understood. Example: transient mutation timeout/flaky tag run while the same commit is green on `main`.

```bash
gh run view <run-id> --log-failed
gh run rerun <run-id> --failed
gh run watch <run-id> --exit-status
```

## Notes

- `workflow_dispatch` publishes to TestPyPI.
- Production tag pushes publish to PyPI and create GitHub release assets.
- PyPI versions are immutable; bump package version before retrying a completed publish.
- `interlocks-mutmut` keeps import path and CLI as `mutmut`, while distribution name is `interlocks-mutmut`.
