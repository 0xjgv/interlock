"""Pytest plugin that records public symbols reached by each Gherkin scenario.

Loaded into the pytest subprocess that runs Gherkin scenarios (either via
``-p interlocks.acceptance_trace_plugin`` or via the ``pytest11`` entry-point
declared in ``pyproject.toml``). The plugin is **inert** unless the env var
``INTERLOCKS_TRACE`` is ``"1"`` so it can ship loaded by default without
disturbing unrelated pytest sessions.

Per spec D1, recording lives in the child process — parent-side ``sys.settrace``
is forbidden (the acceptance task shells out to pytest, so a parent tracer
records nothing). Per spec D2, on Python ≥3.12 we use :mod:`sys.monitoring`
(PEP 669) with a distinct tool ID so the recorder never stacks on top of
coverage.py's ``sys.settrace`` (Option A). A ``sys.settrace``-based fallback
path is kept for forward-compatibility / behave-style runners; if a foreign
tracer is already installed when the fallback would activate, the recorder
goes inert with a stderr nudge rather than silently corrupting coverage.

Per-scenario observations are bracketed by ``pytest_bdd_before_scenario`` /
``pytest_bdd_after_scenario`` and flushed in ``pytest_sessionfinish``. Under
xdist each worker writes ``.interlocks/trace.<worker_id>.json`` from its own
session-finish; the master merges shards into ``.interlocks/trace.json`` and
deletes the shards. No xdist → master writes the final file directly.

Stdlib only (D2 constraint). Instrumentation failures are caught and logged
but never alter pytest's exit code (D9).
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interlocks._atomic import atomic_write_bytes
from interlocks.acceptance_identity import scenario_identity

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import CodeType, ModuleType

    import pytest

# ─────────────────────────── env signal names ────────────────────────────────

ENV_ENABLE = "INTERLOCKS_TRACE"
ENV_PATH = "INTERLOCKS_TRACE_PATH"
ENV_SRC_PREFIX = "INTERLOCKS_TRACE_SRC_PREFIX"

_DEFAULT_TRACE_REL = ".interlocks/trace.json"

# Tool ID candidates for sys.monitoring. Per CPython, IDs 0-5 are valid; 0/1/2/5
# are reserved for debugger/coverage/profiler/optimizer respectively, so we
# default to 3 (free-for-tools slot) and fall back to 4, then anything 0-5.
_TOOL_ID_CANDIDATES: tuple[int, ...] = (3, 4, 0, 1, 2, 5)

# ─────────────────────────── recorder ────────────────────────────────────────


class _Recorder:
    """Per-process recorder shared across hooks via ``config._interlocks_trace_recorder``.

    Internal state:
    - ``per_scenario`` maps identity → set of ``(module_qualname, top_level_name)``
    - ``meta`` maps identity → ``{"feature": ..., "title": ...}``
    - ``current_identity`` is set between ``start_scenario`` / ``end_scenario``
    - ``module_index_cache`` reverse-maps ``id(code_obj) → top_level_name`` per
      module. Built lazily on first PY_START / call event from a module.

    A recorder is "inert" when activation failed (e.g. settrace fallback would
    stack on a foreign tracer). Inert recorders no-op every public method but
    are still attached so ``pytest_sessionfinish`` knows to skip persistence.
    """

    def __init__(self, *, src_prefix: str, trace_path: Path) -> None:
        self.src_prefix = src_prefix
        self.trace_path = trace_path
        self.per_scenario: dict[str, set[tuple[str, str]]] = {}
        self.meta: dict[str, dict[str, str]] = {}
        self.current_identity: str | None = None
        self.module_index_cache: dict[str, dict[int, str]] = {}
        self.module_qualname_cache: dict[int, str | None] = {}
        # Activation state — populated by ``activate_*``.
        self.tool: str = "inert"
        self.tool_id: int | None = None
        self._prev_settrace: Any = None
        self.inert: bool = False

    # ── activation ─────────────────────────────────────────────────────────

    def activate(self) -> None:
        """Pick an instrumentation backend and install the global hook.

        Python ≥3.12 → :mod:`sys.monitoring` (Option A).
        Else → :func:`sys.settrace` fallback (Option B); refuses to stack.
        """
        if sys.version_info >= (3, 12) and hasattr(sys, "monitoring"):
            self._activate_monitoring()
        else:  # pragma: no cover - 3.13 minimum, kept for forward-compat
            self._activate_settrace()

    def _activate_monitoring(self) -> None:
        for candidate in _TOOL_ID_CANDIDATES:
            try:
                sys.monitoring.use_tool_id(candidate, "interlocks-acceptance-trace")
            except ValueError:
                continue
            self.tool_id = candidate
            break
        if self.tool_id is None:
            sys.stderr.write("interlocks: could not claim a sys.monitoring tool id; trace inert\n")
            self.inert = True
            return
        try:
            sys.monitoring.register_callback(
                self.tool_id, sys.monitoring.events.PY_START, self._on_py_start
            )
            sys.monitoring.set_events(self.tool_id, sys.monitoring.events.PY_START)
        except Exception as err:  # pragma: no cover - defensive
            sys.stderr.write(f"interlocks: sys.monitoring setup failed: {err}\n")
            self.inert = True
            return
        self.tool = "sys.monitoring"

    def _activate_settrace(self) -> None:
        if sys.gettrace() is not None:
            sys.stderr.write("interlocks: cannot stack sys.settrace with active tracer\n")
            self.inert = True
            return
        sys.settrace(self._on_settrace)
        self.tool = "sys.settrace"

    def deactivate(self) -> None:
        """Reverse :meth:`activate`. Safe to call on inert recorders."""
        if self.inert:
            return
        try:
            if self.tool == "sys.monitoring" and self.tool_id is not None:
                sys.monitoring.set_events(self.tool_id, 0)
                sys.monitoring.register_callback(
                    self.tool_id, sys.monitoring.events.PY_START, None
                )
                sys.monitoring.free_tool_id(self.tool_id)
                self.tool_id = None
            elif self.tool == "sys.settrace":
                sys.settrace(self._prev_settrace)
        except Exception as err:  # pragma: no cover - defensive
            sys.stderr.write(f"interlocks: tracer teardown failed: {err}\n")

    # ── scenario brackets ──────────────────────────────────────────────────

    def start_scenario(self, identity: str, feature_path: str, title: str) -> None:
        if self.inert:
            return
        self.current_identity = identity
        self.per_scenario.setdefault(identity, set())
        # First-write wins for feature/title metadata. (Identity collisions
        # across feature files would imply identical step blocks → same scenario.)
        self.meta.setdefault(identity, {"feature": feature_path, "title": title})

    def end_scenario(self) -> None:
        if self.inert:
            return
        self.current_identity = None

    # ── frame → symbol mapping ─────────────────────────────────────────────

    def _record_code(self, code: CodeType) -> None:
        if self.current_identity is None:
            return
        if code.co_name == "<module>":
            return
        qualname = self._module_qualname_for(code)
        if qualname is None:
            return
        if not self._under_src_prefix(qualname):
            return
        index = self._module_index(qualname)
        if index is None:
            return
        top_name = index.get(id(code))
        if top_name is None:
            return
        self.per_scenario[self.current_identity].add((qualname, top_name))

    def _module_qualname_for(self, code: CodeType) -> str | None:
        cache_key = id(code)
        if cache_key in self.module_qualname_cache:
            return self.module_qualname_cache[cache_key]
        module = inspect.getmodule(code)
        qualname = getattr(module, "__name__", None) if module is not None else None
        self.module_qualname_cache[cache_key] = qualname
        return qualname

    def _under_src_prefix(self, qualname: str) -> bool:
        if not self.src_prefix:
            return True
        return qualname == self.src_prefix or qualname.startswith(self.src_prefix + ".")

    def _module_index(self, qualname: str) -> dict[int, str] | None:
        if qualname in self.module_index_cache:
            return self.module_index_cache[qualname]
        module = sys.modules.get(qualname)
        if module is None:
            return None
        index = _build_module_code_index(module)
        self.module_index_cache[qualname] = index
        return index

    # ── instrumentation callbacks ──────────────────────────────────────────

    def _on_py_start(self, code: CodeType, instruction_offset: int) -> Any:  # noqa: ARG002
        try:
            self._record_code(code)
        except Exception as err:  # pragma: no cover - defensive
            sys.stderr.write(f"interlocks: trace recorder error: {err}\n")
        return None

    def _on_settrace(self, frame: Any, event: str, arg: Any) -> Any:  # noqa: ARG002
        if event == "call":
            try:
                self._record_code(frame.f_code)
            except Exception as err:  # pragma: no cover - defensive
                sys.stderr.write(f"interlocks: trace recorder error: {err}\n")
        return self._on_settrace

    # ── persistence ────────────────────────────────────────────────────────

    def serialize(self) -> dict[str, Any]:
        scenarios: dict[str, Any] = {}
        traced_index: set[str] = set()
        for identity, symbols in self.per_scenario.items():
            sym_list = sorted(f"{module}:{name}" for module, name in symbols)
            traced_index.update(sym_list)
            meta = self.meta.get(identity, {"feature": "", "title": ""})
            scenarios[identity] = {
                "feature": meta["feature"],
                "title": meta["title"],
                "symbols": sym_list,
            }
        return {
            "version": 1,
            "computed_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scenarios": scenarios,
            "traced_symbols_index": sorted(traced_index),
        }


# ─────────────────────────── module-dict reverse index ────────────────────────


def _build_module_code_index(module: ModuleType) -> dict[int, str]:
    """Return ``{id(code_obj) → top_level_attr_name}`` for ``module``.

    Walks ``module.__dict__`` once. Functions map by ``__code__``; classes map
    every method and nested function code object to the *class* attribute name
    (so entering ``MyClass.method`` records ``(module, "MyClass")``);
    ``staticmethod`` objects expose their wrapped code under the module-level
    attribute name they are bound at.
    """
    index: dict[int, str] = {}
    qualname = getattr(module, "__name__", None)
    for attr in vars(module):
        if attr.startswith("_"):
            continue
        try:
            obj = getattr(module, attr, None)
        except Exception as err:  # pragma: no cover - defensive
            # Descriptors with side-effects can raise on attribute access; skip
            # them silently so a single misbehaving attribute can't blind the
            # whole tracer.
            sys.stderr.write(f"interlocks: skipping {qualname}.{attr}: {err}\n")
            continue
        if obj is None:
            continue
        # Only record symbols defined in *this* module - skip re-exports.
        owner = getattr(obj, "__module__", None)
        if owner is not None and owner != qualname:
            continue
        _index_symbol(index, obj, attr)
    return index


def _index_symbol(index: dict[int, str], obj: object, attr: str) -> None:
    """Populate ``index`` with code-objects discoverable from ``obj``."""
    code = _code_of(obj)
    if code is not None:
        index[id(code)] = attr
        return
    if inspect.isclass(obj):
        # Map every callable defined on the class to the class attribute name.
        # Walk __dict__ of the class itself only (avoid base-class methods that
        # don't belong to this class's identity).
        for member in vars(obj).values():
            member_code = _code_of(member)
            if member_code is not None:
                index[id(member_code)] = attr


def _code_of(obj: object) -> CodeType | None:
    """Return the ``__code__`` for a function/staticmethod/classmethod, else None."""
    if inspect.isfunction(obj):
        return getattr(obj, "__code__", None)
    if isinstance(obj, (staticmethod, classmethod)):
        return getattr(obj.__func__, "__code__", None)
    return None


# ─────────────────────────── pytest hooks ────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Build a recorder and attach it to ``config`` if env signal is set."""
    if os.environ.get(ENV_ENABLE) != "1":
        return
    try:
        recorder = _build_recorder(config)
        recorder.activate()
    except Exception as err:
        sys.stderr.write(f"interlocks: trace recorder init failed: {err}\n")
        return
    config._interlocks_trace_recorder = recorder  # type: ignore[attr-defined]


def _build_recorder(config: pytest.Config) -> _Recorder:
    rootpath = Path(getattr(config, "rootpath", Path.cwd()))
    raw_path = os.environ.get(ENV_PATH, _DEFAULT_TRACE_REL)
    trace_path = Path(raw_path)
    if not trace_path.is_absolute():
        trace_path = rootpath / trace_path
    src_prefix = os.environ.get(ENV_SRC_PREFIX) or rootpath.name
    return _Recorder(src_prefix=src_prefix, trace_path=trace_path)


def pytest_bdd_before_scenario(
    request: pytest.FixtureRequest,
    feature: Any,
    scenario: Any,
) -> None:
    """Open a fresh recording for the scenario about to run."""
    recorder = _get_recorder(request.config)
    if recorder is None or recorder.inert:
        return
    try:
        steps = _step_lines(scenario)
        identity = scenario_identity(steps)
        feature_path = getattr(feature, "filename", "") or getattr(feature, "rel_filename", "")
        title = getattr(scenario, "name", "") or ""
        recorder.start_scenario(identity, feature_path=str(feature_path), title=title)
    except Exception as err:  # pragma: no cover - defensive
        sys.stderr.write(f"interlocks: trace recorder error: {err}\n")


def pytest_bdd_after_scenario(
    request: pytest.FixtureRequest,
    feature: Any,  # noqa: ARG001
    scenario: Any,  # noqa: ARG001
) -> None:
    """Close the per-scenario recording (regardless of step success/failure)."""
    recorder = _get_recorder(request.config)
    if recorder is None or recorder.inert:
        return
    try:
        recorder.end_scenario()
    except Exception as err:  # pragma: no cover - defensive
        sys.stderr.write(f"interlocks: trace recorder error: {err}\n")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """Flush recorded scenarios to disk; merge shards on master under xdist."""
    recorder = _get_recorder(session.config)
    if recorder is None:
        return
    try:
        recorder.deactivate()
        if recorder.inert:
            return
        worker_id = _xdist_worker_id(session.config)
        if worker_id is not None:
            _write_shard(recorder, worker_id)
        else:
            _write_master(recorder)
    except Exception as err:  # pragma: no cover - defensive
        sys.stderr.write(f"interlocks: trace recorder flush failed: {err}\n")


# ─────────────────────────── helpers ─────────────────────────────────────────


def _get_recorder(config: pytest.Config | None) -> _Recorder | None:
    if config is None:
        return None
    return getattr(config, "_interlocks_trace_recorder", None)


def _step_lines(scenario: Any) -> list[str]:
    """Reconstruct ``["Given X", "When Y", ...]`` from a pytest-bdd scenario.

    Background steps are excluded — pytest-bdd's ``scenario.steps`` returns
    background + scenario steps combined (see ``ScenarioTemplate.steps``); we
    filter to drop steps tagged as background. Identity must match the parser
    in :mod:`interlocks.acceptance_identity`, which excludes Background.
    """
    raw_steps: Iterable[Any] = getattr(scenario, "steps", []) or []
    lines: list[str] = []
    for step in raw_steps:
        if getattr(step, "background", None) is not None:
            continue
        keyword = (getattr(step, "keyword", "") or "").strip()
        name = (getattr(step, "name", "") or "").strip()
        if not keyword and not name:
            continue
        lines.append(f"{keyword} {name}".strip())
    return lines


def _xdist_worker_id(config: pytest.Config) -> str | None:
    """Return ``"gw0"``-style worker id if running under pytest-xdist, else None."""
    workerinput = getattr(config, "workerinput", None)
    if not workerinput:
        return None
    return str(workerinput.get("workerid", "")) or None


def _serialize(payload: dict[str, Any]) -> bytes:
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    return (text + "\n").encode("utf-8")


def _write_shard(recorder: _Recorder, worker_id: str) -> None:
    payload = recorder.serialize()
    payload.pop("traced_symbols_index", None)  # master recomputes from union
    shard_path = _shard_path(recorder.trace_path, worker_id)
    atomic_write_bytes(shard_path, _serialize(payload))


def _write_master(recorder: _Recorder) -> None:
    """Merge any worker shards into the recorder buffer, then write trace.json."""
    shards = _discover_shards(recorder.trace_path)
    if shards:
        merged = _merge_payloads([recorder.serialize(), *(_load_shard(p) for p in shards)])
        atomic_write_bytes(recorder.trace_path, _serialize(merged))
        for shard in shards:
            shard.unlink(missing_ok=True)
    else:
        atomic_write_bytes(recorder.trace_path, _serialize(recorder.serialize()))


def _shard_path(trace_path: Path, worker_id: str) -> Path:
    """``.interlocks/trace.json`` → ``.interlocks/trace.<worker_id>.json``."""
    suffix = trace_path.suffix
    stem = trace_path.with_suffix("").name  # strip ".json"
    return trace_path.parent / f"{stem}.{worker_id}{suffix}"


def _discover_shards(trace_path: Path) -> list[Path]:
    parent = trace_path.parent
    if not parent.exists():
        return []
    suffix = trace_path.suffix
    stem = trace_path.with_suffix("").name
    pattern = f"{stem}.*{suffix}"
    return sorted(p for p in parent.glob(pattern) if p != trace_path)


def _load_shard(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"interlocks: failed to read shard {path}: {err}\n")
        return {"version": 1, "scenarios": {}}


def _merge_payloads(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Union scenarios across shards; recompute ``traced_symbols_index``."""
    merged_scenarios: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        scenarios = payload.get("scenarios") or {}
        for identity, info in scenarios.items():
            symbols_in = info.get("symbols") or []
            existing = merged_scenarios.get(identity)
            if existing is None:
                merged_scenarios[identity] = {
                    "feature": info.get("feature", ""),
                    "title": info.get("title", ""),
                    "symbols": sorted(set(symbols_in)),
                }
            else:
                merged_symbols = set(existing["symbols"]) | set(symbols_in)
                existing["symbols"] = sorted(merged_symbols)
                # Backfill metadata if a worker ran a scenario the master didn't.
                if not existing.get("feature"):
                    existing["feature"] = info.get("feature", "")
                if not existing.get("title"):
                    existing["title"] = info.get("title", "")
    traced_index: set[str] = set()
    for info in merged_scenarios.values():
        traced_index.update(info["symbols"])
    return {
        "version": 1,
        "computed_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scenarios": merged_scenarios,
        "traced_symbols_index": sorted(traced_index),
    }


__all__ = [
    "ENV_ENABLE",
    "ENV_PATH",
    "ENV_SRC_PREFIX",
    "pytest_bdd_after_scenario",
    "pytest_bdd_before_scenario",
    "pytest_configure",
    "pytest_sessionfinish",
]
