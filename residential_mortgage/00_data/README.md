# Module 00 — Data Ingestion

Converts Fannie Mae Single-Family Performance raw text files into a typed, queryable DuckDB database.
Four scripts run once per data refresh; outputs feed every downstream module.

---

## Operations

### Prerequisites

- Raw Fannie Mae acquisition + performance text files extracted under `raw/fannie_mae/`.
- Python 3.11+ virtual environment activated (`.venv\Scripts\activate`).
- `duckdb`, `pandas`, `pyarrow` installed (`pip install -r requirements.txt`).

### Run order

```powershell
# Step 1 — convert raw text → Parquet (run once per new quarter)
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\01_convert_raw_to_parquet.py

# Step 2 — build typed DuckDB base tables from Parquet
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\02_build_base_tables.py

# Step 3 — build macro-economic tables (FRED, FHFA HPI)
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\03_build_macro_tables.py

# Step 4 — build 0.03% stratified sample database
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\04_build_sample_db.py
```

### Outputs

| Output | Path | Size (sample) | Description |
|---|---|---|---|
| Quarterly Parquet files | `raw/parquet/fannie_mae/<YYYY>Q<N>.parquet` | varies | ZSTD-compressed, one file per acquisition quarter (2000Q1–2025Q4) |
| Full database | `raw/duckdb/mortgages.duckdb` | ~2.22 GB | `loans_table`, `loan_monthly_view`, `loaded_quarters_table`, macro tables |
| Sample database | `raw/duckdb/mortgages_sample.duckdb` | 44.05 MB | 17,275 loans · 994,063 monthly rows · 12 objects |

### Expected output from each script

Each script prints a `PASS/FAIL` summary from the `Checker` class. Exit code 0 = all checks pass.

### Environment flags

| Setting | File | Default | Effect |
|---|---|---|---|
| `sampling.rate` | `_settings/sampling.toml` | `0.0003` | Hash-based sample fraction |
| `sampling.seed` | `_settings/sampling.toml` | (integer) | Deterministic sample selection |
| `duckdb.memory_limit` | `_settings/compute.toml` | `"6GB"` | DuckDB RAM cap |
| `duckdb.threads` | `_settings/compute.toml` | (integer) | Parallelism |

---

## Concepts

### `01_convert_raw_to_parquet.py`

**Purpose:** Parse Fannie Mae pipe-delimited text files (acquisition + performance) and write one ZSTD-compressed Parquet file per acquisition quarter.

**Mathematical / analytical output:** No modelling — pure ETL. Applies `TRY_CAST` on every column and coerces date fields (`%m%Y` → `DATE`). Produces `loaded_quarters_table` with per-quarter row counts, loan counts, and min/max `reporting_period` for downstream reconciliation.

**Concept embodied:** Data provenance and reproducibility. The quarter-level `loaded_quarters_table` is the authoritative ledger of what raw data has been ingested; every downstream script verifies row counts against it.

---

### `02_build_base_tables.py`

**Purpose:** Assemble typed DuckDB tables (`loans_table`, `loan_monthly_view`, `origination_restatements_table`) from the quarterly Parquet files. Runs 7 validation checks per quarter.

**Mathematical / analytical output:** No modelling. 7 assertions per quarter: (1) row count matches ledger, (2) `(loan_id, reporting_period)` unique key, (3) `current_upb ≥ 0`, (4) `reporting_period` parseable, (5) `delinquency_months` in {0..12, NULL, 'XX'}, (6) `zero_balance_code` in known set, (7) `orig_upb > 0` for every loan's first row.

**Concept embodied:** Data quality gates at ingestion. Any quarter that fails even one check stops the pipeline and must be investigated before proceeding.

---

### `03_build_macro_tables.py`

**Purpose:** Load FRED macroeconomic series (unemployment, GDP, 30-year FRM rates) and FHFA state-level house price indices into `macro_economic_mart` and `macro_state_hpi_table`. Derives the LGD discount rate series.

**Mathematical / analytical output:**
- LGD discount rate: $r_d(t) = \max\left(9\%, \bar{r}_{\text{long-run}}\right)$ adapted from FEDFUNDS + 500 bps (departure D-025 from SONIA+500bps UK rule).
- National HPI: quarterly SA index from FHFA, used in LTV indexation across all modules.
- State HPI: 50-state quarterly SA series from FHFA, used in `06_current_ltv.py` and `07_default_rate_history.py`.

**Concept embodied:** Collateral value dynamics. House prices govern LTV at time of default and therefore drive LGD — the most important driver of mortgage credit loss. The FHFA SA index is the standard IRB property index for US residential mortgages.

---

### `04_build_sample_db.py`

**Purpose:** Create `mortgages_sample.duckdb` containing a deterministic 0.03% stratified sample of loans and all associated monthly performance rows, plus the full macro tables.

**Mathematical / analytical output:** No modelling. Sample predicate: `abs(hash(loan_id)) % 10000 < 3` (approximately 0.03%). 7 checks verify the sample counts match the expected fraction of the full DB.

**Concept embodied:** Reproducible development database. The hash-based sample is deterministic across runs (same seed → same loans every time), ensuring test results are comparable. The sample fraction is set so the sample DB fits in memory (44.05 MB) for fast interactive development while preserving realistic population distribution.
