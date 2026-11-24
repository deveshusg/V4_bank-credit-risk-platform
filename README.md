# Bank credit risk platform

> The loans are US conforming residential mortgages from Fannie Mae, assessed under UK rules.

The data that goes with the loans (interest rates, unemployment, house prices) is US too.
Every place a UK rule meets US data is listed in
[docs\departures_from_uk_rules.md](docs/departures_from_uk_rules.md): the UK rule, what we
do, why, and the likely effect.

## Folders
Data files live under `residential_mortgage\00_data\` and are excluded from git:
- `raw\fannie_mae\`: holds the raw `Performance_All.zip` archive.
- `raw\parquet\`: holds compressed quarterly Parquet files and conversion records (`YYYYQn.conversion.json`).
- `processed\`: holds the DuckDB database (`mortgages.duckdb`).

## Setup
Python 3.12 with pip and DuckDB 2.0.0.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Data ingestion pipeline

### 1. Convert raw CSV files to Parquet
Extracts quarterly CSV members from the archive and streams them into compressed Parquet files with line-count verification and conversion records:

```powershell
# Convert a single quarter
python residential_mortgage\00_data\convert_raw_to_parquet.py 2005Q1

# Convert a range of quarters
python residential_mortgage\00_data\convert_raw_to_parquet.py 2000Q1 2008Q4

# Convert all quarters
python residential_mortgage\00_data\convert_raw_to_parquet.py all

# Back-fill conversion records without rewriting Parquet files
python residential_mortgage\00_data\convert_raw_to_parquet.py all --record-only
```

### 2. Build base tables in DuckDB
Reads the quarterly Parquet files, loads unique loans into `loans_table`, draws the 10% development subset (`sampled_loans_table`), runs 8 structural integrity checks, reconciles original balances, and creates `loan_monthly_view`:

```powershell
# Ingest a single quarter
python residential_mortgage\00_data\build_base_tables.py 2005Q1

# Ingest a range of quarters
python residential_mortgage\00_data\build_base_tables.py 2000Q1 2008Q4

# Ingest all available quarters
python residential_mortgage\00_data\build_base_tables.py all
```
