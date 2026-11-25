# `residential_mortgage` — Package Architecture & Runbook

[← Back to Platform Showcase](../README.md) · [_settings/](_settings/) · [Module 0 Guide](00_data/README.md) · [Ingestion Design](01_data_foundation/01_ingestion_design.md) · [Module 2 DAG](02_portfolio_analytics/README.md)

> [!NOTE]
> **Sample-First Default (`0.03%` Stratified DB):** Every script and notebook runs against the self-contained [mortgages_sample.duckdb](00_data/processed/module_outputs/00_data/mortgages_sample.duckdb) (`42.01 MB`, `17,275` loans across `104/104` quarters) and writes into isolated `sample/` folders under `00_data/processed/module_outputs/`. Passing `--full` (or `EDA_FULL='1'` / `WIN_FULL='1'`) switches to full `mortgages.duckdb` (`full/` outputs) using the exact same SQL and business logic.

---

## Package Layout & Conventions

```text
residential_mortgage/
├── _settings/                   # Centralized TOMLs, config loader, regulatory thresholds & time windows
│   ├── __init__.py
│   ├── paths.toml               # Data directories, DB filenames, scratch & module_outputs paths
│   ├── sampling.toml            # Stratified sample rate (0.0003), seed (42) & correlation subsample cap (100_000)
│   ├── compute.toml             # DuckDB RAM/thread limits (6GB/8GB, 4 threads), zip chunk size & 300 DPI charts
│   ├── sources.toml             # Acquisition quarter range (2000Q1–2025Q4) & FRED/FHFA endpoints/known gaps
│   ├── config.py                # TOML loader & sample/full path resolution helpers
│   ├── regulatory_parameters.py # Single source of truth for PRA/FCA thresholds & departures
│   └── windows.py               # Canonical observation, performance, seasoning, probation & projection windows
├── 00_data/                     # Base ingestion, macro tables, 0.03% sample builder & centralized module_outputs/
├── 01_data_foundation/          # Leakage quarantine, feature catalogue & EDA/window notebooks
├── 02_portfolio_analytics/      # 19-script analytics pipeline (run_module2.py) & 14 synthetic unit tests
├── 03_rating_and_pd/            # Module 3 stubs (7 scripts)
├── 04_lgd_ead/                  # Module 4 stubs (3 scripts)
├── 05_ifrs9_ecl/                # Module 5 stubs (5 scripts)
├── 06_basel_capital/            # Module 6 stubs (3 scripts)
├── 07_stress_testing/           # Module 7 stubs (3 scripts)
└── 08_model_risk_mgmt/          # Module 8 stubs & governance templates
```

Every numbered module (`00_data` through `08_model_risk_mgmt`) follows one consistent internal structure:
- `scripts/` — sequentially numbered runnable Python scripts (`01_...`, `02_...`)
- `notebooks/` — Jupyter `.ipynb` exploratory and validation workbooks
- `tests/` — synthetic known-answer unit test suites
- `docs/` — module-local working notes and design documents *(gitignored)*

---

## Configuration & Environment Overrides

| File / Override | Controls | Default Value |
|---|---|---|
| [_settings/paths.toml](_settings/paths.toml) | Raw, macro, Parquet, processed, scratch & `module_outputs` paths; DB filenames | `mortgages_sample.duckdb` / `mortgages.duckdb` |
| [_settings/sampling.toml](_settings/sampling.toml) | Stratified sample fraction, RNG seed & correlation row cap | `rate = 0.0003`, `seed = 42`, `corr_subsample_rows = 100_000` |
| [_settings/compute.toml](_settings/compute.toml) | DuckDB memory limits, thread count, ZIP chunk size & chart DPI | `memory_limit = "6GB"`, `convert_memory_limit = "8GB"`, `threads = 4`, `dpi = 300` |
| [_settings/sources.toml](_settings/sources.toml) | Quarter range, FRED (`FEDFUNDS`, `UNRATE`) & FHFA URLs, known blank gap months | `2000Q1`–`2025Q4`; `known_unemployment_gaps = ["2025-10-01"]` |
| `EDA_FULL` / `WIN_FULL` | Notebook mode switch (`'0'` = sample DB, `'1'` = full `mortgages.duckdb`) | `'0'` (sample default via `os.environ.setdefault`) |
| `EDA_MIN_CELL` | Minimum cell loan threshold in `02_eda.ipynb` | `30` (`sample`) / `1000` (`full`) |

### Sample vs. Full Execution Matrix

| Mode | Trigger | Base DB Read | Module 2 Mart DB | Outputs Path |
|---|---|---|---|---|
| **Sample (Default)** | *(no flag)* / `EDA_FULL='0'` | `mortgages_sample.duckdb` (`42.01 MB`) | `module2_sample.duckdb` (`26.51 MB`) | `00_data/processed/module_outputs/<module>/sample/<script>/` |
| **Full (Opt-In)** | `--full` / `EDA_FULL='1'` | `mortgages.duckdb` (`~2.06 GiB` + Parquet lake) | `module2.duckdb` | `00_data/processed/module_outputs/<module>/full/<script>/` |

---

## Step-by-Step Execution Commands

> Run every command from the **repository root** using `.venv\Scripts\python.exe`.

### Module 0: Data Ingestion, Macro & Sample DB ([00_data/README.md](00_data/README.md))

| Step | Command | Purpose & Mode |
|---|---|---|
| `01` | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\01_convert_raw_to_parquet.py all` | Convert raw Fannie Mae quarterly CSVs from `Performance_All.zip` to ZSTD Parquet *(full raw data; pass single quarter e.g. `2005Q1` to test)* |
| `02` | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\02_build_base_tables.py all` | Materialize `loans_table` + `loan_monthly_view` into `mortgages.duckdb`; `7` atomic checks/quarter *(`--db` optional)* |
| `03` | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\03_build_macro_tables.py` | Load FRED & FHFA macro tables + PRA LGD discount rates; `6` checks *(sample DB default; add `--full` for `mortgages.duckdb`)* |
| `04` | `.venv\Scripts\python.exe residential_mortgage\00_data\scripts\04_build_sample_db.py` | Build standalone `0.03%` per-quarter stratified `mortgages_sample.duckdb` (`7` checks) |

### Module 1: Data Foundation (`01_data_foundation/`)

| Step | Command | Purpose |
|---|---|---|
| `03` | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\03_leakage_audit.py` | Classify all `78` loan & monthly fields (`field_leakage_table`; add `--full` for production DB) |
| `04` | `.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\04_feature_catalogue.py` | Build `feature_catalogue_table` & export `feature_catalogue.md` *(add `--full` for production DB)* |

**Run Module 1 Notebooks via `nbconvert` (or open with kernel `v4-credit-risk`):**

```powershell
$env:JUPYTER_PATH = "$PWD\.venv\share\jupyter"

# Observation & performance window censoring audit ('0' = sample default, '1' = full DB)
$env:WIN_FULL = '0'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\notebooks\05_observation_windows.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk

# 16-section Master EDA notebook ('0' = sample default, '1' = full DB + 10% hash subset for histories)
$env:EDA_FULL = '0'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\notebooks\02_eda.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk
```

### Module 2: Portfolio Analytics (`02_portfolio_analytics/`)

```powershell
# Default 0.03% sample pipeline (00 -> 18, writes module2_sample.duckdb + charts/findings under sample/)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py

# Opt-in full 3.31B-row production run (writes module2.duckdb + outputs under full/)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --full

# Dry-run preview or resume from a specific step (00..18)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --dry-run
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --from-step 07

# Run all 14 synthetic known-answer unit tests (pytest / unittest compatible)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\tests\test_module2.py
```

See [02_portfolio_analytics/README.md](02_portfolio_analytics/README.md) for the script-by-script table and mart dependencies.

### Modules 3 to 8 (`03_rating_and_pd/` – `08_model_risk_mgmt/`)

Scaffolded with standard `scripts/`, `notebooks/`, `tests/`, and `docs/` folders. All scripts resolve inputs and thresholds from `_settings/` (`from _settings import config, windows`). Execution commands will be added here as each module moves from stub to implementation.

---

## Centralized Output Layout & `.gitignore` Boundary

All built artifacts write inside `00_data/processed/module_outputs/`:

```text
00_data/processed/module_outputs/
├── 00_data/
│   └── mortgages_sample.duckdb                         # Tracked (42.01 MB standalone 0.03% DB)
├── 01_data_foundation/
│   ├── sample/
│   │   ├── 02_eda/{charts/*.png, tables/*.csv}         # PNG charts tracked; CSV tables gitignored
│   │   ├── 04_feature_catalogue/feature_catalogue.md   # Generated markdown (gitignored)
│   │   └── 05_observation_windows/{charts/*.png, tables/*.csv}
│   └── full/                                           # Entirely gitignored
└── 02_portfolio_analytics/
    ├── sample/
    │   ├── module2_sample.duckdb                       # Tracked (26.51 MB sample marts)
    │   ├── 00_build_monthly_core/*.parquet             # Ignored (104 typed Parquets)
    │   ├── {01..13}_*/ *.png                           # Tracked (8 analytical PNG charts)
    │   ├── {07_default_rate_history,09_risk_drivers}/book_snapshot*/ # Ignored Parquets
    │   └── 18_portfolio_findings/18_portfolio_findings.md            # Tracked
    └── full/                                           # Entirely gitignored
```
