@story_728
Feature: Apportion joint account balances between holders
  As a payout operator
  I want joint account balances apportioned between their named holders
  So that each depositor's aggregate and compensation use only their share

  Simplified rules for demonstration only - not FSCS policy.
  Covers rules R1-R8 of the deposit-compensation-rules skill.
  "The deposit limit" is read from payout.config.DEPOSIT_LIMIT_GBP.

  @ac_1
  Scenario: AC1 - Two eligible holders receive equal shares of a joint account
    Given a joint account "J72801" held in SCV order by eligible depositors "D9101, D9102" with a balance of £10,000.00
    When compensation is calculated
    Then depositor "D9101" is credited £5,000.00 from account "J72801"
    And depositor "D9102" is credited £5,000.00 from account "J72801"

  @ac_2 @gap_g1
  Scenario: G1 - A sole balance and joint share are aggregated before compensation
    Given a sole account "S72801" for depositor "D0001" with a balance of £30,000.00
    And a joint account "J72802" held in SCV order by eligible depositors "D0001, D0002" with a balance of £20,000.00
    When compensation is calculated
    Then depositor "D0001" is credited £10,000.00 from account "J72802"
    And depositor "D0001" has an aggregated balance of £40,000.00
    And depositor "D0001" is paid £40,000.00

  @gap_g2
  Scenario: G2 - A remainder penny goes to the first of three holders in SCV order
    Given a joint account "J72803" held in SCV order by eligible depositors "D9201, D9202, D9203" with a balance of £100.00
    When compensation is calculated
    Then depositor "D9201" is credited £33.34 from account "J72803"
    And depositor "D9202" is credited £33.33 from account "J72803"
    And depositor "D9203" is credited £33.33 from account "J72803"

  @gap_g3
  Scenario: G3 - An odd penny is allocated in SCV holder order and shares reconcile
    Given a joint account "J72804" held in SCV order by eligible depositors "D9301, D9302" with a balance of £100.01
    When compensation is calculated
    Then depositor "D9301" is credited £50.01 from account "J72804"
    And depositor "D9302" is credited £50.00 from account "J72804"
    And account "J72804" credits for depositors "D9301, D9302" are Decimal amounts with 2 decimal places and total £100.01

  @gap_g4
  Scenario: G4 - An ineligible holder's share is not reallocated
    Given a joint account "J72805" held in SCV order by depositors "D9401, D9402" with a balance of £10,000.00
    And depositor "D9402" is not eligible for compensation
    When compensation is calculated
    Then depositor "D9401" is credited £5,000.00 from account "J72805"
    And depositor "D9401" is paid £5,000.00
    And depositor "D9402" is paid £0.00

  @gap_g5
  Scenario: G5 - An overdrawn joint account contributes zero
    Given a sole account "S72802" for depositor "D9501" with a balance of £1,000.00
    And a joint account "J72806" held in SCV order by eligible depositors "D9501, D9502" that is overdrawn by £250.00
    When compensation is calculated
    Then depositor "D9501" is credited £0.00 from account "J72806"
    And depositor "D9501" is paid £1,000.00

  @ac_3 @gap_g6
  Scenario: G6 - An aggregate one penny above the configured limit is capped
    Given a joint account "J72807" held in SCV order by eligible depositors "D9601, D9602" with each holder's share £0.01 above the deposit limit
    When compensation is calculated
    Then depositor "D9601" has an aggregated balance £0.01 above the deposit limit
    And depositor "D9601" is paid the deposit limit

  @gap_g7
  Scenario: G7 - The configured cap is inclusive at and one penny above the limit
    Given a joint account "J72808" held in SCV order by eligible depositors "D9701, D9702" with each holder's share equal to the deposit limit
    And a joint account "J72809" held in SCV order by eligible depositors "D9703, D9704" with each holder's share £0.01 above the deposit limit
    When compensation is calculated
    Then depositor "D9701" has an aggregated balance equal to the deposit limit
    And depositor "D9701" is paid the deposit limit
    And depositor "D9703" has an aggregated balance £0.01 above the deposit limit
    And depositor "D9703" is paid the deposit limit

  @gap_g8
  Scenario: G8 - Two pennies across three holders remain exact and reconcile
    Given a joint account "J72810" held in SCV order by eligible depositors "D9801, D9802, D9803" with a balance of £0.02
    When compensation is calculated
    Then depositor "D9801" is credited £0.01 from account "J72810"
    And depositor "D9802" is credited £0.01 from account "J72810"
    And depositor "D9803" is credited £0.00 from account "J72810"
    And account "J72810" credits for depositors "D9801, D9802, D9803" are Decimal amounts with 2 decimal places and total £0.02

  @gap_g9
  Scenario: G9 - A zero-balance joint account produces exact zero shares
    Given a joint account "J72811" held in SCV order by eligible depositors "D9901, D9902" with a balance of £0.00
    When compensation is calculated
    Then depositor "D9901" is credited £0.00 from account "J72811"
    And depositor "D9902" is credited £0.00 from account "J72811"
    And account "J72811" credits for depositors "D9901, D9902" are Decimal amounts with 2 decimal places and total £0.00
    And depositor "D9901" has Decimal monetary results with 2 decimal places
    And depositor "D9902" has Decimal monetary results with 2 decimal places