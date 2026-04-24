# PyPI Release Checklist for `interlocks`

## Package metadata

- [x] `pyproject.toml` has `[project]`
- [x] `name = "interlocks"`
- [x] `version = "0.1.0"`
- [x] `readme = "README.md"`
- [x] `requires-python = ">=3.13"`
- [x] `license = {text = "MIT"}`
- [x] `authors` set
- [x] project URLs set
- [x] CLI scripts set:
  - [x] `interlock`
  - [x] `il`

## Build config

- [x] `[build-system]` exists
- [x] `uv_build` configured
- [x] bundled defaults included in sdist/wheel

## Local validation

- [x] Run:
  ```bash
  rm -rf dist
  uv build
  ```
- [x] Run:
  ```bash
  uvx twine check dist/*
  ```
- [x] Run:
  ```bash
  uv run python -m pytest -q tests/test_wheel_install.py -m slow
  ```

## Current blocker

- [ ] Remove direct Git dependency from `pyproject.toml`:
  ```toml
  "mutmut @ git+https://github.com/boxed/mutmut.git@e31d923c734383ddb7df4aa439ab3c60fd7d629a"
  ```
- [ ] Publish `interlock-mutmut` first using:
  ```text
  vendor/mutmut-fork/PUBLISH.md
  ```
- [ ] After `interlock-mutmut` exists on PyPI, replace dependency with:
  ```toml
  "interlock-mutmut>=3.5.0"
  ```
- [ ] Regenerate lockfile:
  ```bash
  uv lock
  ```

## TestPyPI setup

- [ ] Create/claim TestPyPI project `interlocks`
- [ ] Configure TestPyPI Trusted Publisher:
  - [ ] owner/repo = this GitHub repo
  - [ ] workflow = `release.yml`
  - [ ] environment = `testpypi`
- [ ] Run GitHub `release` workflow manually
- [ ] Confirm TestPyPI install works:
  ```bash
  uv tool install --index-url https://test.pypi.org/simple/ interlocks
  ```

## PyPI setup

- [ ] Create/claim PyPI project `interlocks`
- [ ] Configure PyPI Trusted Publisher:
  - [ ] owner/repo = this GitHub repo
  - [ ] workflow = `release.yml`
  - [ ] environment = `pypi`

## Release

- [ ] Ensure version in `pyproject.toml` is final
- [ ] Run final checks:
  ```bash
  interlock check
  rm -rf dist
  uv build
  uvx twine check dist/*
  ```
- [ ] Commit changes
- [ ] Tag matching version:
  ```bash
  git tag v0.1.0
  ```
- [ ] Push tag:
  ```bash
  git push origin v0.1.0
  ```
- [ ] Confirm GitHub release workflow publishes to PyPI
- [ ] Smoke-test real install:
  ```bash
  pipx install interlocks
  interlock --help
  ```
