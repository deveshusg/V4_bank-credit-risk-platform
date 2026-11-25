# V4 Bank Credit Risk Platform

> **US conforming residential mortgages (Fannie Mae, 2000Q1–2025Q4) modeled and governed end-to-end under UK PRA, CRR, and IFRS 9 rules — using DuckDB + ZSTD Parquet as a single source of truth.**

All macroeconomic series paired with the loans (interest rates, unemployment, house prices) are US series matching the underlying USD collateral. Every point where a UK regulatory rule meets US mortgage or macroeconomic data is explicitly documented in the platform's regulatory registry ([residential_mortgage/regulatory_parameters.py](residential_mortgage/regulatory_parameters.py)) and summarized below under [UK Regulatory Alignment & Key US-Data Departures](#uk-regulatory-alignment--key-us-data-departures).

---

## Platform Roadmap: Built vs. Planned

The platform spans **Modules 0 through 8** under `residential_mortgage/`. Modules 0 and 1 are verified on the full 104-quarter population, Module 2 is built and verified on the 10% development sample + synthetic tests (full-population run pending), and Modules 3–8 are scaffolded placeholders (`sys.exit("Not built yet")`).

| Module | Folder | Scope | Status |
|---|---|---|---|
| **0 — Data Ingestion & Macro** | `residential_mortgage/00_data/` | Extract 104 quarters (113-field layout) to ZSTD Parquet, build `loans_table` / `sampled_loans_table` / `loan_monthly_view`, load FRED + FHFA macro tables & LGD discount rates | **Complete** (full 57.6M loans / 3.31B rows reconciled; 8/8 per-quarter checks & 6/6 macro checks pass) |
| **1 — Data Foundation** | `residential_mortgage/01_data_foundation/` | Ingestion design, 16-section Master EDA, field leakage quarantine (`field_leakage_table`), approved feature catalogue (`feature_catalogue_table`), observation windows | **Core Complete / Minor WIP** (`03_leakage_audit.py` & `04_feature_catalogue.py` complete for 78 loan fields; EDA pass on 10% sample; macro publication lags & `windows.py` / `05_observation_windows.ipynb` censoring/alignment pending) |
| **2 — Portfolio Analytics** | `residential_mortgage/02_portfolio_analytics/` | 19-script pipeline (`00_build_monthly_core.py` through `18_portfolio_findings.py`): slim typed monthly core, balance waterfall & plausibility, UK default & probation engine, roll rates, 30-day backstop, emergence lag, CIF vintage curves, indexed & downward-only LTV, 12m DR & Vasicek rho, WOE/IV risk drivers, segmentation, workout outcomes & FSD, relief/forbearance & re-default, macro links, cycle benchmarks, mix/HHI, PSI/MoC representativeness, survivorship, mart findings | **Built & Sample-Verified** (`14/14` unit tests + `--sample` 331.46M-row run verified; full 3.31B-row production run pending) |
| **3 — Rating & PD** | `residential_mortgage/03_rating_and_pd/` | Application & behavioural scorecards (WoE/IV logistic), standalone PIT & TTC PD models, calibration & SS4/24 cyclicality, 15-grade master rating scale, validation (exact binomial, Brier, H-L, PSI, MoC, Pluto-Tasche) | **Planned** (7 placeholder stubs) |
| **4 — LGD & EAD** | `residential_mortgage/04_lgd_ead/` | Workout LGD (`FEDFUNDS + 500 bps` floored at 9%), SS4/24 component LGD (`5%` floor), Expected Loss waterfall (`EL = PD × LGD × EAD`) & EL-vs-ECL bridge | **Planned** (3 placeholder stubs) |
| **5 — IFRS 9 ECL** | `residential_mortgage/05_ifrs9_ecl/` | Stage 1/2/3 SICR triggers & 30 DPD backstop, Aalen-Johansen CIF lifetime PD term structures, scenario-sensitive LGD/EAD, multi-scenario ECL non-linearity, monthly ECL movement waterfall | **Planned** (5 placeholder stubs) |
| **6 — Basel Capital** | `residential_mortgage/06_basel_capital/` | Standardised Approach RWA (Art. 124F/124L loan-splitting, Art. 124G Table 6B), retail AIRB Vasicek ASRF & output floor, Economic Capital (`VaR 99.9% - EL`), Euler allocation & RAROC | **Planned** (3 placeholder stubs) |
| **7 — Stress Testing** | `residential_mortgage/07_stress_testing/` | ARDL cointegration macro satellites, Vasicek state inversion & 5-year capital projection (BoE 2025 BCST path), Mahalanobis reverse stress testing to CET1 < 4.5% | **Planned** (3 placeholder stubs) |
| **8 — Model Risk Management** | `residential_mortgage/08_model_risk_mgmt/` | PRA SS1/23 governance layer (plus SR 11-7 / SR 26-2 reference): automated model inventory, conceptual soundness, independent validation reports, ongoing drift monitoring | **Planned** (2 stubs + 2 doc placeholders) |

> Open items tracked ahead of Modules 3–8 include adding macroeconomic publication lags (`UNRATE` ~1m, HPI ~2m) to `03_leakage_audit.py` / `04_feature_catalogue.py`, aligning competing-exit censoring and snapshot dates in [residential_mortgage/windows.py](residential_mortgage/windows.py) / `05_observation_windows.ipynb`, and completing word-for-word PRA Rulebook / SS4/24 wording checks before capital and ECL sign-off.

---

## Core Architecture & Engineering Principles

- **DuckDB + Parquet Lake Architecture:** Monthly loan histories (~3.31B rows) stay compressed in quarterly ZSTD Parquet files rather than duplicated in DuckDB. `loans_table` materializes one latest-corrected row per loan; `loan_monthly_view` queries the Parquet lake directly; Module 2 builds a slim 23-column typed core (`loan_monthly_core`) and lightweight output marts (`module2_marts.duckdb`) for Modules 3–8.
- **Explicit Object Naming:** Table names encode storage type: `*_table` (materialized base table), `*_view` (query view over Parquet/tables), and `*_mart` (reconciled analytical output table).
- **Strict Leakage Quarantine:** `03_leakage_audit.py` classifies all 78 loan/monthly columns into `origination` (33 usable, lag 0), `monthly_lag_1` (21 usable, `t-1`), `quarantined` (19 outcome/loss columns, target-only), and `key` (5 join/time keys) in `field_leakage_table` before modeling.
- **Isolated 10% Development Mode (`--sample`):** A deterministic 10% loan sample (`sampled_loans_table`, seed `42`, 1 thread, `5,759,759` loans) isolates development runs into `monthly_core_sample/`, `module2_marts_sample.duckdb`, `outputs_sample/`, and `18_portfolio_findings_sample.md` so experiments never overwrite production artifacts.
- **Central Regulatory Registry:** [residential_mortgage/regulatory_parameters.py](residential_mortgage/regulatory_parameters.py) stores every threshold and regulatory rate alongside its source article, check date, and project choice / data departure note.

---

## Measured Data Scope

| Dataset / Store | Coverage / Scale | Notes |
|---|---|---|
| **Fannie Mae Performance Data** | `2000Q1`–`2025Q4` (104 cohorts) | **57,597,528** unique loans; **3,314,483,004** monthly records; **12.63 trillion USD** original UPB reconciled to the cent; includes the 2007–2009 downturn |
| **Parquet Lake & Master DB** | ~26.04 GB Parquet, ~2.22 GB `mortgages.duckdb` | Git-ignored under `residential_mortgage/00_data/{raw,processed}/` |
| **Development Sample (`10%`)** | 5,759,759 loans (~331.46M monthly rows) | Verified across Module 1 EDA and Module 2 `00`–`18` sample run |
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
├── .gitignore                               # Excludes local environments, private working notes, and raw/processed datasets
├── references/
│   └── fannie_mae_glossary_file_layout.pdf  # Official Fannie Mae 113-field schema & glossary
├── residential_mortgage/
│   ├── how_to_run.md                        # Step-by-step execution guide
│   ├── regulatory_parameters.py             # Centralized regulatory thresholds & parameters
│   ├── windows.py                           # Observation/performance window helper (draft WIP)
│   ├── 00_data/                             # Parquet conversion, DuckDB base tables, FRED/FHFA macro pipeline, field_map.py, data_log.md
│   ├── 01_data_foundation/                  # Ingestion design, 16-section EDA notebook, leakage audit, feature catalogue
│   ├── 02_portfolio_analytics/              # Module 2 pipeline (00–18 + module2_common.py, run_module2.py, README.md)
│   ├── 03_rating_and_pd/                    # Stubs (Module 3)
│   ├── 04_lgd_ead/                          # Stubs (Module 4)
│   ├── 05_ifrs9_ecl/                        # Stubs (Module 5)
│   ├── 06_basel_capital/                    # Stubs (Module 6)
│   ├── 07_stress_testing/                   # Stubs (Module 7)
│   └── 08_model_risk_mgmt/                  # Stubs & placeholder governance files (Module 8)
└── tests/
    └── test_module2.py                      # Synthetic known-answer unit tests for Module 2 (14 tests)
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

### 2. External Data Placement (Not Stored in Git)
Raw source files and generated databases are ignored by [.gitignore](.gitignore):
- `residential_mortgage/00_data/raw/fannie_mae/` — holds Fannie Mae `Performance_All.zip`.
- `residential_mortgage/00_data/raw/parquet/` — holds extracted quarterly ZSTD Parquet files and `YYYYQn.conversion.json` ledgers.
- `residential_mortgage/00_data/raw/macro/` — holds `fedfunds.csv`, `unrate.csv`, and `hpi_master.csv` (or fetched via `--force-download`).
- `residential_mortgage/00_data/processed/` — holds `mortgages.duckdb` (and Module 2 `monthly_core*/`, `module2_marts*.duckdb`).

---

## How to Run

Run all commands from the repository root (`E:\Repos\V4_bank-credit-risk-platform`) using `.venv\Scripts\python.exe`. Each script prints a summary and exits with `PASS` or `FAIL`. See [residential_mortgage/how_to_run.md](residential_mortgage/how_to_run.md) for detailed notes.

### Module 0: Data Ingestion & Macro Tables

```powershell
# 1. Convert raw quarterly CSVs from Performance_All.zip to ZSTD Parquet (single quarter, range, or all)
.venv\Scripts\python.exe residential_mortgage\00_data\convert_raw_to_parquet.py 2005Q1
.venv\Scripts\python.exe residential_mortgage\00_data\convert_raw_to_parquet.py 2000Q1 2008Q4
.venv\Scripts\python.exe residential_mortgage\00_data\convert_raw_to_parquet.py all
.venv\Scripts\python.exe residential_mortgage\00_data\convert_raw_to_parquet.py all --record-only

# 2. Build DuckDB base tables (loans_table, sampled_loans_table, loan_monthly_view) with 8 checks per quarter
.venv\Scripts\python.exe residential_mortgage\00_data\build_base_tables.py 2005Q1
.venv\Scripts\python.exe residential_mortgage\00_data\build_base_tables.py 2000Q1 2008Q4
.venv\Scripts\python.exe residential_mortgage\00_data\build_base_tables.py all

# 3. Build FRED & FHFA macro tables and PRA LGD discount rates (add --force-download to fetch CSVs)
.venv\Scripts\python.exe residential_mortgage\00_data\build_macro_tables.py
```

### Module 1: Data Foundation

```powershell
# Leakage classification & approved feature register
.venv\Scripts\python.exe residential_mortgage\01_data_foundation\03_leakage_audit.py
.venv\Scripts\python.exe residential_mortgage\01_data_foundation\04_feature_catalogue.py

# 16-section Master EDA notebook (set $env:EDA_SAMPLE = '1' for the 10% development sample)
$env:JUPYTER_PATH = "$PWD\.venv\share\jupyter"
$env:EDA_SAMPLE = '1'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace residential_mortgage\01_data_foundation\02_eda.ipynb --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=v4-credit-risk
```

### Module 2: Portfolio Analytics (`00`–`18`)

Run the 10% sample end-to-end first (`--sample`), or omit `--sample` for a full-population run (`3.31B` monthly rows):

```powershell
# Python runner — full 19-script pipeline on 10% sample (recommended first)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --sample

# Python runner — full 3.31B-row production run (writes module2_marts.duckdb, charts, and findings report)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py

# Preview commands without running, or resume from a specific step
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --sample --dry-run
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --sample --from-step 07
```

Scripts can also be executed individually in dependency order (`00_build_monthly_core.py` through `18_portfolio_findings.py`), passing `--sample` during development. See [residential_mortgage/02_portfolio_analytics/README.md](residential_mortgage/02_portfolio_analytics/README.md) for the script-by-script table and mart dependencies.

---

## Testing & Verification

- **Synthetic Known-Answer Unit Suite:**
  ```powershell
  .venv\Scripts\python.exe tests\test_module2.py
  ```
  Covers default trigger/probation transitions, art. 178(5A) restructuring, COVID deferral caps, HPI drawdown & downward-only LTV, non-MSA sentinel exclusions, recovery cash flows, and `--sample` SQL paths (`14` unit tests).
- **Pipeline Atomic Gates:** Every ingestion script (`8/8` checks per quarter), macro load (`6/6` checks), and Module 2 script (`Checker` assertions) fails fast if row counts, UPB reconciliations, or primary keys (`loan_id`, `(loan_id, reporting_period)`, `(loan_id, default_month)`) drift.

---

## Key Project Files

| File | Purpose |
|---|---|
| [residential_mortgage/how_to_run.md](residential_mortgage/how_to_run.md) | Step-by-step execution guide for data ingestion and Module 1 |
| [residential_mortgage/regulatory_parameters.py](residential_mortgage/regulatory_parameters.py) | Single source of truth for regulatory thresholds, sources, and departure notes |
| [residential_mortgage/01_data_foundation/01_ingestion_design.md](residential_mortgage/01_data_foundation/01_ingestion_design.md) | Ingestion layout, storage architecture, and Parquet view benchmark measurements |
| [residential_mortgage/02_portfolio_analytics/README.md](residential_mortgage/02_portfolio_analytics/README.md) | Module 2 script-by-script reference and mart dependency map (`00`–`18`) |
| [residential_mortgage/00_data/data_log.md](residential_mortgage/00_data/data_log.md) | Auto-generated per-quarter ingestion ledger (`2000Q1`–`2025Q4`) |
| [references/fannie_mae_glossary_file_layout.pdf](references/fannie_mae_glossary_file_layout.pdf) | Official Fannie Mae 113-field file layout and field definitions |
| [requirements.txt](requirements.txt) | Pinned Python dependencies |
