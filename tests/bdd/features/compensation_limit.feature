@compensation_limit
Feature: Compensation is capped at the deposit limit
  As a payout operator
  I want each eligible depositor's compensation capped at the deposit limit
  So that payouts follow the rulebook

  Simplified rules for demonstration only — not FSCS policy.
  Covers rules R1, R2, R5, R6, R7 and R8 of the deposit-compensation-rules skill, for sole accounts.
  "The deposit limit" is read from payout.config.DEPOSIT_LIMIT_GBP.

  Scenario: A sole account below the limit is paid in full
    Given a sole account "A1001" for depositor "D9001" with a balance of £50,000.00
    When compensation is calculated
    Then depositor "D9001" is paid £50,000.00

  Scenario: A sole account above the limit is capped at the deposit limit
    Given a sole account "A1002" for depositor "D9002" with a balance £30,000.00 above the deposit limit
    When compensation is calculated
    Then depositor "D9002" is paid the deposit limit

  Scenario: A balance exactly at the limit is paid in full
    Given a sole account "A1003" for depositor "D9003" with a balance equal to the deposit limit
    When compensation is calculated
    Then depositor "D9003" is paid the deposit limit

  Scenario: Balances across several sole accounts are added together
    Given a sole account "A1004" for depositor "D9004" with a balance of £30,000.00
    And a sole account "A1005" for depositor "D9004" with a balance of £20,000.00
    When compensation is calculated
    Then depositor "D9004" has an aggregated balance of £50,000.00
    And depositor "D9004" is paid £50,000.00

  Scenario: An ineligible depositor receives nothing
    Given a sole account "A1006" for depositor "D9005" with a balance of £20,000.00
    And depositor "D9005" is not eligible for compensation
    When compensation is calculated
    Then depositor "D9005" is paid £0.00

  Scenario: An overdrawn sole account counts as zero
    Given a sole account "A1007" for depositor "D9006" that is overdrawn by £250.00
    And a sole account "A1008" for depositor "D9006" with a balance of £1,000.00
    When compensation is calculated
    Then depositor "D9006" is paid £1,000.00
