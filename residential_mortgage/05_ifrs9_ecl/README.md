# Module 5: IFRS 9 expected credit loss (ECL)

Accounting loss allowances under IFRS 9 as adopted in the UK.

**Status:** Skeleton only (2026-11-15). Nothing here is built yet. Each module is designed first, and the design is signed off and copied to `docs\module_5\` before any code is written.

| # | File | What it will do | Needs first |
|---|---|---|---|
| 1 | `01_staging_sicr.py` | Puts each loan in stage 1, 2 or 3, using a significant increase in credit risk and a 30 days past due backstop. | Module 3: 06_master_rating_scale.py; Module 4: 03_expected_loss.py |
| 2 | `02_pd_term_structure.py` | PD for each future year of a loan's life, allowing for prepayment. | Module 2: 04_vintage_curves.py; 01_staging_sicr.py |
| 3 | `03_lifetime_lgd_ead.py` | Future LGD under each economic scenario, and the expected balance as the loan pays down. | Module 4: 02_component_lgd.py; 02_pd_term_structure.py |
| 4 | `04_scenario_ecl.py` | Expected credit loss under several economic scenarios, weighted together. | 02_pd_term_structure.py, 03_lifetime_lgd_ead.py |
| 5 | `05_movement_waterfall.py` | Explains each month's change in the allowance: new loans, stage moves, repayments and write-offs. | 04_scenario_ecl.py |
