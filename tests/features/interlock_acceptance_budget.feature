@cli
Feature: interlocks acceptance budget gate
  As a maintainer relying on `interlocks ci` to keep the public surface covered
  I want the baseline / status / gate subcommands to behave deterministically on
  realistic projects
  So that the ratchet stays trustworthy across every PR

  Background:
    Given an acceptance-budget tmp project

  # req: acceptance-baseline-writes
  Scenario: `interlocks acceptance baseline` writes a signed budget
    Given a fresh trace covering the public surface
    When I run "interlocks acceptance baseline" in the tmp project
    Then the acceptance command exits 0
    And the budget file exists and is signed

  # req: acceptance-baseline-overwrite
  Scenario: `interlocks acceptance baseline` refuses to overwrite without --force
    Given a fresh trace covering the public surface
    And a previously written budget
    When I run "interlocks acceptance baseline" in the tmp project
    Then the acceptance command exits 1
    And the acceptance output contains "--force"

  # req: acceptance-budget-rise
  Scenario: budget gate fails when a new untraced public symbol appears
    Given a trace covering "tmppkg.core:public_fn"
    And a signed budget with no untraced symbols
    And a second public function "other_fn" exists in the source
    When I run the acceptance budget gate in the tmp project
    Then the acceptance command exits 1
    And the acceptance stderr contains "tmppkg.core:other_fn"

  # req: acceptance-budget-shrink
  Scenario: budget gate shrinks budget when a previously-untraced symbol gains coverage
    Given a trace covering "tmppkg.core:public_fn"
    And a signed budget listing "tmppkg.core:public_fn" as untraced
    When I run the acceptance budget gate in the tmp project
    Then the acceptance command exits 0
    And the acceptance stderr contains "shrunk by 1"
    And the budget file now lists no untraced symbols

  # req: acceptance-status-summary
  Scenario: `interlocks acceptance status` prints the expected summary fields
    Given a fresh trace covering the public surface
    And a signed budget with no untraced symbols
    When I run "interlocks acceptance status" in the tmp project
    Then the acceptance command exits 0
    And the acceptance output contains "scenarios:"
    And the acceptance output contains "traced symbols:"
    And the acceptance output contains "untraced symbols:"
    And the acceptance output contains "budget untraced:"
    And the acceptance output contains "delta vs budget:"

  # req: acceptance-status-behave-gap
  Scenario: `interlocks acceptance status` names the behave gap
    Given the tmp project pins acceptance_runner to "behave"
    When I run "interlocks acceptance status" in the tmp project
    Then the acceptance command exits 0
    And the acceptance output contains "behave runner: trace recording unavailable (pytest-bdd only)"

  # req: acceptance-budget-tampering
  Scenario: budget gate detects hand-edited (tampered) budget files
    Given a signed budget listing "tmppkg.core:public_fn" as untraced
    And the budget file is hand-edited to add "ghost" without re-signing
    When I run the acceptance budget gate in the tmp project
    Then the acceptance command exits 1
    And the acceptance stderr contains "budget tampering detected"
