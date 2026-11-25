# V4 Bank Credit Risk Platform

> **US conforming residential mortgages (Fannie Mae, 2000Q1–2025Q4) modeled and governed end-to-end under UK PRA, CRR, and IFRS 9 rules — using DuckDB + ZSTD Parquet as a single source of truth.**

All macroeconomic series paired with the loans (interest rates, unemployment, house prices) are US series matching the underlying USD collateral. Every point where a UK regulatory rule meets US mortgage or macroeconomic data is explicitly documented in the platform's regulatory registry ([residential_mortgage/regulatory_parameters.py](residential_mortgage/regulatory_parameters.py)) and summarized below under [UK Regulatory Alignment & Key US-Data Departures](#uk-regulatory-alignment--key-us-data-departures).

---

## Platform Roadmap: Built vs. Planned

The platform spans **Modules 0 through 8** under `residential_mortgage/`, organized cleanly per module with `scripts/`, `notebooks/`, `tests/`, and local `docs/` subfolders, and centralized settings under `residential_mortgage/settings/`. Modules 0 and 1 are built and verified, Module 2 is built and verified on the 0.03% stratified sample + synthetic tests (`--full` run opt-in), and Modules 3–8 are scaffolded placeholders (`sys.exit("Not built yet")`).

| Module | Folder | Scope | Status |
|---|---|---|---|
| **0 — Data Ingestion, Macro & Sample DB** | `residential_mortgage/00_data/` | Convert 104 quarters (113-field layout) to ZSTD Parquet, build `loans_table` + `loan_monthly_view`, load FRED + FHFA macro tables & LGD discount rates, generate self-contained `0.03%` `mortgages_sample.duckdb` | **Complete** (`57.6M` loans / `3.31B` rows full; `17,275` loans / `~1M` rows stratified sample DB) |
| **1 — Data Foundation** | `residential_mortgage/01_data_foundation/` | Ingestion design, 16-section Master EDA notebook (`notebooks/02_eda.ipynb`), field leakage quarantine (`03_leakage_audit.py`), approved feature catalogue (`04_feature_catalogue.py`), observation windows | **Core Complete / Minor WIP** (`field_leakage_table` & `feature_catalogue_table` complete for 78 loan fields; EDA charts saved under `module_outputs/01_data_foundation/sample/02_eda/`) |
| **2 — Portfolio Analytics** | `residential_mortgage/02_portfolio_analytics/` | 19-script pipeline (`scripts/00_build_monthly_core.py` through `scripts/18_portfolio_findings.py`): slim typed monthly core, balance waterfall & plausibility, UK default & probation engine, roll rates, 30-day backstop, emergence lag, CIF vintage curves, indexed & downward-only LTV, 12m DR & Vasicek rho, WOE/IV risk drivers, segmentation, workout outcomes & FSD, relief/forbearance & re-default, macro links, cycle benchmarks, mix/HHI, PSI/MoC representativeness, survivorship, mart findings | **Built & Sample-Verified** (`14/14` unit tests + default `0.03%` sample run verified into `module2_sample.duckdb`; full `--full` 3.31B-row production run opt-in) |
| **3 — Rating & PD** | `residential_mortgage/03_rating_and_pd/` | Application & behavioural scorecards (WoE/IV logistic), standalone PIT & TTC PD models, calibration & SS4/24 cyclicality, 15-grade master rating scale, validation (exact binomial, Brier, H-L, PSI, MoC, Pluto-Tasche) | **Planned** (7 placeholder stubs in `scripts/`) |
| **4 — LGD & EAD** | `residential_mortgage/04_lgd_ead/` | Workout LGD (`FEDFUNDS + 500 bps` floored at 9%), SS4/24 component LGD (`5%` floor), Expected Loss waterfall (`EL = PD × LGD × EAD`) & EL-vs-ECL bridge | **Planned** (3 placeholder stubs in `scripts/`) |
| **5 — IFRS 9 ECL** | `residential_mortgage/05_ifrs9_ecl/` | Stage 1/2/3 SICR triggers & 30 DPD backstop, Aalen-Johansen CIF lifetime PD term structures, scenario-sensitive LGD/EAD, multi-scenario ECL non-linearity, monthly ECL movement waterfall | **Planned** (5 placeholder stubs in `scripts/`) |
| **6 — Basel Capital** | `residential_mortgage/06_basel_capital/` | Standardised Approach RWA (Art. 124F/124L loan-splitting, Art. 124G Table 6B), retail AIRB Vasicek ASRF & output floor, Economic Capital (`VaR 99.9% - EL`), Euler allocation & RAROC | **Planned** (3 placeholder stubs in `scripts/`) |
| **7 — Stress Testing** | `residential_mortgage/07_stress_testing/` | ARDL cointegration macro satellites, Vasicek state inversion & 5-year capital projection (BoE 2025 BCST path), Mahalanobis reverse stress testing to CET1 < 4.5% | **Planned** (3 placeholder stubs in `scripts/`) |
| **8 — Model Risk Management** | `residential_mortgage/08_model_risk_mgmt/` | PRA SS1/23 governance layer (plus SR 11-7 / SR 26-2 reference): automated model inventory, conceptual soundness, independent validation reports, ongoing drift monitoring | **Planned** (2 stubs in `scripts/` + 2 doc placeholders) |

> Open items tracked ahead of Modules 3–8 include adding macroeconomic publication lags (`UNRATE` ~1m, HPI ~2m) to `03_leakage_audit.py` / `04_feature_catalogue.py`, aligning competing-exit censoring and snapshot dates in [residential_mortgage/windows.py](residential_mortgage/windows.py) / `05_observation_windows.ipynb`, and completing word-for-word PRA Rulebook / SS4/24 wording checks before capital and ECL sign-off.

---

## Core Architecture & Engineering Principles

- **DuckDB + Parquet Lake & Self-Contained Sample DB:** On the full 3.31B-row dataset (`--full`), monthly histories stay compressed in quarterly ZSTD Parquet files rather than duplicated in DuckDB, while `loans_table` materializes one latest-corrected row per loan and `loan_monthly_view` queries the Parquet lake directly. By default, every module runs on `mortgages_sample.duckdb` — a self-contained **0.03% per-quarter stratified DuckDB** (~`55 MB`, GitHub-tracked) carrying identical schemas (`loans_table`, `loan_monthly_view`, and full macro/catalogue tables) so anyone cloning this repo can execute every script and test without downloading 90 GB of raw files.
- **Explicit Object Naming:** Table names encode storage type: `*_table` (materialized base table), `*_view` (SQL view), and `*_mart` (reconciled analytical output table).
- **Strict Leakage Quarantine:** `03_leakage_audit.py` classifies all 78 loan/monthly columns into `origination` (33 usable, lag 0), `monthly_lag_1` (21 usable, `t-1`), `quarantined` (19 outcome/loss columns, target-only), and `key` (5 join/time keys) in `field_leakage_table` before modeling.
- **Sample Default & Opt-In `--full` Isolation:** Runs default to `sample/` paths (`mortgages_sample.duckdb`, `module2_sample.duckdb`, `module_outputs/<module>/sample/<script>/`) while explicit `--full` writes into isolated `full/` paths (`mortgages.duckdb`, `module2.duckdb`, `module_outputs/<module>/full/<script>/`). Same SQL and logic flow end-to-end; nothing overwrites production artifacts.
- **Centralized Settings & Regulatory Registry:** Operational settings (`paths.toml`, `sampling.toml`, `compute.toml`, `sources.toml`) live in `residential_mortgage/settings/` loaded via [residential_mortgage/config.py](residential_mortgage/config.py), while regulatory thresholds, articles, and departure notes live separately in [residential_mortgage/regulatory_parameters.py](residential_mortgage/regulatory_parameters.py).

---

## Measured Data Scope

| Dataset / Store | Coverage / Scale | Notes |
|---|---|---|
| **Fannie Mae Performance Data** | `2000Q1`–`2025Q4` (104 cohorts) | **57,597,528** unique loans; **3,314,483,004** monthly records; **12.63 trillion USD** original UPB reconciled to the cent; includes the 2007–2009 downturn |
| **Full Parquet Lake & Master DB** | ~26.04 GB Parquet, ~2.06 GiB `mortgages.duckdb` | Git-ignored under `residential_mortgage/00_data/{raw,processed}/` |
| **Stratified GitHub Sample (`0.03%`)** | `17,275` loans (~`1M` monthly rows across all 104 quarters) | Self-contained `mortgages_sample.duckdb` + `module2_sample.duckdb` (~`1–2 MB`) + sample charts tracked in Git |
| **Macro Series (FRED & FHFA)** | `macro_monthly_table` (322 months), `macro_state_hpi_table` (5,406 quarterly rows across 51 states/DC) | `FEDFUNDS` (FRED), `UNRATE` (FRED; Oct-2025 blank preserved via `unemployment_missing`), `hpi_master.csv` (FHFA); includes PRA LGD discount rates in `macro_economic_mart` |

---

## UK Regulatory Alignment & Key US-Data Departures

Work follows **UK PRA Rulebook** (Capital Requirements / IRB / CRM / SA Parts effective 1 January 2027), **SS11/13** & **SS4/24**, **PS9/24**, **IFRS 9**, **BoE BCST**, and **SS1/23**. The **15 documented departures** where US Fannie Mae loan or macro data differs from UK definitions include:
- **Currency & Macro Drivers:** Loans are USD conforming US mortgages backed by `FEDFUNDS`, `UNRATE`, and FHFA state/national HPI (rather than UK mortgages / SONIA / UK HPI).
- **LGD Discount Rates:** Long-run rate uses `ROUND(FEDFUNDS + 5, 4)` (adapting SONIA + 5%); downturn rate uses `GREATEST(9, FEDFUNDS + 5)` (a stricter floor over SS11/13 / PS9/24 "at least 9%").
- **Default Definition:** Arrears are reported in whole months (`>= 3` months for `> 90 DPD`) rather than exact days past due, with no past-due GBP/dollar amount (`£0 / 0%` retail materiality met by any arrears `>= 3` months) and `modification_flag` `N -> Y` transitions as the distressed-restructuring trigger.
- **COVID-19 Payment Deferrals:** Overlaid UK PRA/FCA deferral caps (6-month limit, `2020-03-01` to `2021-03-31` start window, `2021-07-31` hard end) onto longer US CARES Act forbearance histories.
- **Collateral Revaluation:** Quarterly FHFA state HPI indexation paired with the Standardised `> 10%` downward revaluation check.

> **Governance note:** All quantitative metrics and scripts carry verification status explicitly. Paragraph-level PRA Rulebook / SS4/24 wording checks are flagged inline in [residential_mortgage/regulatory_parameters.py](residential_mortgage/regulatory_parameters.py) ahead of Modules 3–7 sign-off.

---

## Repository Structure

```text
V4_bank-credit-risk-platform/
├── README.md
├── requirements.txt                         # Pinned Python 3.12 dependencies (DuckDB 2.0.0, pandas 3.1.1, matplotlib 3.11.2, Jupyter)
├── .gitignore                               # Ignores full data/Parquets/docs; tracks mortgages_sample.duckdb, module2_sample.duckdb & sample charts
├── references/
│   └── fannie_mae_glossary_file_layout.pdf  # Official Fannie Mae 113-field schema & glossary
└── residential_mortgage/
    ├── config.py                            # Central TOML settings & path resolver
    ├── how_to_run.md                        # Step-by-step execution guide
    ├── regulatory_parameters.py             # Centralized regulatory thresholds & parameters
    ├── windows.py                           # Observation/performance window helper (draft WIP)
    ├── settings/                            # Grouped TOML settings (paths, sampling, compute, sources)
    ├── 00_data/
    │   ├── scripts/                         # field_map.py, 01_convert_raw_to_parquet.py .. 04_build_sample_db.py
    │   ├── data_log.md                      # Auto-generated per-quarter ingestion ledger
    │   ├── raw/                             # fannie_mae/, macro/, parquet/ (gitignored via .gitkeep)
    │   └── processed/                       # Full DB + module_outputs/<module>/<sample|full>/<script>/
    ├── 01_data_foundation/                  # scripts/, notebooks/, tests/, docs/ + 01_ingestion_design.md
    ├── 02_portfolio_analytics/              # run_module2.py, scripts/ (00..18 + module2_common.py), tests/test_module2.py, notebooks/, docs/
    ├── 03_rating_and_pd/                    # scripts/, notebooks/, tests/, docs/ (Stubs — Module 3)
    ├── 04_lgd_ead/                          # scripts/, notebooks/, tests/, docs/ (Stubs — Module 4)
    ├── 05_ifrs9_ecl/                        # scripts/, notebooks/, tests/, docs/ (Stubs — Module 5)
    ├── 06_basel_capital/                    # scripts/, notebooks/, tests/, docs/ (Stubs — Module 6)
    ├── 07_stress_testing/                   # scripts/, notebooks/, tests/, docs/ (Stubs — Module 7)
    └── 08_model_risk_mgmt/                  # scripts/, notebooks/, tests/, docs/ + placeholder governance specs (Module 8)
```

---

## Setup & Prerequisites

### 1. Software & Python Environment
Python **3.12+** is used on Windows with `pip` and `.venv`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Pinned packages in [requirements.txt](requirements.txt): `duckdb==2.0.0`, `matplotlib==3.11.2`, `ipykernel==7.4.0`, `nbconvert==7.17.2`, `pandas==3.1.1`.

### 2. Data Layout (Sample Tracked in Git, Full Opt-In Locally)
- `residential_mortgage/00_data/processed/module_outputs/00_data/mortgages_sample.duckdb` — **Tracked in Git** (`0.03%` stratified sample, self-contained for development & CI).
- `residential_mortgage/00_data/processed/module_outputs/02_portfolio_analytics/sample/module2_sample.duckdb` + sample PNG charts & `18_portfolio_findings.md` — **Tracked in Git**.
- Full raw files (`raw/fannie_mae/`, `raw/parquet/`, `raw/macro/`) and full production DBs (`mortgages.duckdb`, `module2.duckdb`, large Parquet caches) are ignored by [.gitignore](.gitignore).

---

## How to Run

Run all commands from the repository root (`E:\Repos\V4_bank-credit-risk-platform`) using `.venv\Scripts\python.exe`. Every script defaults to the **0.03% sample DB** (`mortgages_sample.duckdb`); pass `--full` when intentionally running the full 3.31B-row dataset (`mortgages.duckdb`). See [residential_mortgage/how_to_run.md](residential_mortgage/how_to_run.md) for detailed notes.

### Module 0: Data Ingestion, Macro Tables & Sample DB

```powershell
# 1. Convert raw quarterly CSVs from Performance_All.zip to ZSTD Parquet (full raw pipeline)
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\01_convert_raw_to_parquet.py 2005Q1
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\01_convert_raw_to_parquet.py all

# 2. Build full DuckDB base tables (loans_table, loan_monthly_view) with 7 checks per quarter
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\02_build_base_tables.py all

# 3. Build FRED & FHFA macro tables and PRA LGD discount rates (defaults to sample DB; add --full for production)
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\03_build_macro_tables.py

# 4. Build self-contained 0.03% stratified mortgages_sample.duckdb from mortgages.duckdb
.venv\Scripts\python.exe residential_mortgage\00_data\scripts\04_build_sample_db.py
```

### Module 1: Data Foundation

```powershell
# Leakage classification & approved feature register (defaults to sample DB; add --full for full DB)
.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\03_leakage_audit.py
.venv\Scripts\python.exe residential_mortgage\01_data_foundation\scripts\04_feature_catalogue.py

# 16-section Master EDA notebook (defaults to 0.03% sample DB; set $env:EDA_FULL = '1' for full dataset)
$env:JUPYTER_PATH = "$PWD\.venv\share\jupyter"
$env:EDA_FULL = '0'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\notebooks\02_eda.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk
```

### Module 2: Portfolio Analytics (`00`–`18`)

```powershell
# Default 0.03% sample pipeline (writes module2_sample.duckdb & per-script outputs under sample/)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py

# Opt-in full 3.31B-row production run (writes module2.duckdb & outputs under full/)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --full

# Preview commands without running, or resume from a specific step
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --dry-run
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --from-step 07
```

Scripts can also be executed individually from `residential_mortgage\02_portfolio_analytics\scripts\` in dependency order (`00_build_monthly_core.py` through `18_portfolio_findings.py`). See [residential_mortgage/02_portfolio_analytics/README.md](residential_mortgage/02_portfolio_analytics/README.md) for the script-by-script table and mart dependencies.

---

## Testing & Verification

- **Synthetic Known-Answer Unit Suite:**
  ```powershell
  .venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\tests\test_module2.py
  ```
  Covers default trigger/probation transitions, art. 178(5A) restructuring, COVID deferral caps, HPI drawdown & downward-only LTV, non-MSA sentinel exclusions, recovery cash flows, and module output path isolation (`14` unit tests).
- **Pipeline Atomic Gates:** Every ingestion script (`7/7` checks per quarter), macro load (`6/6` checks), sample DB build (`7/7` checks), and Module 2 script (`Checker` assertions) fails fast if row counts, UPB reconciliations, or primary keys (`loan_id`, `(loan_id, reporting_period)`, `(loan_id, default_month)`) drift.

---

## Key Project Files

| File | Purpose |
|---|---|
| [residential_mortgage/config.py](residential_mortgage/config.py) | Loads TOML settings (`residential_mortgage/settings/`) and resolves `sample/` vs `full/` paths |
| [residential_mortgage/how_to_run.md](residential_mortgage/how_to_run.md) | Step-by-step execution guide across modules |
| [residential_mortgage/regulatory_parameters.py](residential_mortgage/regulatory_parameters.py) | Single source of truth for regulatory thresholds, sources, and departure notes |
| [residential_mortgage/00_data/README.md](residential_mortgage/00_data/README.md) | Module 0 script order and data layout guide |
| [residential_mortgage/01_data_foundation/01_ingestion_design.md](residential_mortgage/01_data_foundation/01_ingestion_design.md) | Ingestion layout, storage architecture, and Parquet view benchmark measurements |
| [residential_mortgage/02_portfolio_analytics/README.md](residential_mortgage/02_portfolio_analytics/README.md) | Module 2 script-by-script reference and mart dependency map (`00`–`18`) |
| [residential_mortgage/00_data/data_log.md](residential_mortgage/00_data/data_log.md) | Auto-generated per-quarter ingestion ledger (`2000Q1`–`2025Q4`) |
| [references/fannie_mae_glossary_file_layout.pdf](references/fannie_mae_glossary_file_layout.pdf) | Official Fannie Mae 113-field file layout and field definitions |
| [requirements.txt](requirements.txt) | Pinned Python dependencies |
