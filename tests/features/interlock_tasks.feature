Feature: Interlock task commands run against a real tmp project
  As a user running quality gates
  I want each `interlock <task>` to behave sensibly on a freshly-scaffolded project
  So that the tool is safe to adopt on any layout

  Scenario: audit reports no vulnerabilities for a project with no deps
    Given a tmp project with layout "audit"
    When I run "interlock audit" in that project
    Then the exit code is 0 or the output mentions "No known vulnerabilities"

  Scenario: deps flags a declared-but-unused dependency
    Given a tmp project with layout "deps"
    When I run "interlock deps" in that project
    Then the exit code is not 0
    And the output contains "DEP002"

  Scenario: arch passes with the default contract when src and tests are packages
    Given a tmp project with layout "arch"
    When I run "interlock arch" in that project
    Then the exit code is 0
    And the output contains "[arch]"

  Scenario: coverage passes when a trivial test exercises the module
    Given a tmp project with layout "coverage"
    When I run "interlock coverage --min=0" in that project
    Then the exit code is 0
    And the output contains "[coverage]"

  Scenario: crap passes when no function exceeds the threshold
    Given a tmp project with layout "crap"
    When I run "interlock crap" in that project
    Then the exit code is 0
    And the output contains "CRAP"

  Scenario: mutation skips cleanly without coverage data
    Given a tmp project with layout "mutation"
    When I run "interlock mutation" in that project
    Then the exit code is 0
    And the output contains "mutation"
