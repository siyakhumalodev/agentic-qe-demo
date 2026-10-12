Feature: Payout limit
    In order to pay depositors the right amount
    As a payout operator
    I want compensation to be capped at the protection limit

@regression @payout
Scenario: Depositor above the protection limit is paid the limit
    Given I have opened the payout portal
    When I start a payout run for case "CBS-2026-001"
    And I wait for the payout run to finish
    Then the run status should be "Completed"
    And the payment for depositor "D0002" should be "£85,000.00"
