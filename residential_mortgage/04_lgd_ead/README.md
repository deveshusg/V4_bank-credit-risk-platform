# Module 4: Loss given default (LGD) and exposure

Estimates how much is lost when a loan defaults, and the expected loss on the book.

**Status:** Skeleton only (2026-11-15). Nothing here is built yet. Each module is designed first, and the design is signed off and copied to `docs\module_4\` before any code is written.

| # | File | What it will do | Needs first |
|---|---|---|---|
| 1 | `01_workout_lgd.py` | Loss on each defaulted loan from its recovery cash flows, discounted back to the default date. | Module 2: 02_default_engine.py |
| 2 | `02_component_lgd.py` | LGD for mortgages built from parts: the chance the loan recovers, the loss if the property is sold, and costs, with the regulatory floors. | 01_workout_lgd.py |
| 3 | `03_expected_loss.py` | Expected loss = PD x LGD x exposure, and a bridge from expected loss to the IFRS 9 allowance. | Module 3: 06_master_rating_scale.py; 02_component_lgd.py |
