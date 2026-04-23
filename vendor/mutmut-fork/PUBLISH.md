# Publishing `pyharness-mutmut` to PyPI

This is a **manual, one-off workflow**. Pyharness maintainers run it when the
upstream SHA pyharness pins needs to be republished under the
`pyharness-mutmut` distribution name so that `pipx install pyharness` works
without `git` available on the install host.

## Prerequisites

- `git`, `uv` (>=0.9.5), and a PyPI API token scoped to the
  `pyharness-mutmut` project.
- Maintainer access to https://pypi.org/project/pyharness-mutmut/ (or the
  ability to claim the name on first publish).

## Walkthrough

### 1. Clone upstream mutmut

```sh
git clone https://github.com/boxed/mutmut.git /tmp/mutmut-fork
cd /tmp/mutmut-fork
```

### 2. Pin to a known-good SHA

Pyharness today pins mutmut to commit
**`e31d923c734383ddb7df4aa439ab3c60fd7d629a`** (see the `mutmut @ git+...`
entry in pyharness's root `pyproject.toml`). That commit corresponds to
upstream version **3.5.0** with the `set_start_method` guard from
[mutmut#466](https://github.com/boxed/mutmut/pull/466).

Check out that SHA:

```sh
git checkout e31d923c734383ddb7df4aa439ab3c60fd7d629a
```

If a newer upstream tag exists that supersedes both 3.5.0 and the
`set_start_method` guard, prefer that tag instead — but bump the `version`
in the template `pyproject.toml` (step 3) to match whatever upstream says.

### 3. Swap in the template `pyproject.toml`

Overwrite upstream's `pyproject.toml` with the skeleton shipped in this repo:

```sh
cp /path/to/pyharness/vendor/mutmut-fork/pyproject.toml ./pyproject.toml
```

The skeleton keeps every upstream runtime dependency, the `mutmut` console
script, and the BSD-3-Clause license. It differs from upstream only in:

- `name = "pyharness-mutmut"` (was `mutmut`)
- `description` — reflects the republish purpose
- `urls` — points back to upstream + pyharness repo for issue routing
- authors — credits the upstream maintainer

Double-check the `version` field. Keep it in lockstep with upstream at the
pinned SHA (currently `3.5.0`). If a previous `pyharness-mutmut` publish has
already claimed that version on PyPI, bump a local suffix
(e.g. `3.5.0.post1`) rather than picking an arbitrary version — this
preserves the upstream-version signal for downstream consumers.

### 4. Build

```sh
uv build
```

Verify `dist/pyharness_mutmut-<version>-py3-none-any.whl` and the matching
`.tar.gz` are produced, and that the wheel still ships the `mutmut/` package
directory (i.e. the import path is unchanged):

```sh
unzip -l dist/pyharness_mutmut-*.whl | grep '^.* mutmut/'
```

### 5. Publish

```sh
uv publish --token "$PYPI_TOKEN"
```

On first publish, PyPI will register the `pyharness-mutmut` project against
your account. Subsequent publishes need the same token scope.

Smoke-test from a fresh environment:

```sh
uv tool install --from pyharness-mutmut mutmut
mutmut --help
```

### 6. Follow-up PR in pyharness

This scaffold unit deliberately does **not** modify pyharness's own
`pyproject.toml`. Once the first `pyharness-mutmut` release is live on PyPI,
open a follow-up PR that rewrites the dependency line from:

```toml
"mutmut @ git+https://github.com/boxed/mutmut.git@<sha>",
```

to:

```toml
"pyharness-mutmut>=3.5.0",
```

and regenerates `uv.lock`. That PR is intentionally separate so the publish
step (which requires human-held PyPI credentials) stays decoupled from
pyharness's normal review flow.
