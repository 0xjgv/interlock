Feature: interlock doctor adoption diagnostic
  As a user bootstrapping interlock on a fresh checkout
  I want `interlock doctor` to report readiness, blockers, warnings, and next steps
  So that I can decide whether to run local checks or fix setup first

  Scenario: Doctor reports adoption readiness
    Given I run "interlock doctor"
    Then the output contains "── Readiness"
    And the output contains "── Detected Configuration"
    And the output contains "── Setup Checklist"
    And the output contains "── Blockers"
    And the output contains "── Warnings"
    And the output contains "── Next Steps"
    And the output contains "src_dir"

  Scenario: Setup Checklist surfaces artifact rows with tag labels
    Given I run "interlock doctor"
    Then the output contains "[pyproject]"
    And the output contains "[src dir]"
    And the output contains "[ci workflow]"
