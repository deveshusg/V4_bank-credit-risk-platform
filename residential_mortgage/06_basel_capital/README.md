# Module 6: Basel capital

Regulatory capital for the mortgage book under the UK Basel 3.1 rules.

**Status:** Skeleton only (2026-11-15). Nothing here is built yet. Each module is designed first, and the design is signed off and copied to `docs\module_6\` before any code is written.

| # | File | What it will do | Needs first |
|---|---|---|---|
| 1 | `01_standardised_rwa.py` | Risk-weighted assets under the standardised approach, using LTV bands. | Module 2: 01_data_audit.py |
| 2 | `02_airb_vasicek.py` | Risk-weighted assets under the internal ratings based approach, and the output floor. | Module 3: 06_master_rating_scale.py; Module 4: 02_component_lgd.py |
| 3 | `03_economic_capital.py` | Capital the bank itself would hold against unexpected loss, and the return on that capital. | 02_airb_vasicek.py |
