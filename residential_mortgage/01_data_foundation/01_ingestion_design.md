# Module 1: how the loan data is loaded

Status: reviewed 2026-11-15 (plain-words review and a check against the code). Full-load
numbers in section 11.

## 1. What this document covers

Every later module reads the same loan history:
- defaults;
- roll rates (how loans move between arrears stages);
- PD (probability of default);
- LGD (loss given default);
- ECL (expected credit loss);
- capital and stress tests.

This document explains how that history is loaded, how we prove nothing was lost or changed
on the way, and how each field is treated. It also records the measured times and sizes.
Short forms used in the text are listed in section 12.

## 2. The data

- Source: Fannie Mae's single-family loan performance files.
- The loans are US conforming residential mortgages from Fannie Mae, assessed under UK
  rules.
- 104 quarterly files, 2000Q1 to 2025Q4, held in one zip file. Each file covers the loans
  Fannie Mae bought in that quarter. It holds one row per loan per month, up to December
  2025.
- About 935 GB of text in total (337 GB for 2000 to 2008).
- Each row has 113 fields, separated by a pipe character (|). Fannie Mae's file layout
  (glossary and file layout, dated 11/9/2026) lists 118 fields. The last 5 were added in
  2026 and are not in these files.

## 3. The two-stage load

```
Raw zip (935 GB of text)
   |
   |  Stage 1: convert_raw_to_parquet.py, one quarter at a time
   v
One Parquet file per quarter, plus a conversion record
   |
   |  Stage 2: build_base_tables.py, one quarter at a time
   v
DuckDB database: loans_table and other tables, plus loan_monthly_view
```

- **Parquet** is a compressed file format that stores data column by column.
- **DuckDB** is the database that holds the tables and reads the Parquet files.
- **A view** is a saved query: it shows the monthly rows without copying them into the
  database.

**Why two stages.** The text is too large to load in one step. The first attempt loaded a
quarter straight from text into the database. The computer ran out of working memory and
slowed badly. Splitting the work fixes this:

1. Stage 1 turns each quarter's text into a Parquet file. This is done once. The text is
   unpacked to a temporary folder, converted, checked and then deleted.
2. Stage 2 builds one row per loan into `loans_table`. The monthly rows are not copied
   into the database. `loan_monthly_view` reads them straight from the Parquet files, so
   they are stored only once.

**Restarting.** Both stages work one quarter at a time and skip quarters already done.

**When a quarter fails.** In stage 2, if any check fails, nothing from that quarter is kept.
The script stops and prints FAIL with the check and the numbers. Whoever runs the load reads
the reason, fixes the cause, and runs the same command again. Quarters already loaded are
skipped.

**Where the files are:**

| What | Where |
|---|---|
| Raw zip | `residential_mortgage\00_data\raw\fannie_mae\Performance_All.zip` |
| Parquet files and conversion records | `residential_mortgage\00_data\raw\parquet\YYYYQn.parquet` and `YYYYQn.conversion.json` |
| Database | `residential_mortgage\00_data\processed\mortgages.duckdb` |
| Load log | `residential_mortgage\00_data\data_log.md` |
| Temporary unpacked text | `.scratch\` at the top of the repo (the `--scratch` switch can move it); deleted after each quarter |

## 4. The conversion record

Stage 1 writes a small record, `YYYYQn.conversion.json`, next to each Parquet file. It
holds:

- the number of lines and bytes in the raw text file;
- the number of rows and bytes in the Parquet file;
- how long the unpacking and conversion took;
- the DuckDB version used.

Stage 1 only keeps a Parquet file if its row count equals the raw line count. Stage 2 then
checks the Parquet file against this record again (check 1 below), so a lost row cannot pass
unseen.

**When a Parquet file has no record:**
- `convert_raw_to_parquet.py --record-only` counts the raw lines straight from the zip and
  writes the record. It exits with an error if any quarter fails.
- A normal run that finds such a file writes the record the same way. It converts the
  quarter again only if the counts differ.

## 5. The 8 checks for each quarter

Stage 2 runs these checks on every quarter. If any check fails, nothing from that quarter is
kept.

1. **No rows lost.** Rows in the Parquet file equal the raw lines in the conversion record.
   A missing record is a fail.
2. **Every loan loaded once.** Loans in `loans_table` for the quarter equal the distinct
   loan ids in the Parquet file.
3. **Original balance adds up exactly.** The original balance (original UPB) of each loan
   is reported every month. `loans_table` keeps its latest value. The check proves that
   no balance was lost or invented on the way:
   - total original balance in `loans_table`
   - = first-month balances (A)
   - \+ later restatements (R)
   - \+ balances first reported after a blank first month (B),

   to the cent.
   - A: the sum of each loan's original UPB in its first month.
   - R: for loans whose original UPB was later restated, the total change (latest minus
     first month).
   - B: for loans with a blank first month, their latest original UPB.
4. **No loan in two quarters.** No loan in the quarter is already loaded under another
   quarter. A loan in two quarters would be counted twice in every total.
5. **No duplicate months.** No loan has two rows for the same month. No row has a blank
   loan id or a month that cannot be read.
6. **No unreadable values.** In every loaded number or date field, no non-blank value fails
   to read. Fields that are not loaded (section 8) are not checked.
7. **Only allowed codes.** Exit reason codes, Modification Flag and delinquency status hold
   only the values listed in section 9.
8. **Development subset has the right size.** The subset holds 10% of the quarter's loans,
   rounded to a whole loan (0.5 rounds up).

## 6. Decisions behind the design

Decisions are numbered as in the project's decision log. D-001 to D-015 set up the project
(folders, packages, tools) and do not change how the data is loaded. The ones below do.

- **D-016: full data, with a development subset.** All loans in all 104 quarters are
  loaded. A fixed 10% subset of loans (`sampled_loans_table`) is kept for building and
  testing scripts. It is picked by a fixed random rule, so the same loans are chosen every
  run. Later scripts take `--sample` to work on the subset. Final runs use the full data.
- **D-017: origination values.** Fannie Mae sometimes restates an origination field during
  a loan's life, usually to correct it. `loans_table` keeps the latest non-blank value, which
  is the corrected one. Seller name and MSA are the exception: they keep the earliest
  non-blank value (D-027). Restatements are counted in `origination_restatements_table`.
  They are not treated as errors.
- **D-018: Parquet files and views.** The two-stage load in section 3.
- **D-019: explicit names.** Every database object's name ends in what it is (section 7).
- **D-020: fixes to the first build.** Each closes a gap found when the first build was
  reviewed:
  - each quarter now has a conversion record, so the raw line count is kept;
  - check 1 compares against that raw line count;
  - check 3 is an exact reconciliation, to the cent;
  - check 5 also catches blank loan ids and unreadable months;
  - check 7 also covers delinquency status;
  - the view covers only quarters that loaded in full;
  - screen output is plain text, so every console can show it;
  - the old single-step loader was removed.
- **D-021: fixes to D-020.**
  - Check 3's B used the first available value, not the value `loans_table` holds. Now it
    uses the latest non-blank value.
  - `--record-only` reported success even when a quarter failed. Now it exits with an error.
  - A Parquet file without a record was converted again. Now the record is filled in from
    the zip.
  - The load log showed a fixed "PASS" line. Now it shows the raw file size, the top 3
    restated fields and the real check count.
  - A problem writing the log undid a good load. Now the log is written after the quarter
    is saved.
- **D-022, D-025 and D-026: economic data.** Interest rate, unemployment and house price
  tables are built by `build_macro_tables.py`. They are described in the Module 1 design,
  not here.
- **D-023: rounding fix in check 8.** The expected subset size rounded 0.5 to the nearest
  even number, while the subset itself was drawn rounding 0.5 up. For 2019Q1, 10% of
  341,865 loans is 34,186.5, so the check expected 34,186 and found 34,187. Both now round
  0.5 up. Subset sizes do not change.

## 7. Naming rules

- Database objects end in what they are:
  - `_table`: a table stored in the database;
  - `_view`: a saved query that reads the Parquet files and stores nothing itself;
  - `_mart`: a table built for analysis by later modules (today only `macro_economic_mart`).
- Column names are lower case with underscores, taken from `field_map.py` (for example
  `orig_upb`, `credit_score`, `delinquency_status`).
- Quarters are written `YYYYQn`, for example `2005Q1`.

Objects built by stage 2:

| Name | What it holds | One row per |
|---|---|---|
| `loans_table` | Origination details: credit score, LTV, DTI, balance, rate, purpose, state, term | loan |
| `loan_monthly_view` | Monthly performance: balance, delinquency, exit reason, modification, plus `acquisition_quarter` | loan and month |
| `sampled_loans_table` | The 10% development subset, with sample rate, seed and DuckDB version | loan in the subset |
| `loaded_quarters_table` | Each loaded quarter: raw and Parquet sizes, row and loan counts, the check 3 totals, load time | quarter |
| `origination_restatements_table` | For each origination field, how many loans had two or more different non-blank values. A change from blank to a value is not counted. Only fields with at least one such loan get a row. | quarter and field |

## 8. Field classes

`field_map.py` gives each of the 113 fields a class. The class says where the value goes.

| Class | Where the value goes | Fields | Examples |
|---|---|---|---|
| key | Both `loans_table` and `loan_monthly_view` | 2 | loan id, reporting month |
| loans | `loans_table`, latest non-blank value | 31 | original UPB, credit score, original LTV, DTI, property state |
| loans_first | `loans_table`, earliest non-blank value | 2 | seller name, MSA |
| loan_monthly | `loan_monthly_view`, one value per month | 37 | current UPB, delinquency status, Modification Flag, exit reason code, foreclosure costs |
| not_loaded | Not loaded: the layout marks them "not applicable" for single-family data | 41 | reference pool id, list prices, credit-risk-transfer gains and losses |
| **Total** | | **113** | |

## 9. Data treatment

- **Delinquency status.** Stored as given, plus two added columns:
  - `delinquency_months`: the number of months behind, as a whole number. "99" means 99
    months or more.
  - "XX" means the status is not known. It gives a blank `delinquency_months`, and
    `is_dpd_unknown` is set to true. (DPD is the usual short form for days past due. Fannie
    Mae reports whole months, so the column counts months.)
  - A blank stays blank.
  - Allowed values: blank, "XX", or a number of one or two digits.
- **Exit reason codes.** The code is kept, and `exit_reason` holds its label:

  | Code | Label |
  |---|---|
  | 01 | prepaid or matured |
  | 02 | third-party sale |
  | 03 | short sale |
  | 06 | repurchased |
  | 09 | deed-in-lieu or REO (the lender took the property back) |
  | 15 | non-performing note sale |
  | 16 | reperforming note sale |
  | 96 | removal (non-credit) |

  A blank is allowed. Any other code fails check 7.
- **Modification Flag.** Only Y, N or blank. It does not always stay Y once set
  (section 10.5).
- **Values that cannot be read.** An unreadable number or date is left blank and counted.
  Numbers use DuckDB's TRY_CAST; months use DuckDB's try_strptime with the month-year
  format. Any count above zero in a loaded field fails check 6, so no value is lost without
  notice.
- **Current UPB.** Stored as given. 2005Q1 has no blank balances at any loan age. Other
  quarters are covered by the fill rates in the EDA. Filling in blank early balances, if
  any, is left to the first module that needs it.

## 10. Measured numbers

### 10.1 Conversion speed and compression (stage 1)

From the overnight run log, for quarters converted up to 2021Q2. Time covers the whole
quarter: unpacking, converting and checking. Compression is raw text size divided by
Parquet size.

| Quarter | Raw text | Time | Seconds per raw GB | Compression |
|---|---|---|---|---|
| 2003Q3 | 37.71 GB | 24m 06s | 38.3 | 40.8x |
| 2005Q3 | 8.96 GB | 6m 35s | 44.1 | 40.0x |
| 2008Q4 | 3.73 GB | 3m 10s | 50.9 | 36.2x |
| 2012Q4 | 17.22 GB | 13m 06s | 45.6 | 37.6x |
| 2019Q1 | 3.21 GB | 2m 41s | 50.2 | 30.5x |
| 2020Q3 | 21.02 GB | 14m 11s | 40.5 | 32.5x |
| 2021Q1 | 21.82 GB | 14m 33s | 40.0 | 33.5x |

- 2003Q3 to 2018Q4: 38 to 53 seconds per raw GB, most quarters near 48. Compression 31x to
  41x.
- 2019Q1 to 2021Q2: 40 to 51 seconds per raw GB. Compression 29.5x to 33.5x.
- 2005Q1 and 2005Q2, converted earlier: about 3m 37s per quarter at 39x.
- All 104 quarters (from the conversion records): 88 quarters carry times, totalling 2.42
  hours unpacking and 6.60 hours converting. The other 16 were converted before records
  existed. Their records were added later from the zip, so they have no conversion times.

### 10.2 Base build time (stage 2)

| Quarter | Raw text | Time |
|---|---|---|
| 2005Q1 | 6.60 GB | 48 s (44 s on the latest test run) |
| 2019Q1 | 3.21 GB | 30 s |

### 10.3 Known answers

Two quarters were built into a test database before the full load:
- **2005Q1:** the known numbers come from the first test load on 2026-11-14, made with the
  earlier single-step loader. The two-stage load gives exactly the same numbers.
- **2019Q1:** the known numbers come from the test build on 2026-11-15. It is the first
  tested quarter with restated balances (R), and they reconcile to the cent.

Both quarters pass all 8 checks. The full load (section 11) matched these numbers again.

| | 2005Q1 | 2019Q1 |
|---|---|---|
| Monthly rows | 24,701,544 | 11,583,612 |
| Loans | 303,611 | 341,865 |
| Original UPB, first month (A) | 49,416,049,000.00 | 82,057,280,000.00 |
| Restated change (R) | 0.00 | -203,000.00 (6 loans) |
| Blank first month (B) | 0.00 | 0.00 |
| Original UPB in `loans_table` | 49,416,049,000.00 | 82,057,077,000.00 |
| Development subset | 30,361 | 34,187 |
| Checks | 8 of 8 PASS | 8 of 8 PASS |

### 10.4 Restated origination fields, 2005Q1

Loans in 2005Q1 with two or more different non-blank values for a field during the loan's
life:

| Field | Loans |
|---|---|
| seller_name | 13,215 |
| msa | 6,578 |
| orig_ltv | 729 |
| mi_pct | 659 |
| orig_date | 178 |
| zip3 | 78 |
| num_borrowers | 6 |
| property_state | 4 |
| first_payment_date | 3 |
| mi_type | 1 |

### 10.5 What the data showed (2005Q1)

- Modification Flag: 10,549 loans show Y at some point. 59 of them show N after a Y.
- Delinquency status "XX" (not known): 1.14% of rows.
- Current UPB: no blank values at any loan age.

## 11. The full load (all 104 quarters, 2026-11-15)

Every quarter passed its 8 checks. After the load, 11 further checks were run on the whole
database, and all passed:

1. 104 quarters loaded, none twice.
2. Every Parquet file has a conversion record and is loaded.
3. Loans in `loans_table` equal the total in `loaded_quarters_table`, with no loan twice.
4. Original UPB in `loans_table` equals the total in `loaded_quarters_table`.
5. Parquet rows equal raw lines, over all quarters.
6. The development subset is 10% of each quarter, and every subset loan is in
   `loans_table`.
7. 2005Q1 matches its known numbers (section 10.3).
8. 2019Q1 matches its known numbers.
9. `data_log.md` has an entry for every quarter.
10. Rows read through `loan_monthly_view` equal the Parquet rows.
11. Every monthly row joins to a loan in `loans_table`.

| Item | Value |
|---|---|
| Quarters | 104 (2000Q1 to 2025Q4), each 8 of 8 checks PASS |
| Monthly rows | 3,314,483,004 (equal to the raw lines) |
| Loans | 57,597,528 |
| Original UPB in `loans_table` | 12,629,831,311,000.00 |
| Restated original UPB (R), all quarters | -2,723,000.00; blank first month (B): 0.00 |
| Development subset | 5,759,759 loans: 10% of each quarter, rounded per quarter, so slightly above 10% of the total (5,759,752.8) |
| Raw text | 934.92 GB |
| Total Parquet size | 26.04 GB (35.9 times smaller) |
| `loans_table` size | about 2.04 GB |
| `mortgages.duckdb` size | 2.22 GB |
| Base build time | 4.74 hours (sum of the quarter load times) |
| Query time on `loan_monthly_view`: rows by month | 183 seconds |
| Query time on `loan_monthly_view`: delinquency spread | 182 seconds |
| Query time on `loan_monthly_view`: join to `loans_table` | 276 seconds |

A full pass over the monthly history takes 3 to 5 minutes, because every value is stored as
text and converted as it is read. That is workable for Module 1. If later modules need many
full passes, a copy of the Parquet files with numbers and dates already converted is the next
step to consider.

**Load log.** `data_log.md` is written only when the default database is loaded. If writing
it fails, the quarter just saved stays loaded, but the run stops. Rerunning the same command
carries on from the next quarter.

## 12. Short forms

| Short form | Meaning |
|---|---|
| UPB | Unpaid principal balance: the amount of the loan still owed. Original UPB is the amount lent. |
| LTV | Loan-to-value: loan amount as a percentage of the property value |
| CLTV | Combined LTV: all loans on the property together |
| DTI | Debt-to-income: the borrower's monthly debt payments as a percentage of monthly income |
| MSA | Metropolitan statistical area: the city region the property is in |
| zip3 | First 3 digits of the property's postcode (ZIP code) |
| MI | Mortgage insurance (mi_pct: the share covered; mi_type: who pays it) |
| REO | Real estate owned: the lender has taken the property back |
| DPD | Days past due |
| PD | Probability of default |
| LGD | Loss given default |
| ECL | Expected credit loss |
| NA | Not applicable |
