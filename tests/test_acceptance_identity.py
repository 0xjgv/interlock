"""Tests for interlocks.acceptance_identity — content-derived scenario identity."""

from __future__ import annotations

from pathlib import Path

from interlocks.acceptance_identity import (
    Scenario,
    iter_scenarios,
    scenario_identity,
)


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ─────────────── scenario_identity (pure function) ─────────────────────


def test_identity_is_16_char_hex() -> None:
    identity = scenario_identity(["Given a thing", "When it happens", "Then ok"])
    assert len(identity) == 16
    int(identity, 16)  # hex-decodable


def test_identity_normalizes_case_and_whitespace() -> None:
    a = scenario_identity(["Given A Thing", "When it happens", "Then ok"])
    b = scenario_identity(["  given a thing  ", "when it happens", "then ok"])
    assert a == b


def test_identity_skips_blank_and_comment_lines() -> None:
    base = scenario_identity(["Given a thing", "When it happens", "Then ok"])
    decorated = scenario_identity([
        "",
        "Given a thing",
        "# inline comment",
        "",
        "When it happens",
        "  # indented comment",
        "Then ok",
    ])
    assert base == decorated


def test_identity_changes_when_step_text_changes() -> None:
    a = scenario_identity(["Given a thing", "When it happens", "Then ok"])
    b = scenario_identity(["Given a thing", "When it happens twice", "Then ok"])
    assert a != b


# ─────────────── iter_scenarios — feature parsing ─────────────────────


def test_rename_preserves_identity(tmp_path: Path) -> None:
    """Title text changes; step lines unchanged → identity unchanged."""
    body_a = """Feature: cli
  Scenario: original title
    Given the cli is installed
    When I run interlocks check
    Then it exits 0
"""
    body_b = """Feature: cli
  Scenario: renamed title
    Given the cli is installed
    When I run interlocks check
    Then it exits 0
"""
    a = list(iter_scenarios(_write(tmp_path / "a.feature", body_a)))
    b = list(iter_scenarios(_write(tmp_path / "b.feature", body_b)))
    assert len(a) == len(b) == 1
    assert a[0].identity == b[0].identity
    assert a[0].title == "original title"
    assert b[0].title == "renamed title"


def test_step_edit_changes_identity(tmp_path: Path) -> None:
    body_a = """Feature: cli
  Scenario: s
    Given a thing
    When it happens
    Then ok
"""
    body_b = """Feature: cli
  Scenario: s
    Given a thing
    When it happens twice
    Then ok
"""
    a = list(iter_scenarios(_write(tmp_path / "a.feature", body_a)))
    b = list(iter_scenarios(_write(tmp_path / "b.feature", body_b)))
    assert a[0].identity != b[0].identity


def test_comment_only_diff_preserves_identity(tmp_path: Path) -> None:
    body_a = """Feature: cli
  Scenario: s
    Given a thing
    When it happens
    Then ok
"""
    body_b = """Feature: cli
  Scenario: s
    # added a comment line inside the scenario
    Given a thing

    When it happens
    Then ok
"""
    a = list(iter_scenarios(_write(tmp_path / "a.feature", body_a)))
    b = list(iter_scenarios(_write(tmp_path / "b.feature", body_b)))
    assert a[0].identity == b[0].identity


def test_background_change_does_not_affect_scenario_identity(tmp_path: Path) -> None:
    body_a = """Feature: cli
  Background:
    Given a clean repo

  Scenario: s
    Given a thing
    When it happens
    Then ok
"""
    body_b = """Feature: cli
  Background:
    Given a clean repo
    And the cli is on PATH
    And the cache is empty

  Scenario: s
    Given a thing
    When it happens
    Then ok
"""
    a = list(iter_scenarios(_write(tmp_path / "a.feature", body_a)))
    b = list(iter_scenarios(_write(tmp_path / "b.feature", body_b)))
    assert len(a) == len(b) == 1
    assert a[0].identity == b[0].identity


def test_outline_examples_rows_do_not_affect_identity(tmp_path: Path) -> None:
    body_a = """Feature: cli
  Scenario Outline: parametric
    Given input <x>
    When I square it
    Then I get <y>

    Examples:
      | x | y |
      | 1 | 1 |
      | 2 | 4 |
"""
    body_b = """Feature: cli
  Scenario Outline: parametric
    Given input <x>
    When I square it
    Then I get <y>

    Examples:
      | x | y  |
      | 1 | 1  |
      | 2 | 4  |
      | 3 | 9  |
      | 4 | 16 |
"""
    a = list(iter_scenarios(_write(tmp_path / "a.feature", body_a)))
    b = list(iter_scenarios(_write(tmp_path / "b.feature", body_b)))
    assert len(a) == len(b) == 1
    assert a[0].identity == b[0].identity


def test_outline_step_edit_changes_identity(tmp_path: Path) -> None:
    body_a = """Feature: cli
  Scenario Outline: parametric
    Given input <x>
    When I square it
    Then I get <y>

    Examples:
      | x | y |
      | 2 | 4 |
"""
    body_b = """Feature: cli
  Scenario Outline: parametric
    Given input <x>
    When I cube it
    Then I get <y>

    Examples:
      | x | y |
      | 2 | 8 |
"""
    a = list(iter_scenarios(_write(tmp_path / "a.feature", body_a)))
    b = list(iter_scenarios(_write(tmp_path / "b.feature", body_b)))
    assert a[0].identity != b[0].identity


def test_iter_scenarios_yields_one_scenario_per_block(tmp_path: Path) -> None:
    body = """Feature: cli
  Background:
    Given a clean repo

  Scenario: first
    Given a thing
    Then ok

  Scenario: second
    Given another thing
    Then ok

  Scenario Outline: third
    Given input <x>
    Then ok

    Examples:
      | x |
      | 1 |
"""
    scenarios = list(iter_scenarios(_write(tmp_path / "f.feature", body)))
    assert len(scenarios) == 3
    titles = [s.title for s in scenarios]
    assert titles == ["first", "second", "third"]
    # Identities are pairwise distinct (different step blocks).
    identities = {s.identity for s in scenarios}
    assert len(identities) == 3
    # Each Scenario carries the raw step lines (not the background).
    assert all(isinstance(s, Scenario) for s in scenarios)
    assert all(s.feature_path == tmp_path / "f.feature" for s in scenarios)
    assert scenarios[0].steps == ("Given a thing", "Then ok")
    assert scenarios[2].steps == ("Given input <x>", "Then ok")
