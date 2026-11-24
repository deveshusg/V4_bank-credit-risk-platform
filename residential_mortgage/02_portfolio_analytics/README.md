# Module 2: Portfolio analytics

Watches the loan book. Checks that balances roll forward month to month, sets the business default definition, tracks loans after they recover, measures how loans move between arrears stages, and draws default and prepayment curves by vintage.

**Status:** Skeleton only (2026-11-15). Nothing here is built yet. Each module is designed first, and the design is signed off and copied to `docs\module_2\` before any code is written.

| # | File | What it will do | Needs first |
|---|---|---|---|
| 1 | `01_data_audit.py` | Rolls the book's balance forward month by month (opening balance, plus new loans, minus repayments and exits, equals closing balance) and checks that it ties out. | Module 1 complete |
| 2 | `02_default_engine.py` | Turns months behind and other triggers into a default flag for each loan and month, with a probation period before a loan counts as recovered. Builds default_events_mart, which replaces the provisional outcome in the Module 1 EDA. | 01_data_audit.py |
| 3 | `03_roll_rates.py` | Measures how loans move between arrears stages each month, and projects those moves forward. | 02_default_engine.py |
| 4 | `04_vintage_curves.py` | Cumulative default and prepayment by months on book for each vintage. Prepayment is treated as a competing exit: a loan that repays early cannot default later. | 02_default_engine.py |
| 5 | `05_concentrations.py` | Where risk is concentrated: grids by credit score and LTV, shares by state and lender, loans that default early, and loans that fall back into arrears. | 03_roll_rates.py, 04_vintage_curves.py |
