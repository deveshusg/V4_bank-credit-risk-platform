# Module 01 — Data Foundation

Audits the ingested dataset for target leakage, establishes the feature catalogue, and runs
exploratory data analysis notebooks. Must be run after Module 00 and before Module 02.

---

## Operations

### Prerequisites

- `mortgages.duckdb` and `mortgages_sample.duckdb` built by Module 00.
- Python 3.11+ `.venv` with `duckdb`, `pandas`, `matplotlib`, `ipykernel` installed.

### Run order

```powershell
# Script 1 — leakage audit (writes feature_catalogue_table with lag flags)
.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\03_leakage_audit.py

# Script 2 — feature catalogue (writes origination + monthly field metadata)
.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\04_feature_catalogue.py

# Notebook 1 — EDA (run via Jupyter or nbconvert; uses sample DB)
# jupyter nbconvert --to notebook --execute residential_mortgage/01_data_foundation/notebooks/02_eda.ipynb

# Notebook 2 — Observation windows diagram
# jupyter nbconvert --to notebook --execute residential_mortgage/01_data_foundation/notebooks/05_observation_windows.ipynb
```

### Outputs

| Output | Location | Description |
|---|---|---|
| `feature_catalogue_table` | `mortgages_sample.duckdb` | Per-field lag rules, leakage verdicts, population availability |
| `origination_restatements_table` | `mortgages_sample.duckdb` | Count of loans with restated origination fields per quarter |
| EDA report | `outputs/01_data_foundation/02_eda/` | Charts: balance distributions, delinquency histograms, state maps |
| Window diagram | `outputs/01_data_foundation/05_observation_windows/` | Timeline diagram of observation/performance windows |

> [!NOTE]
> `03_leakage_audit.py` writes `feature_catalogue_table` into the **sample** DB. Run with `--full` to also write to the full DB (required before Module 02 `--full` runs).

---

## Concepts

### `03_leakage_audit.py`

**Purpose:** Classify every field in the monthly performance file as either an observation-window feature (safe to use in model training) or a performance-window field (leakage if used as a feature at snapshot date $t_0$).

**Mathematical / analytical output:** A table with one row per field, columns: `field_name`, `leakage_verdict` (`safe` / `leakage` / `conditional`), `lag_rule` (`monthly_lag_1` = use at $t-1$ only), `first_population_month` (the earliest month when the field is non-null in the data).

**Concept embodied:** Target leakage prevention. In a performance-window outcome model (12-month default indicator), any feature that could reveal information about the future 12 months is a form of data leakage. The rule is: a feature for snapshot date $t_0$ may only use values known at $t_0 - 1$ (one-month lag). Fields like `zero_balance_code`, `upb_at_removal`, and `cure_month` are always leakage because they are only populated at or after the resolution event.

> [!WARNING]
> `payment_history`, `total_principal`, `borrower_assistance_plan`, and `alt_delinquency_resolution` are flagged as late-populated fields — they first appear in later data releases. Even with `monthly_lag_1`, their availability at model training time should be verified against the data release calendar.

---

### `04_feature_catalogue.py`

**Purpose:** Extend the leakage audit with population statistics (null rate, distribution metrics) for every origination and monthly field, and document the macro publication-lag rules for FRED and FHFA series.

**Mathematical / analytical output:** Enriched `feature_catalogue_table` with `null_pct`, `unique_pct`, and `sample_distribution` summary for each field. Marks macro fields with `pub_lag_months` (FRED unemployment: 1 month; FHFA HPI: 2 months) to indicate that the value available at snapshot month $t_0$ is actually the value published for month $t_0 - \text{pub\_lag}$.

**Concept embodied:** Data availability at model execution time. A model is only valid if every feature it uses would be available at the moment it scores a new loan. The catalogue forces an explicit declaration of when each field becomes known, preventing implicit future-data assumptions.

> [!IMPORTANT]
> The macro publication-lag enforcement is documented here but **not yet enforced at runtime** in `13_economy_links.py`. Before Module 3 feature selection, verify that `lag_months` for each macro series is set to at least `pub_lag_months` to avoid implicit leakage.
