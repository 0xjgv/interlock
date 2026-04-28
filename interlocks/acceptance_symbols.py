"""Public-symbol enumerator for the acceptance trace gate.

Walks ``cfg.src_dir`` for ``*.py`` modules, imports each, and yields the
``(module_qualname, attribute_name)`` pairs that count as the project's public
surface. The trace plugin will later compare this set against the symbols
reached by Gherkin scenarios; this module only produces the "what symbols
exist" half of the comparison.

Public attributes are top-level functions, classes, and ``staticmethod``
objects whose ``__module__`` matches the containing module (re-exports do not
count). Class methods are *not* enumerated separately — the class is the unit
of granularity, matching the budget design (D3).
"""

from __future__ import annotations

import importlib
import inspect
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path
    from types import ModuleType

    from interlocks.config import InterlockConfig


def iter_public_symbols(cfg: InterlockConfig) -> Iterable[tuple[str, str]]:
    """Yield ``(module_qualname, attribute_name)`` pairs for the public surface.

    Modules whose import raises ``ImportError`` are skipped with a stderr
    nudge; the iterator continues past the failure without raising and without
    affecting the caller's exit code.
    """
    project_root = cfg.project_root.resolve()
    src_dir = cfg.src_dir.resolve()
    src_path_str = str(src_dir)
    if src_path_str not in sys.path:
        sys.path.insert(0, src_path_str)
    project_path_str = str(project_root)
    if project_path_str not in sys.path:
        sys.path.insert(0, project_path_str)

    for path in sorted(src_dir.rglob("*.py")):
        qualname = _module_qualname(path, project_root)
        if qualname is None:
            continue
        module = _safe_import(qualname)
        if module is None:
            continue
        yield from _iter_module_symbols(module, qualname)


def _module_qualname(path: Path, project_root: Path) -> str | None:
    """Map a ``.py`` path to its dotted module qualname, or ``None`` to skip.

    Rules:
    - Skip files inside ``__pycache__``.
    - Skip files whose name starts with ``_`` other than ``__init__.py``.
    - Skip when any path segment (excluding the filename) starts with ``_``.
    - ``__init__.py`` resolves to its containing package qualname.
    """
    try:
        rel = path.resolve().relative_to(project_root)
    except ValueError:
        return None
    *dirs, filename = rel.parts
    if "__pycache__" in dirs:
        return None
    if any(segment.startswith("_") for segment in dirs):
        return None
    if filename == "__init__.py":
        return ".".join(dirs) if dirs else None
    stem = filename.removesuffix(".py")
    if stem.startswith("_"):
        return None
    return ".".join((*dirs, stem))


def _safe_import(qualname: str) -> ModuleType | None:
    """Import ``qualname``; on import failure log to stderr and return ``None``.

    Catches the broader ``Exception`` family rather than just ``ImportError``
    because scaffold templates and pytest-bdd-style modules can raise other
    exceptions at import-time (e.g. ``IndexError`` from ``CONFIG_STACK[-1]``
    when ``pytest_bdd.scenarios()`` runs outside a pytest session). The trace
    gate's job is to enumerate the public surface, not to validate that every
    module can be imported in arbitrary contexts.
    """
    try:
        return importlib.import_module(qualname)
    except Exception as err:
        sys.stderr.write(f"interlocks: skipping {qualname}: {err}\n")
        return None


def _iter_module_symbols(module: ModuleType, qualname: str) -> Iterator[tuple[str, str]]:
    """Yield public ``(qualname, attr)`` pairs declared in ``module``."""
    for attr in sorted(vars(module)):
        if attr.startswith("_"):
            continue
        obj = getattr(module, attr, None)
        if obj is None:
            continue
        if not _is_public_kind(obj):
            continue
        if getattr(obj, "__module__", None) != qualname:
            continue
        yield (qualname, attr)


def _is_public_kind(obj: object) -> bool:
    """True when ``obj`` is a function, class, or ``staticmethod``."""
    return inspect.isfunction(obj) or inspect.isclass(obj) or isinstance(obj, staticmethod)
