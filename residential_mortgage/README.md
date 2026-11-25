# Residential Mortgage Credit Risk Platform (`residential_mortgage/`)

End-to-end UK PRA, CRR, and IFRS 9 residential mortgage modeling platform built over US Fannie Mae loan performance data (`2000Q1`–`2025Q4`, `57.6M` loans / `3.31B` monthly rows full; `17,275` loans / `994,063` rows in the GitHub-tracked `0.03%` stratified sample DB), using DuckDB + ZSTD Parquet as a single source of truth.

---

## Package Structure

```text
residential_mortgage/
├── _settings/                 # Platform TOMLs (paths, sampling, compute, sources), config.py, regulatory_parameters.py, windows.py
├── 00_data/                   # Ingestion, macro tables, 0.03% sample DB builder & centralized module_outputs/
├── 01_data_foundation/        # Leakage audit, feature catalogue, 02_eda.ipynb, 05_observation_windows.ipynb
├── 02_portfolio_analytics/    # 19-script Module 2 pipeline (00..18 + module2_common.py) & 14 synthetic unit tests
├── 03_rating_and_pd/          # Stubs (Module 3 — Rating & PD)
├── 04_lgd_ead/                # Stubs (Module 4 — LGD & EAD)
├── 05_ifrs9_ecl/              # Stubs (Module 5 — IFRS 9 ECL)
├── 06_basel_capital/          # Stubs (Module 6 — Basel Capital)
├── 07_stress_testing/         # Stubs (Module 7 — Stress Testing)
└── 08_model_risk_mgmt/        # Stubs & governance placeholders (Module 8 — Model Risk Management)
```

Every numbered module uses `scripts/`, `notebooks/`, `tests/`, and local `docs/` subfolders. Settings, path resolvers, regulatory thresholds, and canonical window definitions all live in [_settings/](_settings/):
- [_settings/config.py](_settings/config.py) — Loads `paths.toml`, `sampling.toml`, `compute.toml`, and `sources.toml`, and resolves `sample/` vs `full/` database and output paths.
- [_settings/regulatory_parameters.py](_settings/regulatory_parameters.py) — Single source of truth for PRA/FCA regulatory thresholds, source citations, and US-data departures.
- [_settings/windows.py](_settings/windows.py) — Canonical observation, performance, seasoning, probation, and projection windows.

---

## Data & Sample-First Execution Rules

Run every command from the repository root (`E:\Repos\V4_bank-credit-risk-platform`) using the repo's `.venv\Scripts\python.exe`. Operational defaults (paths, sampling rate, DuckDB memory/threads, chart DPI, macro URLs) live in `residential_mortgage\_settings\*.toml`.

All pipeline scripts and notebooks **default to the self-contained `0.03%` sample DB** (`mortgages_sample.duckdb`, `42.01 MB`) and write outputs under:
`residential_mortgage\00_data\processed\module_outputs\<module>\sample\<script>\`

Pass `--full` (or set `EDA_FULL='1'` / `WIN_FULL='1'` for notebooks) when intentionally running against the full `3.31B`-row dataset (`mortgages.duckdb` -> `full\`).

---

## How to Run

### Module 0: Data Ingestion, Macro Tables & Sample DB

| Step | Command | What it does | Mode |
|---|---|---|---|
| 1 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\01_convert_raw_to_parquet.py all` | Converts raw quarterly CSVs from `Performance_All.zip` to ZSTD Parquet + conversion ledgers | Full raw data |
| 2 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\02_build_base_tables.py all` | Builds `loans_table` and `loan_monthly_view` (`mortgages.duckdb`); 7 checks per quarter | Full (`--db` optional) |
| 3 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\03_build_macro_tables.py` | Loads FRED (`FEDFUNDS`, `UNRATE`) & FHFA HPI tables and PRA discount rates; 6 checks | Sample DB default (`--full` for production DB) |
| 4 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\04_build_sample_db.py` | Builds self-contained `0.03%` stratified `mortgages_sample.duckdb` (`42.01 MB`) from `mortgages.duckdb` | Reads full DB, writes sample DB |

See [00_data/README.md](00_data/README.md) for the Module 0 file and folder guide.

### Module 1: Data Foundation

| Step | Command | What it does |
|---|---|---|
| 1 | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\03_leakage_audit.py` | Classifies all 78 loan/monthly columns (`field_leakage_table`: 33 origination, 21 `t-1`, 19 quarantined, 5 keys); add `--full` for production DB |
| 2 | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\04_feature_catalogue.py` | Builds `feature_catalogue_table` and exports `feature_catalogue.md` under `module_outputs\01_data_foundation\`; add `--full` for production DB |
| 3 | See commands below | Runs [05_observation_windows.ipynb](01_data_foundation/notebooks/05_observation_windows.ipynb) and [02_eda.ipynb](01_data_foundation/notebooks/02_eda.ipynb) under `module_outputs\01_data_foundation\<sample|full>\` |

```powershell
$env:JUPYTER_PATH = 'E:\Repos\V4_bank-credit-risk-platform\.venv\share\jupyter'

# Observation/performance window coverage & censoring checks ('0' = 0.03% sample, '1' = full)
$env:WIN_FULL = '0'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\notebooks\05_observation_windows.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk

# 16-section Master EDA notebook ('0' = 0.03% sample, '1' = full)
$env:EDA_FULL = '0'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\notebooks\02_eda.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk
```

See [01_data_foundation/01_ingestion_design.md](01_data_foundation/01_ingestion_design.md) for ingestion architecture and view benchmarks.

### Module 2: Portfolio Analytics (`00` to `18`)

Defaults to the `0.03%` sample DB (`module2_sample.duckdb`, `26.51 MB` -> `module_outputs\02_portfolio_analytics\sample\`).
Pass `--full` for the `3.31B`-row production run (`module2.duckdb` -> `module_outputs\02_portfolio_analytics\full\`):

```powershell
# Default 0.03% stratified sample run (00 -> 18)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py

# Opt-in full 3.31B-row production run
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --full

# Preview commands without running, or resume from a specific step
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --dry-run
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --from-step 07

# Module 2 unit tests (14 synthetic known-answer checks)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\tests\test_module2.py
```

See [02_portfolio_analytics/README.md](02_portfolio_analytics/README.md) for the script table and mart dependencies.

### Modules 3 to 8 (Not Built Yet)

Each module follows the `scripts/`, `notebooks/`, `tests/`, `docs/` structure and reads defaults from `residential_mortgage/_settings/`. Commands will be added here as each module is built.
