# Module 7: Stress testing

Losses, allowances and capital under severe recessions.

**Status:** Skeleton only (2026-11-15). Nothing here is built yet. Each module is designed first, and the design is signed off and copied to `docs\module_7\` before any code is written.

| # | File | What it will do | Needs first |
|---|---|---|---|
| 1 | `01_satellite_models.py` | Links economic data (interest rates, unemployment, house prices) to default rates. | Module 2: 03_roll_rates.py; Module 6: 02_airb_vasicek.py |
| 2 | `02_stress_projection.py` | Projects losses, allowances and capital ratios over 5 years under a stress scenario. | Module 5: 04_scenario_ecl.py; Module 6: 02_airb_vasicek.py; 01_satellite_models.py |
| 3 | `03_reverse_stress.py` | Finds the mildest scenario that would break the bank's capital. | 02_stress_projection.py |
