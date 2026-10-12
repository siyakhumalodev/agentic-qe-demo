-- Work database of the simulated payout VM: intermediate calculation results and an ETL audit trail.
CREATE TABLE IF NOT EXISTS calc_results (
    seq                   INTEGER NOT NULL,
    depositor_id          TEXT PRIMARY KEY,
    depositor_name        TEXT NOT NULL,
    eligible              INTEGER NOT NULL,
    aggregate_balance_gbp TEXT NOT NULL,
    compensation_gbp      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS etl_audit (
    ts      TEXT NOT NULL,
    phase   TEXT NOT NULL,
    message TEXT NOT NULL
);
