# Module 8: Model risk management

Model governance under PRA SS1/23: a register of every model, its assumptions and limits, independent validation, and ongoing monitoring.

**Status:** Skeleton only (2026-11-15). Nothing here is built yet. Each module is designed first, and the design is signed off and copied to `docs\module_8\` before any code is written.

| # | File | What it will do | Needs first |
|---|---|---|---|
| 1 | `01_model_inventory.py` | Lists every model in the platform with its purpose, data, owner and status. | Module 3: 07_model_validation.py; Module 5: 05_movement_waterfall.py; Module 6: 03_economic_capital.py; Module 7: 03_reverse_stress.py |
| 2 | `02_conceptual_soundness.md` | For each model: its assumptions, its limits and its known weaknesses. | 01_model_inventory.py |
| 3 | `03_validation_reports/` | One independent validation report per model. | 01_model_inventory.py |
| 4 | `04_monitoring_dashboard.py` | Tracks model performance over time with red, amber and green signals. | 01_model_inventory.py |
