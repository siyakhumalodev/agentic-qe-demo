-- Staging database of the simulated payout VM: the SCV file is loaded here as-is.
CREATE TABLE IF NOT EXISTS scv_staging (
    row_no             INTEGER PRIMARY KEY,
    account_id         TEXT NOT NULL,
    account_type       TEXT NOT NULL,
    holder_seq         INTEGER NOT NULL,
    depositor_id       TEXT NOT NULL,
    depositor_name     TEXT NOT NULL,
    depositor_eligible TEXT NOT NULL,
    balance_gbp        TEXT NOT NULL
);
