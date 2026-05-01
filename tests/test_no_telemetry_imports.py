"""Unit tests for the ``no_telemetry_imports`` lint gate.

The gate is intentionally dumb: any banned substring on any line — even inside
a string literal or docstring — is flagged. That is desired. The codebase
keeps such test data under ``tests/`` (which the gate does not scan) so the
self-check stays clean.
"""

from __future__ import annotations

from pathlib import Path

from interlocks.tasks.no_telemetry_imports import _scan


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_scan_flags_sentry_import(tmp_path: Path) -> None:
    _write(tmp_path / "interlocks" / "foo.py", "import sentry_sdk\n")

    violations = _scan(tmp_path)

    assert len(violations) == 1
    assert violations[0].startswith("interlocks/foo.py:1: ")
    assert violations[0].endswith(": import sentry_sdk")


def test_scan_flags_with_locals_in_string_literal(tmp_path: Path) -> None:
    # The gate is dumb on purpose: ``with_locals=True`` inside a docstring is
    # still flagged. Real projects keep such test data under ``tests/`` where
    # this gate does not scan.
    _write(
        tmp_path / "interlocks" / "bar.py",
        '"""docstring containing with_locals=True somewhere inside."""\n',
    )

    violations = _scan(tmp_path)

    assert len(violations) == 1
    assert "with_locals=True" in violations[0]
    assert violations[0].startswith("interlocks/bar.py:1: ")


def test_scan_clean_tree_returns_empty(tmp_path: Path) -> None:
    _write(tmp_path / "interlocks" / "ok.py", "x = 1\nimport os\n")

    assert _scan(tmp_path) == []


def test_scan_skips_defaults_subdir(tmp_path: Path) -> None:
    # interlocks/defaults/ ships vendored tool configs that may legitimately
    # mention banned strings; the gate must not scan them.
    _write(
        tmp_path / "interlocks" / "defaults" / "vendored_config.py",
        "config = 'import sentry_sdk'\n",
    )
    _write(
        tmp_path / "interlocks" / "defaults" / "nested" / "deeper.py",
        "from sentry_sdk import Hub\n",
    )

    assert _scan(tmp_path) == []


def test_scan_does_not_descend_into_tests(tmp_path: Path) -> None:
    # Files outside ``interlocks/`` (e.g. tests/, repo root) are out of scope.
    _write(tmp_path / "tests" / "test_thing.py", "import sentry_sdk\n")
    _write(tmp_path / "scripts" / "tool.py", "from posthog import Client\n")

    assert _scan(tmp_path) == []


def test_scan_real_interlocks_repo_is_clean() -> None:
    # Self-check: the actual interlocks repo source must contain none of the
    # banned strings. If a future change adds one, this test localizes the
    # regression independently of the CLI plumbing.
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "interlocks").is_dir(), "expected interlocks/ next to tests/"

    assert _scan(repo_root) == []


def test_scan_missing_interlocks_dir_returns_empty(tmp_path: Path) -> None:
    # Project without an ``interlocks/`` source dir (the typical user repo)
    # produces no violations from ``_scan``. The CLI wrapper turns that into
    # a warn-skip; ``_scan`` itself stays pure.
    assert _scan(tmp_path) == []


def test_scan_flags_multiple_patterns_per_file(tmp_path: Path) -> None:
    _write(
        tmp_path / "interlocks" / "multi.py",
        "import sentry_sdk\nx = 1\ninit(default_integrations=True, with_locals=True)\n",
    )

    violations = _scan(tmp_path)

    # 1 hit on line 1 + 2 hits on line 3 = 3 rows.
    assert len(violations) == 3
    assert any("multi.py:1:" in v and "import sentry_sdk" in v for v in violations)
    assert any("multi.py:3:" in v and "default_integrations=True" in v for v in violations)
    assert any("multi.py:3:" in v and "with_locals=True" in v for v in violations)
