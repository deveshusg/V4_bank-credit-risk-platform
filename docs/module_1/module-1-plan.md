# Module 1 plan: data foundation

Date: 2026-11-14. Status: updated 2026-11-15 (full load done; D-020 to D-025).
Source: docs\v4_build_plan_revised.md, lines 88-178.
Paths: all Module 1 files and datasets live under residential_mortgage\00_data\ and residential_mortgage\01_data_foundation\.
Packages: duckdb 2.0.0 and matplotlib 3.11.2 (D-015); pandas 3.1.1, ipykernel 7.4.0, nbconvert 7.17.2 for the EDA notebook (D-024).

## Current data footprint (measured 2026-11-15)
- Source: residential_mortgage\00_data\raw\fannie_mae\Performance_All.zip (62.8 GB compressed, 934.92 GB of text, 104 quarters 2000Q1 to 2025Q4).
- Parquet files: residential_mortgage\00_data\raw\parquet\YYYYQn.parquet, 26.04 GB in total (35.9 times smaller than the text).
- Database: residential_mortgage\00_data\processed\mortgages.duckdb, 2.22 GB (loans_table about 2.04 GB; loan_monthly_view reads the Parquet files).
- Temporary scratch: E:\Repos\V4_bank-credit-risk-platform\.scratch\ (extracted text deleted after each quarter).

## Execution sequence

1. **00_data\field_map.py (COMPLETE)**
   - Maps all 113 positions from Fannie Mae's layout to column names, data types and targets (loans, loans_first, loan_monthly, not_loaded).
   - Checks that positions run 1 to 113 and names are unique.

2. **00_data\convert_raw_to_parquet.py (COMPLETE: 104 of 104 quarters converted)**
   - Extracts YYYYQn.csv to .scratch\, streams it into YYYYQn.parquet.tmp with ZSTD compression, checks Parquet rows = raw lines, then renames to .parquet.
   - Writes YYYYQn.conversion.json next to the Parquet file: raw lines and bytes, Parquet rows and bytes, times, DuckDB version.
   - --record-only back-fills records from the zip without writing text files.
   - Resumable: skips quarters whose Parquet file and record agree.

3. **00_data\build_base_tables.py (COMPLETE: 104 of 104 quarters loaded, every quarter 8 of 8 checks PASS)**
   - Loads unique loans into loans_table (latest corrected value per D-017; seller name and MSA: earliest non-blank value, D-027).
   - Builds loan_monthly_view over the loaded quarters' Parquet files, adding acquisition_quarter.
   - Draws the 10% development subset (sampled_loans_table, seed 42, 1 thread).
   - Runs 8 checks per quarter inside one transaction; rolls back on any FAIL:
     1. Parquet rows = raw_lines from YYYYQn.conversion.json.
     2. Unique loans in loans_table = distinct loan ids in Parquet.
     3. Original UPB: A (first month) + R (restated change) + B (blank first month) = loaded total.
     4. No loan already loaded under another quarter.
     5. No duplicate (loan_id, reporting_period), no NULL loan_id, no unreadable dates.
     6. No non-blank value fails conversion.
     7. Allowed values for exit codes, Modification Flag and delinquency status.
     8. Subset count = ROUND(0.10 x unique loans), using DuckDB's ROUND on both sides (D-023).
   - Writes loaded_quarters_table and an entry in data_log.md for each quarter.
   - Post-load checks (run 2026-11-15): 11 of 11 PASS.

3b. **00_data\build_macro_tables.py (fixed under D-025; rebuilt on the full database 2026-11-15, 6 of 6 checks PASS)**
   - Loads the federal funds rate (FRED FEDFUNDS), unemployment (FRED UNRATE) and the FHFA house price index into macro_monthly_table (322 months), macro_state_hpi_table (5,406 rows), macro_monthly_view, macro_sources_table and macro_economic_mart. Downloads only with --force-download.
   - Changes over 1 and 12 months are taken by date. A month missing in a source stays blank and is flagged (October 2025 unemployment).
   - LGD discount rates per month, taken for the month of default: long-run = federal funds rate + 5% (SS11/13 13.13A); downturn = the higher of 9% and the long-run rate (SS11/13 13.13, 13.13B; PS9/24 3.141; "higher of" is our stricter choice). Departures: docs\departures_from_uk_rules.md.
   - Reviewer re-check 2026-11-15: all High and Medium findings fixed. Checks 2 and 5 then tightened (D-026): unemployment may be blank only in a known gap; every state must have every quarter from 2000Q1.

4. **01_data_foundation\01_ingestion_design.md (DRAFT, full-load numbers added)**
   - Plain-words account of the pipeline, the checks, decisions D-016 to D-023, naming, field treatment and measured numbers.
   - Open: review by readers with no earlier context.

5. **01_data_foundation\02_eda.ipynb (D-024; plan signed off 2026-11-15)**
   - Follows plan\master_eda_plan.md (copy in docs\module_1\master_eda_plan.md): 16 sections, provisional outcome decided loan by loan, field classes read from field_leakage_table and feature_catalogue_table, intervals instead of p-values, checks C1 to C8.
   - Charts to 02_eda_outputs\charts\, tables to 02_eda_outputs\tables\.
   - Open: notebook being changed to the signed-off plan; then run with --sample and on the full data.
   - Open item for Module 2: when 02_default_engine.py builds default_events_mart, replace build_loan_outcome() with a read of that mart and rerun.

6. **01_data_foundation\03_leakage_audit.py (COMPLETE: run on the full database 2026-11-15, PASS)**
   - Classifies the 78 columns: 33 origination, 21 monthly with a one-month lag, 19 quarantined, 5 keys. Writes field_leakage_table.
   - Open: economic data lags (unemployment about 1 month, house prices about 2 months) are stated in the EDA, not yet in field_leakage_table.

7. **01_data_foundation\04_feature_catalogue.py**
   - Writes feature_catalogue_table and exports docs\module_1\feature_catalogue.md.

## Measured numbers
- Full load: 3,314,483,004 monthly rows; 57,597,528 loans; original UPB 12,629,831,311,000.00; subset 5,759,759 loans.
- Conversion: 2.42 hours extracting and 6.60 hours converting for the 88 quarters with recorded times; about 40 to 50 seconds per raw GB.
- Base build: 4.74 hours in total (sum of the quarter load times).
- A full pass over loan_monthly_view takes about 3 minutes: rows by month 183 s, delinquency spread 182 s, join to loans_table 276 s. Workable for Module 1; typed Parquet is the next step if later modules need many full passes.
