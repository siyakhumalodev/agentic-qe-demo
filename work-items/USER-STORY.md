# STORY-123 — Apportion joint account balances between holders

| Field | Value |
|---|---|
| Type | User Story |
| State | Active |
| Case | CBS-2026-001 (Contoso Building Society - fictional) |
| Tags | payout; joint-accounts |

## Story

As a payout operator I want joint account balances apportioned between the account holders so that
each depositor's compensation reflects only their share and we do not overpay.

## Background

Today the calculation credits the full joint balance to every holder.

## Acceptance criteria

- **AC1** Given a joint account with two holders and a balance of £10,000.00, when compensation is calculated, then each holder is credited £5,000.00 from that account.
- **AC2** Given a depositor with a sole account and a share of a joint account, when compensation is calculated, then their share is added to their sole balance before the limit is applied.
- **AC3** Given a depositor whose aggregated balance exceeds £120,000.00, when compensation is calculated, then their compensation is £120,000.00.

---

_Fictional work item for a demonstration. Simplified rules for demonstration only — not FSCS policy._
