Feature: Interlock stage commands on a minimal inline project
  As a downstream adopter of interlock
  I want each stage (check / pre-commit / ci / nightly) to run cleanly on a
  trivial project with no surprises
  So that my real projects can rely on the same exit-code + output contract

  Background:
    Given a minimal tmp project

  Scenario: `interlock check` greenlights a clean project
    When I run "interlock check" in the tmp project
    Then the stage exits 0
    And the stage output contains "Quality Checks"
    And the stage output contains "[fix]"
    And the stage output contains "[test]"

  Scenario: `interlock pre-commit` no-ops when nothing is staged
    When I run "interlock pre-commit" in the tmp project
    Then the stage exits 0
    And the stage output contains "No staged Python files"

  Scenario: `interlock ci` runs the full verification pipeline
    When I run "interlock ci" in the tmp project
    Then the stage exits 0
    And the stage output contains "CI Checks"
    And the stage output contains "[lint]"
    And the stage output contains "[coverage]"

  Scenario: `interlock nightly` runs coverage + mutation (bounded runtime)
    When I run "interlock nightly" in the tmp project
    Then the stage exits 0
    And the stage output contains "Nightly"
    And the stage output contains "[coverage]"
    And the stage output contains "Mutation"
