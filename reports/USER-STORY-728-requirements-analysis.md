<!-- markdownlint-disable MD060 -->

# Requirements analysis - USER-STORY-728 "Apportion joint account balances between holders"

Simplified rules for demonstration only - not FSCS policy.

## 1. Acceptance criteria quality

| AC | Verdict | Issue | Suggestion |
|----|---------|-------|------------|
| AC1 | Accept with minor clarification | It is concrete, observable, unambiguous, and consistent with R3 and R8. It covers only two eligible holders and an evenly divisible balance; it does not identify SCV holder order, which is immaterial for this example. | Retain it as the baseline equal-split criterion and state that both holders are eligible. Cover three or more holders and remainder pennies separately. |
| AC2 | Revise | It is consistent with R2 and R3, but it supplies no balances, holder count, aggregate, or payable outcome, so implementations can interpret it differently and still appear to pass. | Use eligible depositor D0001 with a sole balance of £30,000.00 and a £10,000.00 share of a £20,000.00 two-holder joint account; require an aggregate and compensation of £40,000.00. |
| AC3 | Revise | It expresses R7 but hard-codes £120,000.00 even though R1 makes `payout.config.DEPOSIT_LIMIT_GBP` the source of truth. "Exceeds" gives no concrete input, eligibility is unstated, and it does not prove that the joint share was aggregated before capping. | Refer to the configured deposit compensation limit, state that the depositor is eligible, and use an aggregate £0.01 above that limit. Limit-dependent tests must calculate the input and expected result from `payout.config.DEPOSIT_LIMIT_GBP`. |

## 2. Gaps

| ID | Gap | Rule | Risk | Proposed Given / When / Then |
|----|-----|------|------|------------------------------|
| G1 | AC2 does not define the observable aggregation of a sole balance and a joint-account share. | R2, R3 | High | Given eligible depositor D0001 has a sole account of £30,000.00 and is holder 1 of a £20,000.00 joint account with eligible depositor D0002, when compensation is calculated, then D0001 is credited £10,000.00 from the joint account, has an aggregate of £40,000.00, and is paid £40,000.00. |
| G2 | No criterion covers equal apportionment across three or more holders. | R3, R4 | High | Given a joint account of £100.00 has eligible holders D0001, D0002, and D0003 at `holder_seq` 1, 2, and 3, when compensation is calculated, then they are credited £33.34, £33.33, and £33.33 respectively. |
| G3 | No criterion defines odd-penny allocation in SCV holder order. | R4, R8 | High | Given a joint account of £100.01 has eligible holder D0001 at `holder_seq` 1 and eligible holder D0002 at `holder_seq` 2, when compensation is calculated, then D0001 is credited £50.01, D0002 is credited £50.00, and the shares total £100.01. |
| G4 | No criterion states that an ineligible co-holder receives zero and that their share is not reallocated. | R3, R5 | High | Given a £10,000.00 joint account has eligible holder D0001 at `holder_seq` 1 and ineligible holder D0002 at `holder_seq` 2, when compensation is calculated, then D0001 is credited and paid £5,000.00 and D0002 is paid £0.00. |
| G5 | No criterion covers an overdrawn joint account. | R3, R6 | Medium | Given eligible depositor D0001 has a sole account of £1,000.00 and is a holder of an overdrawn joint account with a balance of -£250.00, when compensation is calculated, then D0001 is credited £0.00 from the joint account and is paid £1,000.00. |
| G6 | AC3 fixes the current numeric limit in the requirement instead of treating configuration as authoritative. | R1, R7 | High | Given `payout.config.DEPOSIT_LIMIT_GBP` is £120,000.00 and eligible depositor D0001 has an aggregate of £120,000.01, when compensation is calculated, then D0001 is paid the configured deposit compensation limit of £120,000.00. |
| G7 | The story does not state inclusive behavior exactly at the limit or one penny above it. | R1, R7 | High | Given eligible depositor D0001 has an aggregate exactly equal to the configured limit and eligible depositor D0002 has an aggregate £0.01 above it, when compensation is calculated, then both are paid exactly the configured limit. The test amounts and expected values are derived from `payout.config.DEPOSIT_LIMIT_GBP`. |
| G8 | No criterion requires every apportioned share to remain a two-decimal-place `Decimal` or requires all shares to reconcile to the account balance. | R4, R8 | High | Given a £0.02 joint account has eligible holders D0001, D0002, and D0003 in SCV order, when compensation is calculated, then their `Decimal` shares are £0.01, £0.01, and £0.00, each has 2 dp, and the shares total £0.02. |
| G9 | No criterion covers a zero-balance joint account. | R3, R6, R8 | Low | Given a joint account of £0.00 has eligible holders D0001 and D0002, when compensation is calculated, then each is credited £0.00 and each monetary result is a 2 dp `Decimal`. |

## 3. Code vs rulebook

| Location | Rule | Current behaviour | Expected behaviour |
|----------|------|-------------------|--------------------|
| `payout/rules.py`, `calculate_compensation` | R3 | Each SCV row credits its holder with the full repeated joint-account balance. A £10,000.00 two-holder joint account therefore credits £10,000.00 to each holder. | Group rows by joint account and divide the single account balance equally across all named holders. |
| `payout/rules.py`, `calculate_compensation` | R4 | The calculation neither uses `holder_seq` nor allocates remainder pennies, so it cannot produce £50.01 and £50.00 for £100.01 or £33.34, £33.33, and £33.33 for £100.00. | Round each equal share down to a penny, then allocate remainder pennies one at a time in ascending SCV `holder_seq` order. |
| `payout/rules.py`, `calculate_compensation` | R2 | Sole balances are aggregated correctly, but a depositor's full repeated joint balance is added instead of only that depositor's apportioned share. The cap is therefore applied to an overstated aggregate. | Add each depositor's apportioned joint shares to all eligible sole balances before applying the limit. |
| `payout/rules.py`, `calculate_compensation` | R5 | An ineligible holder is paid £0.00, but an eligible co-holder is credited the full repeated joint balance rather than only their equal share. For a £10,000.00 two-holder account, the eligible holder receives £10,000.00 instead of £5,000.00. | Keep the ineligible holder's equal share unpaid and do not transfer it to an eligible co-holder. |
| `payout/scv.py`, `_check_accounts` | R4 | `holder_seq` values must be positive and unique per account, but they need not form the sequence 1 through the holder count, and SCV rows are not ordered by `holder_seq` for calculation. | Remainder allocation must follow `holder_seq`; malformed or non-contiguous sequences need an explicit validation policy before they can be handled deterministically. |

## 4. Questions for the product owner

1. Should a joint account whose `holder_seq` values are unique but non-contiguous, such as 1 and 3, be rejected as malformed, or should the available values still define remainder order?
2. Should a record marked `JOINT` with only one holder be rejected, or treated as a one-holder joint account whose holder receives the full balance?
3. If the same depositor appears more than once as a named holder of one joint account, should each row count as a separate equal share, or should the account be rejected?
4. If eligibility flags conflict across rows for the same depositor, should the current "all rows must be eligible" behavior remain, or should the SCV be rejected as inconsistent?

## 5. Recommendation

* Add as acceptance criteria: G1 as the concrete replacement for AC2; G2 for three or more holders; G3 for remainder pennies in SCV order; G4 for an ineligible co-holder without reallocation; and G6 as the configured-limit revision of AC3. Retain AC1 with explicit holder eligibility.
* Test-design notes: G5, G7, G8, and G9 should be regression scenarios rather than additional story criteria. Existing sole-account scenarios already establish overdrawn handling and inclusive cap behavior, while the joint-account tests must verify those rules survive apportionment. Every limit-dependent test must read `payout.config.DEPOSIT_LIMIT_GBP`; every amount must use `Decimal` at 2 dp; and every joint account's shares must reconcile to its non-overdrawn balance.
* Park for the product owner: the four malformed or contradictory SCV questions in section 4. The R1-R8 behavior itself is settled by the rulebook and should not be parked.

<!-- markdownlint-enable MD060 -->