"""Tests for the acceptance trace pytest plugin (Pytester-isolated).

These tests exercise the plugin without the full ``interlocks`` harness via
pytest's built-in ``pytester`` fixture. Each test materialises a synthetic
project tree (source package + feature file + step defs), runs pytest in-proc
with the plugin loaded via ``-p interlocks.acceptance_trace_plugin``, and
asserts on the resulting ``trace.json`` artifact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


# ─────────────────────────── helpers ─────────────────────────────────────────


def _write_synthetic_project(
    pytester: pytest.Pytester,
    *,
    pkg_name: str = "synthsrc",
    extra_module_body: str = "",
    feature_body: str | None = None,
    step_defs_body: str | None = None,
) -> Path:
    """Materialise pkg + feature + step-defs under ``pytester.path``.

    Returns the rootpath. ``pytester.path`` is the tmp working dir; rootpath
    matches it because there's no enclosing pyproject.
    """
    root = pytester.path
    pkg = root / pkg_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        '"""Synthetic source package."""\n'
        f"\n"
        "def public_func() -> int:\n"
        "    return 42\n"
        "\n"
        "def _private_helper() -> int:\n"
        "    return public_func()\n"
        "\n"
        "class Pipeline:\n"
        "    def run(self) -> int:\n"
        "        return public_func()\n"
        f"\n{extra_module_body}\n",
        encoding="utf-8",
    )

    feat_dir = root / "features"
    feat_dir.mkdir()
    feature_text = feature_body or (
        "Feature: synth\n"
        "  Scenario: exercise public func\n"
        "    Given the package is imported\n"
        "    When I call public_func\n"
        "    Then I get 42\n"
    )
    (feat_dir / "synth.feature").write_text(feature_text, encoding="utf-8")

    step_defs_text = step_defs_body or (
        "from pytest_bdd import scenarios, given, when, then\n"
        f"import {pkg_name}\n"
        "\n"
        'scenarios("features/synth.feature")\n'
        "\n"
        '@given("the package is imported")\n'
        "def _imported():\n"
        "    pass\n"
        "\n"
        '@when("I call public_func")\n'
        "def _call(state):\n"
        f"    state['result'] = {pkg_name}.public_func()\n"
        "\n"
        '@then("I get 42")\n'
        "def _check(state):\n"
        "    assert state['result'] == 42\n"
        "\n"
        "import pytest\n"
        "@pytest.fixture\n"
        "def state():\n"
        "    return {}\n"
    )
    (root / "test_synth_steps.py").write_text(step_defs_text, encoding="utf-8")
    return root


def _run(pytester: pytest.Pytester, *args: str, **env: str) -> pytest.RunResult:
    """Invoke pytester.runpytest with the plugin auto-loaded via entry-point.

    The plugin ships with a ``pytest11`` entry-point so it loads automatically
    in the running interpreter. We rely on that here rather than adding
    ``-p interlocks.acceptance_trace_plugin`` (which would double-register
    under pytester's in-process driver and raise ``ValueError``).
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return pytester.runpytest(*args)
    finally:
        monkeypatch.undo()


# ─────────────────────────── basic recording ─────────────────────────────────


def test_basic_recording_captures_public_func(pytester: pytest.Pytester) -> None:
    """Calling a public function during a scenario records ``module:func``."""
    root = _write_synthetic_project(pytester)
    trace_path = root / ".interlocks" / "trace.json"

    result = _run(
        pytester,
        "-q",
        INTERLOCKS_TRACE="1",
        INTERLOCKS_TRACE_PATH=str(trace_path),
        INTERLOCKS_TRACE_SRC_PREFIX="synthsrc",
    )
    result.assert_outcomes(passed=1)
    assert trace_path.exists(), f"trace.json missing; stdout: {result.stdout.str()}"
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert "computed_at" in payload
    assert "scenarios" in payload
    assert "traced_symbols_index" in payload
    assert len(payload["scenarios"]) == 1
    [scenario] = payload["scenarios"].values()
    assert scenario["title"] == "exercise public func"
    assert "synthsrc:public_func" in scenario["symbols"]


def test_module_level_filter_excludes_module_frames(pytester: pytest.Pytester) -> None:
    """Module-body execution must not record ``(module, "<module>")``.

    Force a module-level import inside the scenario step body: the
    ``importlib.import_module`` call materialises a fresh module whose
    top-level body executes under our PY_START callback. Without the filter,
    the resulting code object (``co_name == "<module>"``) would map to no
    top-level attribute name and we'd see weird artifacts; the explicit
    filter rules out ever recording the bare module entry.
    """
    feature_body = (
        "Feature: synth\n"
        "  Scenario: import at runtime\n"
        "    Given the package is imported lazily\n"
        "    When I call public_func\n"
        "    Then I get 42\n"
    )
    step_defs_body = (
        "import importlib\n"
        "import pytest\n"
        "from pytest_bdd import scenarios, given, when, then\n"
        "\n"
        'scenarios("features/synth.feature")\n'
        "\n"
        '@given("the package is imported lazily")\n'
        "def _imported(state):\n"
        "    state['mod'] = importlib.import_module('synthsrc')\n"
        "\n"
        '@when("I call public_func")\n'
        "def _call(state):\n"
        "    state['result'] = state['mod'].public_func()\n"
        "\n"
        '@then("I get 42")\n'
        "def _check(state):\n"
        "    assert state['result'] == 42\n"
        "\n"
        "@pytest.fixture\n"
        "def state():\n"
        "    return {}\n"
    )
    root = _write_synthetic_project(
        pytester, feature_body=feature_body, step_defs_body=step_defs_body
    )
    (root / "test_synth_steps.py").write_text(step_defs_body, encoding="utf-8")
    trace_path = root / ".interlocks" / "trace.json"

    result = _run(
        pytester,
        "-q",
        INTERLOCKS_TRACE="1",
        INTERLOCKS_TRACE_PATH=str(trace_path),
        INTERLOCKS_TRACE_SRC_PREFIX="synthsrc",
    )
    result.assert_outcomes(passed=1)
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    [scenario] = payload["scenarios"].values()
    for symbol in scenario["symbols"]:
        assert ":<module>" not in symbol, f"<module> leaked into trace: {symbol}"


def test_inert_when_env_unset(pytester: pytest.Pytester) -> None:
    """Plugin is a no-op without ``INTERLOCKS_TRACE=1``."""
    root = _write_synthetic_project(pytester)
    trace_path = root / ".interlocks" / "trace.json"

    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)
    assert not trace_path.exists()


# ─────────────────────────── tool selection ──────────────────────────────────


def test_uses_sys_monitoring_on_312_plus(pytester: pytest.Pytester) -> None:
    """On Python ≥3.12 the recorder picks ``sys.monitoring`` (Option A).

    Project minimum is 3.13 (always >=3.12 in practice); the assertion is
    kept as a guarantee that the activation path is actually wired through
    on supported interpreters rather than silently going inert.
    """
    root = _write_synthetic_project(pytester)
    trace_path = root / ".interlocks" / "trace.json"
    # Probe via a conftest that captures the recorder's tool field at session
    # finish and writes it to a sibling file, since the recorder lives only in
    # the pytester subprocess view.
    (root / "conftest.py").write_text(
        "import json, pathlib\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    rec = getattr(session.config, '_interlocks_trace_recorder', None)\n"
        "    if rec is not None:\n"
        "        pathlib.Path('tool.txt').write_text(rec.tool)\n",
        encoding="utf-8",
    )
    result = _run(
        pytester,
        "-q",
        INTERLOCKS_TRACE="1",
        INTERLOCKS_TRACE_PATH=str(trace_path),
        INTERLOCKS_TRACE_SRC_PREFIX="synthsrc",
    )
    result.assert_outcomes(passed=1)
    tool_marker = (root / "tool.txt").read_text(encoding="utf-8")
    assert tool_marker == "sys.monitoring"


# ─────────────────────────── stack-detection ─────────────────────────────────


def test_stack_detection_falls_back_inert(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Foreign tracer + settrace fallback path → recorder goes inert with a nudge.

    We exercise the unit-level entry points directly (without actually fooling
    pytester's subprocess) since the env we care about is purely Python state.
    """
    from interlocks.acceptance_trace_plugin import _Recorder

    def _sentinel_trace(frame, event, arg):  # pragma: no cover - never called
        return _sentinel_trace

    sys.settrace(_sentinel_trace)
    try:
        recorder = _Recorder(src_prefix="x", trace_path=pytester.path / "trace.json")
        # Force the settrace branch.
        recorder._activate_settrace()
        assert recorder.inert is True
        assert recorder.tool == "inert"
    finally:
        sys.settrace(None)


# ─────────────────────────── tracer cleanup on failure ───────────────────────


def test_tracer_cleanup_on_step_failure(pytester: pytest.Pytester) -> None:
    """A step that raises must not leak the tracer into subsequent scenarios."""
    feature_body = (
        "Feature: synth\n"
        "  Scenario: failing\n"
        "    Given the package is imported\n"
        "    When the step blows up\n"
        "    Then never reached\n"
        "\n"
        "  Scenario: passing\n"
        "    Given the package is imported\n"
        "    When I call public_func\n"
        "    Then I get 42\n"
    )
    step_defs_body = (
        "import pytest\n"
        "from pytest_bdd import scenarios, given, when, then\n"
        "import synthsrc\n"
        "\n"
        'scenarios("features/synth.feature")\n'
        "\n"
        '@given("the package is imported")\n'
        "def _imported():\n"
        "    pass\n"
        "\n"
        '@when("the step blows up")\n'
        "def _boom():\n"
        "    raise RuntimeError('boom')\n"
        "\n"
        '@then("never reached")\n'
        "def _never():\n"
        "    pass\n"
        "\n"
        '@when("I call public_func")\n'
        "def _call(state):\n"
        "    state['result'] = synthsrc.public_func()\n"
        "\n"
        '@then("I get 42")\n'
        "def _check(state):\n"
        "    assert state['result'] == 42\n"
        "\n"
        "@pytest.fixture\n"
        "def state():\n"
        "    return {}\n"
    )
    root = _write_synthetic_project(
        pytester, feature_body=feature_body, step_defs_body=step_defs_body
    )
    # Override the feature path that the default step-defs file pointed at;
    # rewrite the generated test file to drop the relative ``../features/``.
    (root / "test_synth_steps.py").write_text(step_defs_body, encoding="utf-8")
    # Move the feature file to ``features/synth.feature`` (already is).
    trace_path = root / ".interlocks" / "trace.json"

    result = _run(
        pytester,
        "-q",
        INTERLOCKS_TRACE="1",
        INTERLOCKS_TRACE_PATH=str(trace_path),
        INTERLOCKS_TRACE_SRC_PREFIX="synthsrc",
    )
    # One pass + one fail expected.
    result.assert_outcomes(passed=1, failed=1)
    assert trace_path.exists()
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    # The passing scenario must have recorded ``public_func``; the failing
    # scenario may or may not have entries (we only assert the tracer didn't
    # crash and the second scenario was unaffected).
    titles = {info["title"] for info in payload["scenarios"].values()}
    assert "passing" in titles


# ─────────────────────────── xdist shard merge ───────────────────────────────


def test_xdist_shard_merge(pytester: pytest.Pytester) -> None:
    """With pytest-xdist, workers shard their output and master merges."""
    pytest.importorskip("xdist")
    feature_body = (
        "Feature: synth\n"
        "  Scenario: alpha\n"
        "    Given the package is imported\n"
        "    When I call public_func\n"
        "    Then I get 42\n"
        "\n"
        "  Scenario: beta\n"
        "    Given the package is imported\n"
        "    When I call public_func twice\n"
        "    Then I get 42 again\n"
    )
    step_defs_body = (
        "import pytest\n"
        "from pytest_bdd import scenarios, given, when, then\n"
        "import synthsrc\n"
        "\n"
        'scenarios("features/synth.feature")\n'
        "\n"
        '@given("the package is imported")\n'
        "def _imported():\n"
        "    pass\n"
        "\n"
        '@when("I call public_func")\n'
        "def _call(state):\n"
        "    state['result'] = synthsrc.public_func()\n"
        "\n"
        '@when("I call public_func twice")\n'
        "def _call2(state):\n"
        "    state['result'] = synthsrc.public_func() + synthsrc.public_func() - 42\n"
        "\n"
        '@then("I get 42")\n'
        "def _check(state):\n"
        "    assert state['result'] == 42\n"
        "\n"
        '@then("I get 42 again")\n'
        "def _check2(state):\n"
        "    assert state['result'] == 42\n"
        "\n"
        "@pytest.fixture\n"
        "def state():\n"
        "    return {}\n"
    )
    root = _write_synthetic_project(
        pytester, feature_body=feature_body, step_defs_body=step_defs_body
    )
    (root / "test_synth_steps.py").write_text(step_defs_body, encoding="utf-8")
    trace_path = root / ".interlocks" / "trace.json"

    result = _run(
        pytester,
        "-q",
        "-n",
        "2",
        "-p",
        "no:cacheprovider",
        INTERLOCKS_TRACE="1",
        INTERLOCKS_TRACE_PATH=str(trace_path),
        INTERLOCKS_TRACE_SRC_PREFIX="synthsrc",
    )
    result.assert_outcomes(passed=2)
    assert trace_path.exists(), f"trace.json missing; stdout: {result.stdout.str()}"
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert len(payload["scenarios"]) == 2
    titles = {info["title"] for info in payload["scenarios"].values()}
    assert titles == {"alpha", "beta"}
    # Shards should have been merged + deleted.
    parent = trace_path.parent
    leftover_shards = [
        p for p in parent.glob("trace.*.json") if p != trace_path and p.name != trace_path.name
    ]
    assert leftover_shards == [], f"shards not cleaned up: {leftover_shards}"
    # Public function invoked under both scenarios → in the union index.
    assert "synthsrc:public_func" in payload["traced_symbols_index"]


# ─────────────────────────── shard-only path (worker view) ───────────────────


def test_worker_writes_shard_not_master(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct unit test: worker code path writes a shard to the right path."""
    from interlocks.acceptance_trace_plugin import _Recorder, _shard_path, _write_shard

    trace_path = pytester.path / ".interlocks" / "trace.json"
    rec = _Recorder(src_prefix="x", trace_path=trace_path)
    rec.per_scenario["abc123"] = {("x.foo", "bar")}
    rec.meta["abc123"] = {"feature": "x.feature", "title": "t"}

    _write_shard(rec, "gw0")
    expected = _shard_path(trace_path, "gw0")
    assert expected.exists()
    payload = json.loads(expected.read_text(encoding="utf-8"))
    assert payload["scenarios"]["abc123"]["symbols"] == ["x.foo:bar"]
    # Shard must NOT carry the merged index — master derives it.
    assert "traced_symbols_index" not in payload
