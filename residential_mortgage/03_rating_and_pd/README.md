# Module 3: Rating and probability of default (PD)

Scores loans, estimates the chance each one defaults, groups loans into rating grades, and tests the models.

**Status:** Skeleton only (2026-11-15). Nothing here is built yet. Each module is designed first, and the design is signed off and copied to `docs\module_3\` before any code is written.

| # | File | What it will do | Needs first |
|---|---|---|---|
| 1 | `01_application_scorecard.py` | Scorecard built only from what was known when the loan was made. | Module 2: 02_default_engine.py |
| 2 | `02_behavioural_scorecard.py` | Scorecard built from the loan's recent payment history, always one month old. | 01_application_scorecard.py |
| 3 | `03_pit_pd.py` | PD that moves with the economy. Used for IFRS 9. | 01_application_scorecard.py |
| 4 | `04_ttc_pd.py` | PD averaged over a full economic cycle. Used for capital. | Module 2: 02_default_engine.py |
| 5 | `05_pd_calibration.py` | Lines the model PDs up with observed default rates, and measures how much they move with the economic cycle. | 03_pit_pd.py, 04_ttc_pd.py |
| 6 | `06_master_rating_scale.py` | Puts loans into 15 numbered grades, each with one PD, and tracks moves between grades. | 05_pd_calibration.py |
| 7 | `07_model_validation.py` | Tests the PD models: predicted against actual defaults per grade, stability over time, and margins of conservatism. | 05_pd_calibration.py, 06_master_rating_scale.py |
