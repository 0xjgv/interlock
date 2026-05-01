"""Unit tests for interlocks.crash.fingerprint — stable 16-hex crash IDs."""

from __future__ import annotations

import re

from interlocks.crash.fingerprint import compute

_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def test_same_inputs_produce_same_fingerprint() -> None:
    frames = [("interlocks/cli.py", "main"), ("interlocks/runner.py", "run")]
    assert compute(frames, "RuntimeError") == compute(frames, "RuntimeError")


def test_line_shift_does_not_change_fingerprint() -> None:
    # Two captures of the "same bug" where only line numbers would differ —
    # since FrameTuple omits line numbers, identical (filename, function) pairs
    # MUST collide regardless of any line-number context the caller had.
    before_refactor = [
        ("interlocks/runner.py", "run"),
        ("interlocks/tasks/lint.py", "main"),
    ]
    after_refactor = [
        ("interlocks/runner.py", "run"),
        ("interlocks/tasks/lint.py", "main"),
    ]
    assert compute(before_refactor, "ValueError") == compute(after_refactor, "ValueError")


def test_different_exception_types_produce_different_fingerprints() -> None:
    frames = [("interlocks/cli.py", "main")]
    assert compute(frames, "RuntimeError") != compute(frames, "ValueError")


def test_different_frames_produce_different_fingerprints() -> None:
    a = [("interlocks/cli.py", "main")]
    b = [("interlocks/runner.py", "run")]
    assert compute(a, "RuntimeError") != compute(b, "RuntimeError")


def test_output_shape_is_16_lowercase_hex() -> None:
    fp = compute([("interlocks/cli.py", "main")], "RuntimeError")
    assert _HEX16.match(fp), fp
    assert len(fp) == 16


def test_empty_frames_still_produces_valid_fingerprint() -> None:
    # Edge case: a crash with no frames left after scrubbing/collapsing should
    # still hash deterministically rather than blow up.
    fp = compute([], "RuntimeError")
    assert _HEX16.match(fp), fp
