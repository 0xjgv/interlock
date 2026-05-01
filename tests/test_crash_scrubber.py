"""Unit tests for :mod:`interlocks.crash.scrubber`.

The scrubber is the boundary between live tracebacks and what ends up on
disk. These tests pin redaction order and the external-frame collapse
contract; regressions here would leak user paths into crash payloads.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import interlocks
from interlocks.crash import scrubber
from interlocks.crash.scrubber import (
    ExternalFrames,
    ScrubbedFrame,
    is_interlocks_frame,
    normalize_traceback,
    scrub_path,
)

# ─────────────── scrub_path ─────────────────────────────────────────


def test_scrub_path_replaces_home_with_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/jane")
    assert scrub_path("/Users/jane/code/foo.py", project_root=None) == "~/code/foo.py"


def test_scrub_path_redacts_other_macos_users(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paths from other users (CI runners, shared boxes) collapse to ``<user>``."""
    monkeypatch.setenv("HOME", "/Users/jane")
    scrubbed = scrub_path("/Users/bob/code/foo.py", project_root=None)
    assert scrubbed == "/Users/<user>/code/foo.py"


def test_scrub_path_redacts_linux_user_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/home/runner/...`` is the canonical GitHub Actions path — must redact."""
    monkeypatch.setenv("HOME", "/Users/jane")
    scrubbed = scrub_path("/home/runner/work/proj/src.py", project_root=None)
    assert scrubbed == "/home/<user>/work/proj/src.py"


def test_scrub_path_collapses_site_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/nowhere")
    raw = "/opt/venv/lib/python3.13/site-packages/pytest/__init__.py"
    assert scrub_path(raw, project_root=None) == "<site-packages>/pytest/__init__.py"


def test_scrub_path_collapses_site_packages_under_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Home-relative venv paths still collapse — site-packages regex runs after home."""
    monkeypatch.setenv("HOME", "/Users/jane")
    raw = "/Users/jane/proj/.venv/lib/python3.13/site-packages/foo/bar.py"
    assert scrub_path(raw, project_root=None) == "<site-packages>/foo/bar.py"


def test_scrub_path_replaces_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project root replacement applies after home/user redaction.

    Home is set to a path that does not overlap the project root so the
    project-root substitution is the load-bearing step.
    """
    monkeypatch.setenv("HOME", "/nowhere")
    project = Path("/srv/build/proj")
    scrubbed = scrub_path("/srv/build/proj/src/cli.py", project_root=project)
    assert scrubbed == "<project>/src/cli.py"


def test_scrub_path_handles_empty_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """``HOME`` unset must not crash; the regex layer still redacts users."""
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)

    def _raises() -> Path:
        raise RuntimeError("home unresolvable")

    monkeypatch.setattr(Path, "home", staticmethod(_raises))
    scrubbed = scrub_path("/Users/jane/file.py", project_root=None)
    assert scrubbed == "/Users/<user>/file.py"


def test_scrub_path_no_match_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/jane")
    assert scrub_path("/etc/hosts", project_root=None) == "/etc/hosts"


# ─────────────── is_interlocks_frame ────────────────────────────────


def test_is_interlocks_frame_true_for_package_files() -> None:
    pkg_file = interlocks.__file__
    assert pkg_file is not None
    assert is_interlocks_frame(pkg_file)


def test_is_interlocks_frame_false_for_external() -> None:
    assert not is_interlocks_frame("/usr/lib/python3.13/json/encoder.py")


# ─────────────── normalize_traceback ────────────────────────────────


def _fake_tb_chain(frames: list[tuple[str, int, str]]) -> Any:
    """Build a linked list mimicking ``TracebackType`` from ``(filename, lineno, name)``.

    Enough of the duck-typed interface for ``normalize_traceback``: each node
    exposes ``tb_frame.f_code.co_filename``, ``tb_frame.f_code.co_name``,
    ``tb_lineno``, and ``tb_next``.
    """
    head: Any = None
    for filename, lineno, name in reversed(frames):
        code = SimpleNamespace(co_filename=filename, co_name=name)
        frame = SimpleNamespace(f_code=code)
        head = SimpleNamespace(tb_frame=frame, tb_lineno=lineno, tb_next=head)
    return head


def test_normalize_traceback_collapses_external_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 interlocks + 5 external (interleaved) yields the documented collapse."""
    monkeypatch.setenv("HOME", "/nowhere")
    pkg_root = Path(interlocks.__file__).resolve().parent

    interlocks_a = str(pkg_root / "cli.py")
    interlocks_b = str(pkg_root / "runner.py")
    interlocks_c = str(pkg_root / "config.py")
    external = "/usr/lib/python3.13/threading.py"

    tb = _fake_tb_chain([
        (interlocks_a, 10, "main"),
        (external, 20, "ext_one"),
        (external, 21, "ext_two"),
        (external, 22, "ext_three"),
        (interlocks_b, 30, "dispatch"),
        (external, 40, "ext_four"),
        (external, 41, "ext_five"),
        (interlocks_c, 50, "load"),
    ])

    result = normalize_traceback(tb, project_root=None)

    assert len(result) == 5
    assert isinstance(result[0], ScrubbedFrame)
    assert result[0].function_name == "main"
    assert result[0].line_no == 10
    assert result[1] == ExternalFrames(count=3)
    assert isinstance(result[2], ScrubbedFrame)
    assert result[2].function_name == "dispatch"
    assert result[3] == ExternalFrames(count=2)
    assert isinstance(result[4], ScrubbedFrame)
    assert result[4].function_name == "load"


def test_normalize_traceback_handles_none() -> None:
    assert normalize_traceback(None, project_root=None) == ()


def test_normalize_traceback_trailing_externals(monkeypatch: pytest.MonkeyPatch) -> None:
    """A traceback ending in external frames flushes the pending count."""
    monkeypatch.setenv("HOME", "/nowhere")
    pkg_root = Path(interlocks.__file__).resolve().parent
    tb = _fake_tb_chain([
        (str(pkg_root / "cli.py"), 1, "main"),
        ("/usr/lib/python3.13/runpy.py", 2, "runner"),
        ("/usr/lib/python3.13/runpy.py", 3, "more"),
    ])

    result = normalize_traceback(tb, project_root=None)

    assert len(result) == 2
    assert isinstance(result[0], ScrubbedFrame)
    assert result[1] == ExternalFrames(count=2)


def test_normalize_traceback_scrubs_filenames(monkeypatch: pytest.MonkeyPatch) -> None:
    """Filenames in returned frames must be redacted, not raw on-disk paths."""
    monkeypatch.setenv("HOME", str(Path(interlocks.__file__).resolve().parents[2]))
    pkg_file = str(Path(interlocks.__file__).resolve().parent / "cli.py")
    tb = _fake_tb_chain([(pkg_file, 1, "main")])

    result = normalize_traceback(tb, project_root=None)

    assert len(result) == 1
    frame = result[0]
    assert isinstance(frame, ScrubbedFrame)
    assert frame.filename.startswith("~")


# ─────────────── dataclass identity ─────────────────────────────────


def test_dataclasses_are_frozen() -> None:
    from dataclasses import FrozenInstanceError

    frame = ScrubbedFrame(filename="x", line_no=1, function_name="f")
    with pytest.raises(FrozenInstanceError):
        frame.line_no = 2  # type: ignore[misc]
    marker = ExternalFrames(count=3)
    with pytest.raises(FrozenInstanceError):
        marker.count = 4  # type: ignore[misc]


def test_module_exports() -> None:
    """Smoke check that the public surface is what other crash modules expect."""
    assert callable(scrubber.scrub_path)
    assert callable(scrubber.is_interlocks_frame)
    assert callable(scrubber.normalize_traceback)
    assert ScrubbedFrame.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert ExternalFrames.__dataclass_params__.frozen  # type: ignore[attr-defined]
