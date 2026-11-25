# How to run

Run every command from the repo folder (`E:\Repos\V4_bank-credit-risk-platform`) with the
repo's Python: `.venv\Scripts\python.exe`. Settings (paths, sampling rate, DuckDB memory/threads,
chart DPI, macro URLs) live in `residential_mortgage\settings\*.toml`.

All pipeline scripts **default to the self-contained 0.03% sample database** (`mortgages_sample.duckdb`)
and write outputs under `residential_mortgage\00_data\processed\module_outputs\<module>\sample\<script>\`.
Pass `--full` when intentionally running against the full 3.31B-row dataset (`mortgages.duckdb` -> `full\`).

## Module 0: data ingestion, macro & sample DB

| Step | Command | What it does | Mode |
|---|---|---|---|
| 1 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\01_convert_raw_to_parquet.py all` | Converts raw quarterly CSVs to ZSTD Parquet + conversion ledgers | Full raw data |
| 2 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\02_build_base_tables.py all` | Builds `loans_table` and `loan_monthly_view` (`mortgages.duckdb`); 7 checks per quarter | Full (`--db` optional) |
| 3 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\03_build_macro_tables.py` | Loads FRED (`FEDFUNDS`, `UNRATE`) & FHFA HPI tables and PRA discount rates; 6 checks | Sample DB default (`--full` for production DB) |
| 4 | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\04_build_sample_db.py` | Builds self-contained 0.03% stratified `mortgages_sample.duckdb` (~55 MB) from `mortgages.duckdb` | Reads full DB, writes sample DB |

## Module 1: data foundation

| Step | Command | What it does |
|---|---|---|
| 1 | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\03_leakage_audit.py` | Classifies all 78 loan/monthly columns (`field_leakage_table`); add `--full` for production DB |
| 2 | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\04_feature_catalogue.py` | Builds `feature_catalogue_table` and exports `feature_catalogue.md` under `module_outputs\01_data_foundation\`; add `--full` for production DB |
| 3 | See below | Runs `02_eda.ipynb` (writes to `module_outputs\01_data_foundation\sample\02_eda\`) |

```powershell
$env:JUPYTER_PATH = 'E:\Repos\V4_bank-credit-risk-platform\.venv\share\jupyter'
$env:EDA_FULL = '0'   # set '1' for full dataset run
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\notebooks\02_eda.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk
```

## Module 2: portfolio analytics (`00` to `18`)

Defaults to the 0.03% sample DB (`module2_sample.duckdb` -> `module_outputs\02_portfolio_analytics\sample\`).
Pass `--full` for the 3.31B-row production run (`module2.duckdb` -> `module_outputs\02_portfolio_analytics\full\`):

```powershell
# Default 0.03% stratified sample run (00 -> 18)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py

# Opt-in full 3.31B-row production run
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --full

# Module 2 unit tests (14 synthetic known-answer checks)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\tests\test_module2.py
```

See [02_portfolio_analytics/README.md](02_portfolio_analytics/README.md) for the script table and dependencies.

## Modules 3 to 8 (not built yet)

Each module follows the `scripts/`, `notebooks/`, `tests/`, `docs/` structure and reads defaults from `residential_mortgage/settings/`. Commands will be added here as each module is built.
