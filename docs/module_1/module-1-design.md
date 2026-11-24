# Module 1 design: data foundation

Status: signed off by Devesh 2026-11-14; amended by D-016 (full data, development sample), D-017 (origination fields restated in data), D-018 (Parquet files and DuckDB views), D-019 (explicit names), D-020 (ingestion fixes), D-024 (EDA notebook, provisional outcome) and D-025 (US data under UK rules; macro tables fixed after design\module-1-macro-review.md). Source plan: docs\v4_build_plan_revised.md, lines 88-178.

## Why
Every later module (defaults, roll rates, PD, LGD, ECL, capital, stress) reads loan history. Module 1 loads that history cleanly, proves nothing was lost or changed, describes the data, and fixes which fields each later module may use.

The raw data is 935 GB of text (337 GB for 2000-2008). To avoid running out of memory, the platform uses two steps:
1. Raw Parquet files: raw CSV text is converted quarter by quarter into compressed Parquet files (residential_mortgage\00_data\raw\parquet\).
2. DuckDB tables and view: loans_table is stored as a physical table in processed\mortgages.duckdb; loan_monthly_view is a view that reads the Parquet files directly without duplicating data.

All loans are stored. A fixed 10% seeded subset (sampled_loans_table) is kept for fast development runs via --sample.

## Naming convention
Names show what each object is:
- *_table: physical DuckDB tables (loans_table, sampled_loans_table, loaded_quarters_table, origination_restatements_table).
- *_view: views that read Parquet files directly (loan_monthly_view).
- *_mart: downstream analytical data marts.

## Data source statement
The loans are US conforming residential mortgages from Fannie Mae, assessed under UK rules.

## Decisions this design rests on
- D-013: files under residential_mortgage\; 2005Q1 test; temporary extracted files on E: are deleted.
- D-014: plan and signed-off design are copied to docs\module_1\.
- D-015: packages are duckdb 2.0.0 and matplotlib 3.11.2, pinned in requirements.txt.
- D-016: load whole quarters, all 104 in the end. The development subset is used through each script's --sample switch.
- D-017: origination fields take the latest non-blank value (Fannie Mae's corrected value). Seller name (5) and MSA (32) take the earliest non-blank value (D-027). Changes within a loan are counted in origination_restatements_table, not failed.
- D-018: two-step ingestion. Stage 1 (convert_raw_to_parquet.py) writes Parquet files. Stage 2 (build_base_tables.py) builds the base tables and view. Root data\ removed; all data lives under residential_mortgage\00_data\ (raw\fannie_mae\, raw\parquet\, processed\mortgages.duckdb).
- D-019: explicit suffixes for tables, views, and marts.
- D-020: conversion record per quarter; Check 1 against raw lines; Check 3 as an exact reconciliation; key checks and delinquency status validation; view built only from loaded quarters; ASCII output; build_db.py deleted; feature_catalogue.md in docs\module_1\.
- D-021: fixes to the D-020 changes: --record-only exits 1 on any FAIL; a missing record is back-filled, not re-converted; Check 3's B uses the latest value; data_log.md written after COMMIT.
- D-023: Check 8 takes its expected subset size from the same DuckDB ROUND that draws the subset.
- D-024: the EDA is a notebook (02_eda.ipynb) with a provisional outcome for the EDA only. Plan: plan\master_eda_plan.md, signed off 2026-11-15.
- D-022: economic data. build_macro_tables.py loads the federal funds rate (FRED FEDFUNDS), unemployment (FRED UNRATE) and the FHFA house price index (HPI Master) into macro_monthly_table, macro_state_hpi_table, macro_monthly_view, macro_economic_mart and macro_sources_table in mortgages.duckdb. 6 checks inside one transaction.
- D-025 (US data under UK rules): data that goes with the loans is US. Every place a UK rule meets US data is listed in docs\departures_from_uk_rules.md. Macro fixes from design\module-1-macro-review.md: no filled months, changes by date, checks that can fail, citations limited to SS11/13 13.13, 13.13A, 13.13B and PS9/24 3.141.

## Input
- 104 quarterly files in residential_mortgage\00_data\raw\fannie_mae\Performance_All.zip, named YYYYQn.csv (2000Q1 to 2025Q4). Pipe-delimited, no header, no quote characters.
- Layout: references\fannie_mae_glossary_file_layout.pdf (11/9/2026), 118 fields. Every line has 113 fields (positions 1-113). Positions 114-118 were added in 2026 and are not in these files.

## Scripts (all under residential_mortgage\)
1. 00_data\field_map.py: maps positions 1-113 to column names, data types, and targets (loans, loans_first, loan_monthly, not_loaded). Self-validates position continuity and unique names.
2. 00_data\convert_raw_to_parquet.py [YYYYQn | --from YYYYQn --to YYYYQn | all | --record-only]:
   - Extracts CSV from zip into .scratch\ on E:.
   - Streams CSV directly into YYYYQn.parquet.tmp with ZSTD compression.
   - Validates that Parquet rows match raw CSV lines, then atomically renames to YYYYQn.parquet.
   - Writes YYYYQn.conversion.json next to the Parquet file with line and byte counts, timings, and DuckDB version.
   - Auto-deletes temporary extracted CSV from .scratch\.
   - Option --record-only streams directly from zip without extracting to disk to write or back-fill conversion records.
   - Skips quarters where both .parquet and .conversion.json exist and row counts match.
3. 00_data\build_base_tables.py [YYYYQn | --from YYYYQn --to YYYYQn | all]:
   - Reads from residential_mortgage\00_data\raw\parquet\.
   - Creates residential_mortgage\00_data\processed\mortgages.duckdb.
   - Loads unique loans into loans_table (latest corrected values per D-017).
   - Rebuilds loan_monthly_view over the Parquet files of loaded quarters only, adding acquisition_quarter.
   - Draws the 10% seeded development subset into sampled_loans_table (reservoir(N ROWS) REPEATABLE (42), 1 thread).
   - Runs 8 checks inside one transaction per quarter; rolls back on any FAIL.
   - Writes loaded quarter details to loaded_quarters_table and prepends an entry to data_log.md for default database runs.
3b. 00_data\build_macro_tables.py [--db PATH] [--force-download] (D-022, fixed under D-025):
   - Reads the economic source files from 00_data\raw\macro\: federal funds rate (FRED FEDFUNDS), unemployment rate (FRED UNRATE) and house price index (FHFA HPI Master).
   - Downloads only when asked (--force-download). A missing file without the flag stops the run. Downloads use curl --fail, check the file's first line, and keep the old file as <name>.<old file date>.csv before replacing it.
   - Records each series in macro_sources_table: source URL, date the file was saved (download date), first and last observation, rows read and publication delay.
   - Builds a month calendar from 1998-01 to the last month in the federal funds file (a blank last month fails check 2, it is not dropped). Changes over 1 and 12 months are taken by date (period minus 1 or 12 months), not by row. A change that spans a missing month is blank.
   - A month missing in a source stays blank and is flagged (unemployment_missing). Nothing is filled in. October 2025 unemployment is blank in the source.
   - Creates macro_monthly_table (2000-01 to the last federal funds month: 322 months, 2000-01 to 2026-10, on today's files), macro_state_hpi_table (51 states x 106 quarters = 5,406 rows today), macro_monthly_view and the macro features table macro_economic_mart.
   - LGD discount rates in macro_economic_mart, one per calendar month, to be joined on the month of default (not the reporting month):
     long-run = federal funds rate + 5% (SS11/13 13.13A: SONIA at the moment of default + 5% for GBP, "a comparable liquid interest rate in the currency of that exposure" otherwise);
     downturn = the higher of 9% and the long-run rate (SS11/13 13.13, a 9% floor for downturn LGD, with the same floor for LGD in-default in 13.13B; PS9/24 3.141 "at least 9%"). The "higher of" is our stricter choice, not the PRA's wording.
     SS4/24 replaces SS11/13 from 1 January 2027; its paragraph numbers are not yet confirmed, so it is not cited by paragraph.
     The federal funds rate is a monthly average, not the rate on the day of default. All departures from UK rules: docs\departures_from_uk_rules.md.
   - Values sit on the first day of their own month or quarter, before they were published (unemployment about 1 month later, national house prices about 2 months, state house prices about 2 months after the quarter ends). The leakage audit must lag them.
   - Runs the 6 macroeconomic checks inside one transaction; prints PASS/FAIL for each; rolls back and exits 1 on any FAIL.
4. 01_data_foundation\01_ingestion_design.md: plain-words document with benchmark numbers, design decisions, and field definitions.
5. 01_data_foundation\02_eda.ipynb (D-024): describes the data (spread, missing values, impossible values, correlations, drift by vintage, active loans by month), with a provisional outcome (bad / good) for bad rates, Information Value, PSI drift and a population waterfall. Saves PNG charts and CSV tables to 02_eda_outputs\. The provisional outcome is replaced by default_events_mart once Module 2 builds it.
6. 01_data_foundation\03_leakage_audit.py: classifies every loan_monthly_view field into allowed or quarantined (with lag rules) to prevent target leakage.
7. 01_data_foundation\04_feature_catalogue.py: approved field register, saved as a DuckDB table and exported to docs\module_1\feature_catalogue.md.

## Tables and views in mortgages.duckdb
- loans_table (TABLE; unique key: loan_id): origination dimensions (FICO, LTV, DTI, balance, rate, purpose, state, term). Measured: 57,597,528 loans across all 104 quarters.
- loan_monthly_view (VIEW over loaded quarters in raw\parquet\*.parquet; unique key: loan_id, reporting_period): monthly performance records (balances, DPD, exit reasons, modifications, acquisition_quarter).
- sampled_loans_table (TABLE; loan_id, acquisition_quarter, sample_rate, seed, duckdb_version): 10% seeded development subset.
- loaded_quarters_table (TABLE): ledger recording quarter, loaded_at, raw_csv_bytes, raw_lines, parquet_bytes, parquet_rows, loans, monthly_rows, orig_upb_first_month, orig_upb_restated, orig_upb_blank_first, orig_upb_total, load_seconds, duckdb_version.
- origination_restatements_table (TABLE): counts of loans with restated origination fields.
- macro_monthly_table (TABLE; unique key: period): monthly national series (federal_funds_rate_pct, unemployment_rate_pct, unemployment_missing, national house price index) and their 1-month and 12-month changes.
- macro_state_hpi_table (TABLE; unique key: state, quarter_date): quarterly state house price index and its 12-month change, used to update property values. No UK rule names an index or a geography; see entry 6 of docs\departures_from_uk_rules.md.
- macro_monthly_view (VIEW over macro_monthly_table).
- macro_economic_mart (TABLE, the macro features table; unique key: period): the monthly series, their changes and the two LGD discount rates.
- macro_sources_table (TABLE; one row per series): source URL, file saved date, first and last observation, rows read, publication delay.

## Data treatment
- Delinquency status becomes whole months (INTEGER). "99" means 99 or more. "XX" becomes NULL with is_dpd_unknown = TRUE. A blank becomes NULL.
- Zero Balance Code is preserved, and exit_reason holds its label: 01 prepaid/matured, 02 third-party sale, 03 short sale, 06 repurchased, 09 deed-in-lieu/REO, 15 non-performing note sale, 16 reperforming note sale, 96 removal. Blank allowed. Any other code fails.
- Modification Flag: Y, N or blank.
- Current UPB: stored as given. Imputation of initial unpopulated UPB is moved to the module that first needs it.
- Conversions: numbers and dates converted with TRY_CAST. Any non-blank conversion failure is counted and fails validation.

## Checks for each quarter (inside one transaction, rolls back on FAIL)
1. Parquet rows = raw_lines from YYYYQn.conversion.json. Missing record = FAIL.
2. Unique loans in loans_table for the quarter = count(DISTINCT loan_id) in the Parquet file.
3. Original UPB reconciliation:
   A = sum of each loan's first-month orig_upb (by reporting period);
   R = sum over loans of (latest non-blank orig_upb - first-month orig_upb), for loans where they differ and first month is not blank;
   B = sum of the latest non-blank orig_upb for loans whose first month is blank
       (the value loans_table holds for them; D-021);
   PASS if A + R + B = sum(orig_upb) in loans_table for the quarter (exact decimal).
4. No loan already in loans_table under another quarter = 0.
5. No duplicate (loan_id, reporting_period) = 0, AND rows with NULL loan_id or unreadable reporting_period = 0.
6. Non-blank values that fail TRY_CAST = 0.
7. Allowed values = 0 violations: zero_balance_code in EXIT_REASONS or NULL; modification_flag in ('Y','N') or NULL; delinquency_status NULL, 'XX', or regex '^[0-9]{1,2}$'.
8. sampled_loans_table count = ROUND(0.10 x unique loans).

## Macroeconomic checks (inside one transaction, rolls back on FAIL; each one can fail)
1. First month is 2000-01-01, last month is at least 2025-12-01, and no month is missing between them. In a normal build the month calendar makes the months complete, so a gap in a source file is caught by check 2 (rates) or check 3 (house prices); check 1 guards the table itself.
2. No blank period or federal funds rate. Unemployment is blank only where unemployment_missing is TRUE, and only in a known gap (October 2025, listed in the script) or after its last published month. No blank state house price index (seasonally adjusted, not adjusted, all sales).
3. Bounds: federal funds rate 0 to 25, unemployment 2 to 20, national and state house price index above 50 where present. No blank national index month before its last published month. Each series runs close to the last federal funds month: national index at most 3 months behind, unemployment at most 2 months, state index (dated on the first day of its quarter) at most 9 months.
4. No duplicate month in macro_monthly_table or macro_economic_mart. No duplicate (state, quarter_date) in macro_state_hpi_table.
5. Exactly 51 states (50 states and DC), each with every quarter from 2000Q1 to the last quarter in the table, with no gap.
6. On every row of macro_economic_mart: long-run rate = federal funds rate + 5, downturn rate = the higher of 9 and the long-run rate, and neither is blank.


## Measured numbers (full load, 2026-11-15)
- 104 quarters, every one 8 of 8 checks PASS; post-load checks 11 of 11 PASS.
- 3,314,483,004 monthly rows; 57,597,528 loans; original UPB 12,629,831,311,000.00; subset 5,759,759 loans.
- Raw text 934.92 GB; Parquet files 26.04 GB (35.9 times smaller); mortgages.duckdb 2.22 GB (loans_table about 2.04 GB).
- Conversion about 40 to 50 seconds per raw GB; base build 4.74 hours in total.
- One full pass over loan_monthly_view takes about 3 minutes (183 s, 182 s and 276 s for the three timed queries). Typed Parquet is the next step only if later modules need many full passes.
