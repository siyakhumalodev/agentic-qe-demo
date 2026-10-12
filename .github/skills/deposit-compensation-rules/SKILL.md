---
name: deposit-compensation-rules
description: Simplified deposit compensation rulebook (R1-R8) for the fictional Contoso Building Society payout - limit, aggregation, joint accounts, remainder pennies, ineligible holders, overdrawn balances, inclusive cap, money. Use when analysing acceptance criteria, designing or reviewing compensation tests, implementing payout/ rules, or checking legacy tests for stale business rules.
---

# Deposit compensation rulebook (simplified)

> **Simplified rules for demonstration only — not FSCS policy.** Fictional firm, synthetic data.

## Where the rules live

| What | Where |
|---|---|
| The limit (single source of truth) | `payout/config.py` -> `DEPOSIT_LIMIT_GBP` |
| Calculation | `payout/rules.py` -> `calculate_compensation(holdings, limit=None)` |
| Data model | `payout/models.py` (`AccountHolding` = one SCV row, `CompensationResult`) |
| Money helpers | `payout/money.py` (`parse_gbp`, `format_gbp`, `to_pence`, `from_pence`, `to_money`) |
| SCV reader | `payout/scv.py` |

## Rules

| ID | Rule | Notes for tests and code |
|---|---|---|
| **R1** | **Limit:** £120,000 per eligible depositor per authorised firm (from 1 Dec 2025; it was **£85,000** from 1 Jan 2017 to 30 Nov 2025). | Configured once as `DEPOSIT_LIMIT_GBP`. Tests read it - never hard-code 120,000 (or 85,000). Public source: fscs.org.uk deposit-limit page; PRA announcement 18 Nov 2025. |
| **R2** | **Aggregation:** all of a depositor's eligible balances at the firm (sole accounts + their shares of joint accounts) are summed **before** the limit is applied. | Aggregate first, then cap. |
| **R3** | **Joint accounts:** the balance is split **equally** between all named holders. | 2, 3 or more holders. |
| **R4** | **Pennies:** each share is rounded **down** to the penny; the remainder pennies are allocated **one at a time to holders in SCV order** (`holder_seq`), so the shares always add up to the balance. | £100.01 / 2 -> £50.01 (first holder) + £50.00. |
| **R5** | **Ineligible holder:** receives £0; their share is **not** reallocated to the other holders. | £10,000.00 joint, 2nd holder ineligible -> £5,000.00 and £0.00. |
| **R6** | **Overdrawn balances** count as £0 for aggregation (no set-off in this demo). | Applies to sole and joint accounts. |
| **R7** | **Inclusive cap:** compensation = min(aggregate, limit). | Exactly at the limit -> paid in full; one penny over -> the limit. |
| **R8** | **Money:** GBP, `Decimal`, 2 dp. | Never `float`. Store/compare pence as integers if useful. |

**Out of scope:** temporary high balances (up to £1.4m for up to six months), non-GBP accounts,
set-off, interest.

## Worked examples (use them in scenarios)

| Case | Input | Expected |
|---|---|---|
| Joint, 2 holders | joint £10,000.00 | £5,000.00 each |
| Sole + joint share | sole £30,000.00 + joint £20,000.00 (2 holders) | aggregate £40,000.00 -> paid £40,000.00 |
| Over the limit | sole £100,000.00 + joint £50,000.00 (2 holders) | aggregate £125,000.00 -> paid the limit |
| Odd penny | joint £100.01, 2 holders | £50.01 (first in SCV order), £50.00 |
| Ineligible co-holder | joint £10,000.00, 2nd holder ineligible | £5,000.00 and £0.00 |
| Three holders | joint £100.00 | £33.34, £33.33, £33.33 |
| Boundary | aggregate = limit / limit + £0.01 | the limit / the limit |
| Overdrawn | sole -£250.00 and sole £1,000.00 | £1,000.00 |

## SCV file format

`account_id,account_type,holder_seq,depositor_id,depositor_name,depositor_eligible,balance_gbp`
- one row per **account holder**; `account_type` is `SOLE` or `JOINT`;
- `holder_seq` = order of holders on the account (SCV order: 1, 2, 3 ...);
- for a joint account the **full balance is repeated** on each holder row - it is *not* the holder's share;
- `depositor_eligible` is `Y`/`N`; `balance_gbp` has exactly 2 dp and may be negative (overdrawn).

The case dataset is `estate/data/CBS-2026-001_SCV.csv` (synthetic depositors `D0001`...).

## Checklist when reviewing criteria or tests

- [ ] Limit read from `payout.config.DEPOSIT_LIMIT_GBP`; the rule changed on 1 Dec 2025 (£85,000 -> £120,000).
- [ ] Boundaries: exactly at the limit, and one penny above.
- [ ] Joint accounts: 2 holders, 3+ holders, odd pennies, an ineligible co-holder, an overdrawn joint account.
- [ ] Aggregation of sole balances and joint shares before the cap.
- [ ] Amounts are `Decimal` with 2 dp; shares reconcile to the balance.
- [ ] Anything not covered above -> a question for the product owner, not an assumption.
