"""Simulated legacy payout estate for the Contoso Building Society demo (fictional).

Portal -> control DB -> coordinator -> simulated VM (two databases) -> PowerShell file moves
-> ETL -> payment file on the outbound share. Run it with ``python -m estate up``.

Everything is local and synthetic; nothing connects to a real system.
"""

__version__ = "1.0.0"
