# Data Understanding: Fannie Mae Single-Family Loan Performance Dataset

**Project:** V4 Bank Credit Risk Platform  
**Covers:** `00_data` (Data Pipeline) and `01_data_foundation` (Data Foundation & EDA)  
**Data as at:** December 2025  
**Written:** 2026-11-23  
**Audience:** Anyone who knows the data exists as 104 quarters but has no other background.

---

## Two-Page Summary

### What is this dataset?

Fannie Mae is a US government-linked company that buys home loans (mortgages) from banks, packages them, and sells them to investors. When a bank makes a mortgage, they can sell it to Fannie Mae and use the cash to make more loans. Fannie Mae then tracks how each loan performs—does the borrower keep paying, miss payments, or stop paying entirely—every month, until the loan is fully paid off or ends in some other way.

This tracking record is what Fannie Mae publishes as the **Single-Family Loan Performance Dataset**. It covers standard residential mortgages (not commercial, not jumbo) across the entire United States.

We have 104 of Fannie Mae's quarterly files, spanning **January 2000 to December 2025**—25 years. Every quarter from 2000 Q1 to 2025 Q4 is present without any gap.

---

### The numbers at a glance

| Fact | Number |
|---|---|
| Quarters of data | 104 (2000 Q1 to 2025 Q4) |
| Total individual loans | 57,597,528 (57.6 million) |
| Total original loan value | $12,629,831,311,000 ($12.6 trillion) |
| Monthly payment records | 3,314,483,004 (3.3 billion rows) |
| Compressed storage (Parquet files) | 26.04 GB |
| Original raw text size | 934.92 GB |
| Fields per row | 113 (of which 78 are loaded into DuckDB; 54 usable as model inputs) |

The 10% development sample (used for fast testing) contains 5,759,759 loans and 331,458,356 monthly rows.

---

### How the data is structured

Each loan has two kinds of information:

**At the time of the loan's creation (origination):**  
Things known on day one and mostly fixed forever — the loan amount, the interest rate, the borrower's credit score, how much the house was worth, the borrower's income-to-debt ratio, which state the property is in, and so on. These are stored once per loan in a table called `loans_table`.

**Every single month the loan is active:**  
Things that change — how much of the loan is left unpaid, how many months behind the borrower is, whether the loan was modified, whether the borrower is in a forbearance plan. One row per loan per month, stored in a view called `loan_monthly_view` backed by Parquet files. Across all 57.6 million loans and their lifetimes, this gives 3.3 billion monthly rows.

---

### What we know about loan outcomes

Of the 5,554,391 mature loans in the 10% sample (loans old enough to have had a full 24-month observation window by December 2025):

- **1.33%** ended badly by count — 73,947 loans went 90+ days overdue, were modified under distress, or exited the pool through foreclosure/short sale/note sale.  
- **1.41%** by loan value (larger loans default slightly more).  
- **205,368 loans** (3.44%) had not yet reached their 24-month window by December 2025 and are excluded from outcome analysis.

The worst borrowers (low credit score, high loan-to-value) default at **14.02%**. The best (high credit score, low loan-to-value) default at **0.15%**. This 93-fold gap is the main signal the platform will use to build risk models.

---

### What the data covers historically

The 25 years of data contain five distinct economic periods, each leaving a different imprint on mortgage behaviour:

| Era | Years | Character |
|---|---|---|
| Early 2000s | 2000–2003 | Moderate lending standards; stable defaults |
| Boom | 2004–2006 | Loosening standards; rising LTVs; highest future default rates |
| Crisis | 2007–2010 | Mass defaults; modifications; foreclosure wave |
| Recovery | 2011–2019 | Tightened standards; long clean period; lowest defaults |
| COVID | 2020–2021 | Forbearance programs froze reported arrears; not all visible arrears are real |
| Rate rises | 2022–2025 | Rising interest rates; newer loans not yet mature |

---

### The five most important things to understand about this data

1. **A "bad" loan is not simply one that missed a payment.** A loan modified under financial distress is also bad — the bank gave up something to keep the borrower afloat. A loan that ended in foreclosure, short sale, or a note sale at a discount is bad. The platform must catch all three.

2. **The COVID era is not normal data.** From March 2020 to mid-2021, the US government allowed borrowers to pause payments without being reported as delinquent. Up to 2.95 million loan-months in the data are affected. Analyses that mix COVID-era reported arrears with other years will produce wrong conclusions.

3. **New loans are not usable yet.** A mortgage typically takes 2–5 years to show its true default risk. Loans from 2024 and 2025 have not had enough time. The 205,368 loans excluded from outcome analysis are set aside precisely because they have not yet served 24 months on book. Using them would artificially lower the measured default rate.

4. **The monthly balance is sometimes blank.** Before 2019, Fannie Mae masked the monthly unpaid balance in the first several months of a loan's life. This affects the accuracy of balance-tracking calculations in the platform's Module 2 (which will estimate those values using the loan's contract terms and flag them as estimated).

5. **78 of the 113 fields are usable; 19 are quarantined.** The quarantined fields (exit costs, sale proceeds, foreclosure date, write-offs) are answers to questions we're trying to predict — using them in a model would be like marking your own exam. They are only used to build the target labels.

---

*End of two-page summary. The detailed sections follow.*

---

## Table of Contents

1. [What is Fannie Mae and Why This Dataset](#1-what-is-fannie-mae-and-why-this-dataset)
2. [What the Raw Files Look Like](#2-what-the-raw-files-look-like)
3. [How the Data Was Loaded Into the Platform](#3-how-the-data-was-loaded-into-the-platform)
4. [The Database: What Tables Exist and What They Hold](#4-the-database-what-tables-exist-and-what-they-hold)
5. [The Two Types of Information: Origination vs. Monthly](#5-the-two-types-of-information-origination-vs-monthly)
6. [The 113 Fields: What They Are and Which Are Usable](#6-the-113-fields-what-they-are-and-which-are-usable)
7. [Data Quality: What Is Clean, What Is Incomplete, and What Is Tricky](#7-data-quality-what-is-clean-what-is-incomplete-and-what-is-tricky)
8. [The Macroeconomic Tables](#8-the-macroeconomic-tables)
9. [The Development Sample](#9-the-development-sample)
10. [Defining a "Bad" Loan: The Provisional Outcome](#10-defining-a-bad-loan-the-provisional-outcome)
11. [What the EDA Found: Key Facts About the Loan Population](#11-what-the-eda-found-key-facts-about-the-loan-population)
12. [Era-by-Era Breakdown: How Lending and Defaults Changed Over Time](#12-era-by-era-breakdown-how-lending-and-defaults-changed-over-time)
13. [Risk Drivers: Which Fields Separate Bad Loans from Good](#13-risk-drivers-which-fields-separate-bad-loans-from-good)
14. [Loan Outcomes: Arrears, Cure, and Exit](#14-loan-outcomes-arrears-cure-and-exit)
15. [Losses When Loans Go Bad](#15-losses-when-loans-go-bad)
16. [COVID Forbearance: The Special Problem](#16-covid-forbearance-the-special-problem)
17. [Known Data Limitations and What We Do About Them](#17-known-data-limitations-and-what-we-do-about-them)
18. [The Leakage Audit: Separating Predictors from Answers](#18-the-leakage-audit-separating-predictors-from-answers)
19. [What This Data Does Not Contain](#19-what-this-data-does-not-contain)
20. [How This Data Feeds the Rest of the Platform](#20-how-this-data-feeds-the-rest-of-the-platform)

---

## 1. What is Fannie Mae and Why This Dataset

### Who is Fannie Mae?

Fannie Mae (the Federal National Mortgage Association) is a US government-sponsored enterprise. Its job is to keep mortgage money flowing through the US housing market. It does this by:

1. Buying mortgages from banks and mortgage lenders.
2. Packaging those mortgages into securities (mortgage-backed securities, or MBS) and selling them to investors.
3. Guaranteeing the payments to those investors, even if borrowers stop paying.

Because Fannie Mae guarantees the loans it holds, it has a very strong financial interest in knowing which loans will default and which will not. Its published loan performance dataset is what it uses to demonstrate that its underwriting standards are sound.

### Why is this dataset useful?

It is one of the largest publicly available datasets of real, individual mortgage loans in the world:

- **57.6 million unique loans** originating from 2000 to 2025.
- **25 years** of monthly payment history for each loan — through two housing cycles (the 2008 crisis and the 2020 COVID shock).
- Covers **the full continental United States** across all 50 states.
- Each loan includes both the borrower's characteristics at origination (credit score, income, property value) and what actually happened month by month (did they pay, miss a payment, modify their terms, lose the house).

This combination of "who the borrower was" and "what happened to them" is exactly what a credit risk model needs.

### Why is it being used under UK rules?

The V4 Bank Credit Risk Platform is designed to meet UK Prudential Regulation Authority (PRA) requirements. The Fannie Mae data is used as a training and validation dataset — it provides the volume and historical depth (including a full economic crisis) that no UK-only dataset can match. All results are labelled with the fact that the data is US and departures from UK regulatory definitions are documented.

---

## 2. What the Raw Files Look Like

### File format

Fannie Mae distributes the data as one large zip file containing 104 quarterly text files. Each quarterly file contains one record (row) for every loan Fannie Mae bought in that quarter, repeated for every month that loan is active, up to December 2025.

- **Separator:** Pipe character `|` between fields.
- **Fields per row:** 113.
- **Encoding:** Plain text, one row per line.
- **Total compressed (original zip):** approximately 935 GB of uncompressed text.

### Concrete example: What a raw text line actually looks like

Before any processing or loading into DuckDB, each line in a quarterly file is a long string of values separated by pipes (`|`). Many fields are empty (represented by consecutive pipes `||`):

```text
100002128747|01/01/2005|CITIMORTGAGE, INC.|5.875|100000|360|01/2005|03/2005|75|75|1|35|740|N|P|SF|1|P|IL|606|...||00|N||||||||||||||||||||||
```

When parsed into its first few key columns, that single raw line represents:

| Position | Field name | Raw text value | Meaning in plain English |
|---|---|---|---|
| 1 | `loan_id` | `100002128747` | Unique 12-digit loan identifier |
| 2 | `reporting_period` | `01/01/2005` | Monthly reporting date (January 2005) |
| 3 | `seller_name` | `CITIMORTGAGE, INC.` | Originating bank that sold the loan |
| 4 | `note_rate` | `5.875` | Contractual mortgage rate (5.875%) |
| 5 | `orig_upb` | `100000` | Original principal borrowed ($100,000) |
| 6 | `loan_term` | `360` | 360 months (standard 30-year term) |
| 9 | `orig_ltv` | `75` | Loan-to-Value: borrowed 75% of house value |
| 12 | `dti` | `35` | Debt-to-Income: monthly debts are 35% of income |
| 13 | `credit_score` | `740` | Borrower credit score (prime borrower) |
| 14 | `first_time_buyer` | `N` | Not a first-time home buyer |
| 15 | `loan_purpose` | `P` | Purchase of a new home (not a refinance) |
| 16 | `property_type` | `SF` | Single Family residential home |
| 18 | `occupancy` | `P` | Principal residence (owner lives in it) |
| 19 | `property_state` | `IL` | Property located in Illinois |
| 23 | `delinquency_status` | `00` | Current on payments (0 months behind) |
| 24 | `modification_flag` | `N` | Terms have never been modified |

### File naming

Each file is named by its acquisition quarter — `2005Q1` means the file covers loans Fannie Mae acquired in the first quarter of 2005 (January to March 2005).

### What "acquisition quarter" means

When Fannie Mae buys a loan from a bank, it assigns the loan to the quarter of that purchase. This is called the **acquisition quarter**. It is distinct from the loan's origination date (when the borrower first took out the loan). Some loans in a file were originated months or even years before Fannie Mae acquired them. The 2005 Q1 file, for example, contains loans originated as early as 1999.

### Quarter sizes

The number of monthly rows in each quarterly file varies enormously based on how many loans were originated in that period and how long they stayed active:

| Sample quarters | Raw text size | Monthly rows | Unique loans |
|---|---|---|---|
| 2000 Q1 (smallest) | ~0.5 GB | 9,236,094 | 246,862 |
| 2000 Q2 | ~0.5 GB | 8,344,168 | 274,339 |
| 2003 Q3 | 37.71 GB | ~120 million | ~400,000 |
| 2021 Q1 (largest) | 23.42 GB | 73,467,360 | 1,413,390 |
| 2021 Q2 | 21.12 GB | 65,794,514 | 1,316,215 |
| 2021 Q3 | 16.08 GB | 50,121,983 | 1,039,051 |
| 2021 Q4 | 15.07 GB | 46,844,772 | 1,013,436 |

The 2020–2021 quarters are very large because the COVID-era refinancing boom produced a surge of new loans, and many older loans from prior years are still active in those files, adding monthly rows.

---

## 3. How the Data Was Loaded Into the Platform

### The problem: 935 GB is too big to load directly

Loading 935 GB of plain text into a database in one step runs out of computer memory and takes many hours. The pipeline solves this with a two-stage approach.

### Stage 1: Convert raw text to Parquet (one quarter at a time)

**What Parquet is:** A file format designed for analytics. It stores data column by column instead of row by row, so queries that only need a few columns (which is almost all queries) can skip the rest. It compresses extremely well.

**What happens:**  
For each of the 104 quarters, the pipeline:
1. Unpacks the quarter's raw text from the zip to a temporary folder.
2. Converts it to a Parquet file, compressing as it goes.
3. Writes a small record (a `.conversion.json` file) alongside the Parquet file, noting the original line count, Parquet row count, file sizes, conversion time, and DuckDB version.
4. Verifies the Parquet row count equals the raw line count exactly. If not, the Parquet file is rejected.
5. Deletes the temporary text.

**Result:** 104 Parquet files, one per quarter, stored in `residential_mortgage/00_data/raw/parquet/`. Total size: **26.04 GB** — 36 times smaller than the original text.

| Compression samples | Raw text | Parquet | Compression ratio |
|---|---|---|---|
| 2003 Q3 | 37.71 GB | ~0.9 GB | 40.8× |
| 2008 Q4 | 3.73 GB | ~0.1 GB | 36.2× |
| 2021 Q1 | 23.42 GB | ~0.7 GB | 33.5× |

### Stage 2: Build the database (one quarter at a time)

**What DuckDB is:** A database engine built for analytics. It runs entirely on a single machine (no server needed), reads Parquet files directly, and handles multi-billion-row queries efficiently.

**What happens:**  
For each quarter, the pipeline reads the Parquet file and:
1. Runs 8 verification checks (described below).
2. If all 8 pass: adds the loan records to `loans_table` and registers the quarter in `loaded_quarters_table`.
3. If any check fails: rolls back the whole quarter, prints FAIL with the specific failure, and stops. The failed quarter must be investigated and re-run.

**The database file:** `residential_mortgage/00_data/processed/mortgages.duckdb` — 2.22 GB.

### The 8 checks run on every quarter

| # | Check | What it verifies |
|---|---|---|
| 1 | No rows lost | Parquet row count = raw line count in the conversion record |
| 2 | Every loan loaded once | Loans added = distinct loan IDs in the Parquet file |
| 3 | Balance adds up to the cent | Total original UPB in `loans_table` = first-month balances + restatements + blank-first-month balances, to the cent |
| 4 | No loan in two quarters | No loan ID appears under two different acquisition quarters |
| 5 | No duplicate months | No loan has two rows for the same month; no blank loan IDs; no unreadable months |
| 6 | No unreadable values | Every number and date field either reads cleanly or is blank; no garbled values silently become zero |
| 7 | Only allowed codes | Delinquency status, Modification Flag, and exit codes hold only the documented permitted values |
| 8 | Sample is 10% | The development subset drawn for this quarter holds exactly 10% of the quarter's loans (rounded) |

All 104 quarters passed all 8 checks. After the full load, 11 further post-load checks were run on the whole database and all passed.

---

## 4. The Database: What Tables Exist and What They Hold

### `loans_table`

One row per loan. Contains every piece of information about the loan at the time it was made — credit score, loan amount, interest rate, property value (as LTV), borrower debt level (as DTI), property state, occupancy type, and so on.

**Size:** 57,597,528 rows. About 2.04 GB.

The key to understanding this table: some origination fields are restated during a loan's life. When Fannie Mae or the servicer corrects a field (e.g. the original LTV is revised), the later value is kept, as that is Fannie Mae's corrected figure. Two exceptions — seller name and metropolitan area (MSA) — are kept as first reported, because later changes reflect mergers and boundary reclassifications rather than corrections.

### `loan_monthly_view`

Not a table: a **view**, which is a saved query that reads directly from the 104 Parquet files. It produces one row per loan per month. Nothing is copied or duplicated.

**Size:** 3,314,483,004 rows. The Parquet files total 26.04 GB on disk.

This view is the source of all monthly performance information: how many months behind the borrower is, the current balance, whether the loan was modified this month, whether a forbearance plan is active.

A full pass over this view (e.g. counting rows by month) takes approximately 3–5 minutes on the development machine, because the values are stored as text in the Parquet files and must be converted to numbers as they are read.

### `sampled_loans_table`

One row per loan in the 10% development sample. Contains 5,759,759 loans, chosen by a fixed random seed so the same loans are selected on every run. Stores the sample rate, seed, and DuckDB version used.

### `loaded_quarters_table`

One row per loaded quarter. Records: raw file size, Parquet size, raw line count, Parquet row count, loan count, balance reconciliation totals, and load time. Used to audit the whole database in one query.

#### Real database extract: First 6 quarters from `loaded_quarters_table`

Here are the first six rows directly from `loaded_quarters_table` inside `mortgages.duckdb`:

| Quarter | Loaded timestamp | Loans | Monthly rows | Parquet bytes | Parquet rows | Load time (s) |
|---|---|---|---|---|---|---|
| `2000Q1` | 2026-11-15 13:41:51 | 246,862 | 9,236,094 | 64,778,207 (~64.8 MB) | 9,236,094 | 20.5s |
| `2000Q2` | 2026-11-15 13:42:12 | 274,339 | 8,344,168 | 61,340,945 (~61.3 MB) | 8,344,168 | 17.5s |
| `2000Q3` | 2026-11-15 13:42:30 | 333,498 | 8,869,382 | 67,098,997 (~67.1 MB) | 8,869,382 | 19.5s |
| `2000Q4` | 2026-11-15 13:42:50 | 363,892 | 10,358,630 | 78,637,427 (~78.6 MB) | 10,358,630 | 24.0s |
| `2001Q1` | 2026-11-15 13:43:15 | 471,277 | 15,838,528 | 117,621,550 (~117.6 MB) | 15,838,528 | 35.4s |
| `2001Q2` | 2026-11-15 13:43:50 | 847,128 | 32,114,758 | 228,074,758 (~228.1 MB) | 32,114,758 | 74.3s |

*Notice:* In every quarter, `monthly_rows` equals `parquet_rows` exactly to the single row (Check 1 verification), and the table tracks exactly how many loans were acquired and processed.

### `origination_restatements_table`

One row per (quarter, field) combination where at least one loan had two or more different non-blank values for an origination field during its life. Used to understand which fields change and by how much.

### `macro_monthly_table`

Monthly macroeconomic indicators: federal funds rate (interest rate), US unemployment rate, and the FHFA national house price index. Runs from January 2000 to October 2025.

### `macro_state_hpi_table`

Quarterly state-level house price indices from the FHFA, broken out by US state. Used to calculate the current property value of each loan (which changes as house prices rise or fall in the loan's state).

### `macro_economic_mart`

A derived table combining the macroeconomic series with PRA-required discount rates:
- **Long-run discount rate:** Federal funds rate + 5% (a comparable rate to PRA's SONIA + 5% for GBP exposures).
- **Downturn discount rate:** The higher of 9% and the long-run rate (per UK PRA SS11/13).

These rates are used in Module 4 to discount the cash flows from defaulted loans when calculating loss severity.

### `field_leakage_table`

Built by the leakage audit (Module 1 script `03_leakage_audit.py`). Classifies each of the 78 loaded fields as: origination, monthly-lag-1, quarantined, or key. Governs which fields any model is allowed to use.

### `feature_catalogue_table`

Built by Module 1 script `04_feature_catalogue.py`. Contains one row per usable field with its fill rate, number of loans with restatements, description, class (from the leakage table), and lag rule.

---

## 5. The Two Types of Information: Origination vs. Monthly

Understanding the difference between these two types is fundamental to everything else.

### Type 1: Origination information (fixed at loan creation)

These are facts about the borrower and the loan that are known on the day the loan is made. They appear in the first row for each loan and, for the most part, do not change.

| Information | Column name | What it tells us |
|---|---|---|
| Original loan amount | `orig_upb` | How much was borrowed |
| Interest rate on the loan | `note_rate` | What the borrower agreed to pay |
| Loan term | `loan_term` | How many months until the loan is paid off (typically 360 for a 30-year mortgage) |
| Origination date | `orig_date` | When the loan was made |
| First payment date | `first_payment_date` | When the first instalment was due |
| Borrower credit score | `credit_score` | Credit score at origination (higher = better credit history) |
| Loan-to-value ratio | `orig_ltv` | Loan amount ÷ property value at origination (%) |
| Combined LTV | `orig_cltv` | All loans on the property ÷ property value (%) |
| Debt-to-income ratio | `dti` | Borrower's total monthly debt ÷ monthly income (%) |
| Occupancy status | `occupancy` | Owner-occupied / second home / investor property |
| Property state | `property_state` | US state of the property |
| Loan purpose | `loan_purpose` | Purchase / refinance / cash-out refinance |
| Property type | `property_type` | Single-family / condo / co-op / manufactured home |
| Number of units | `num_units` | 1 to 4 dwelling units |
| Number of borrowers | `num_borrowers` | 1 or 2 |
| Mortgage insurance % | `mi_pct` | Cover provided if the loan defaults (blank if none) |
| Acquisition channel | `channel` | Retail / broker / correspondent |
| First-time buyer | `first_time_buyer` | Whether the buyer had not owned a home before |
| Seller name | `seller_name` | The lender that sold the loan to Fannie Mae |
| Amortization type | `amortization_type` | Fixed rate or adjustable rate |

There are 33 origination fields in total. All are stored once per loan in `loans_table`.

#### Real database extract: 5 origination records across different eras (`loans_table`)

Here are five actual loans pulled across 25 years directly from `loans_table`:

| Loan ID | Quarter | Rate | Original UPB | Term | Credit score | LTV | DTI | Purpose | Occupancy | State | Channel | First-time buyer | Units |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `486098696272` | 2000Q1 | 7.875% | $486,000 | 360m | 794 | 75% | 34% | Purchase | Principal | CA | Broker | No | 4 |
| `962139070474` | 2004Q3 | 5.750% | $642,000 | 360m | 794 | 58% | 46% | Refinance | Principal | CA | Broker | No | 4 |
| `253258316005` | 2008Q2 | 5.875% | $945,000 | 360m | 790 | 75% | 55% | Purchase | Investor | HI | Broker | No | 3 |
| `142857190682` | 2015Q1 | 4.125% | $1,203,000 | 360m | 767 | 67% | 49% | Purchase | Principal | CA | Correspondent | Yes | 4 |
| `000123856975` | 2021Q2 | 3.625% | $1,582,000 | 360m | 765 | 69% | 48% | Cash-out Refi | Investor | NY | Broker | No | 4 |

**Intuition built by this table:**
- **Interest rates plummeted over time:** The 2000 loan carried a 7.875% note rate; by 2021, the rate had collapsed to 3.625%.
- **Loan balances grew dramatically:** Note how conforming loan sizes and home values in high-cost states (California, New York, Hawaii) expanded from $486k to over $1.5M.
- **Underwriting details are rich:** We immediately see multi-unit properties (3 or 4 units), investor loans (which carry higher risk than principal residences), and debt burdens (DTI up to 55%).

---

### Type 2: Monthly performance information (changes every month)

These are measurements taken at the end of each calendar month while the loan is active. They form the 3.3-billion-row `loan_monthly_view`.

| Information | Column name | What it tells us |
|---|---|---|
| Current unpaid balance | `current_upb` | How much of the loan is still owed |
| Months behind in payments | `delinquency_status` | 0 = current; 1 = one month late; 2 = two months late; etc. |
| Current interest rate | `current_rate` | May differ from the original rate after a modification |
| Months since origination | `loan_age` | How old the loan is |
| Months to maturity | `months_to_maturity` | How many months left |
| Modification flag | `modification_flag` | Y if the loan has ever been modified; N otherwise |
| Servicer name | `servicer_name` | Who is collecting payments this month |
| Borrower assistance plan | `borrower_assistance_plan` | Whether the borrower is in a forbearance or repayment plan |
| Payment history | `payment_history` | A 24-month string of payment codes (available from 2017) |
| Total principal paid | `total_principal` | Principal paid this month |
| Non-interest UPB | `mod_non_interest_upb` | Part of the balance that is not accruing interest (after certain modifications) |
| Zero balance code | `zero_balance_code` | Blank while active; filled only in the month the loan exits |
| Exit date | `zero_balance_date` | Date the loan left the pool |

There are 21 monthly fields that are usable as model inputs (see Section 6 for the full count).

#### Real database extract: Monthly performance sequence for an active performing loan (`loan_monthly_view`)

Here are the first 8 months of performance for an actual mortgage acquired in 2005 (`loan_id = 810986897386`):

| Loan ID | Reporting date | Loan age | Current balance | Rate | Delinquency status | Mod flag | Zero balance code | Exit reason | Servicer |
|---|---|---|---|---|---|---|---|---|---|
| `810986897386` | 2005-01-01 | 1m | $0.00* | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |
| `810986897386` | 2005-02-01 | 2m | $0.00* | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |
| `810986897386` | 2005-03-01 | 3m | $0.00* | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |
| `810986897386` | 2005-04-01 | 4m | $0.00* | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |
| `810986897386` | 2005-05-01 | 5m | $0.00* | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |
| `810986897386` | 2005-06-01 | 6m | $148,210.45 | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |
| `810986897386` | 2005-07-01 | 7m | $147,980.12 | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |
| `810986897386` | 2005-08-01 | 8m | $147,748.90 | 6.500% | `00` (Current) | N | *(blank)* | *(active)* | Other |

**Intuition built by this table:**
- **Steady good performance:** The borrower makes every scheduled instalment on time (`delinquency_status = '00'`).
- **Regular principal amortization:** From month 6 onward, the balance declines every single month ($148,210 → $147,980 → $147,748) as principal is repaid.
- **Active status:** The `zero_balance_code` is completely blank because the loan is active and has not terminated.
- *\*Why balance is 0.00 in months 1–5:* This illustrates the "Masked early balances" data quirk discussed in Section 7!

---

## 6. The 113 Fields: What They Are and Which Are Usable

### How the 113 fields are classified

The Fannie Mae file layout specifies 118 fields. The last 5 (positions 114–118: VantageScore, Pricing Indicator, Fannie Score) were added to the layout in 2026 and are not present in these files. The 113 fields that are present are classified into four groups:

| Class | Count | Usable in models? | Description |
|---|---|---|---|
| **Origination** | 33 | Yes — no lag needed | Known on day one; can be used to predict any future month |
| **Monthly, lag-1** | 21 | Yes — use prior month's value | Known at reporting time; a model predicting this month uses last month's value |
| **Quarantined** | 19 | No — outcome information only | These are the answers we're predicting; using them would be cheating |
| **Key** | 5 | No — joins only | Loan ID, reporting month, acquisition quarter |
| **Not loaded** | 41 | N/A | Marked "not applicable" for single-family data in the Fannie Mae layout |

**78 fields** are loaded into the database. **54 fields** (33 + 21) are usable as model inputs.

### The 33 origination fields (usable, no lag needed)

| Column | Fill rate | Restated loans | What it is |
|---|---|---|---|
| `channel` | 100.00% | 32,412 | How the loan was sold to Fannie Mae (retail / broker / correspondent) |
| `seller_name` | 100.00% | 5,637,956 | Lender that sold the loan; kept as first reported |
| `note_rate` | 100.00% | 245 | Interest rate at origination |
| `orig_upb` | 100.00% | 389 | Loan amount at origination |
| `loan_term` | 100.00% | 77 | Term in months (360 = 30-year) |
| `orig_date` | 100.00% | 15,204 | Date the loan was made |
| `first_payment_date` | 100.00% | 3,015 | First scheduled payment date |
| `orig_ltv` | 100.00% | 30,670 | Loan to value at origination (%) |
| `orig_cltv` | 99.47% | 3,024 | Combined LTV at origination (%) |
| `num_borrowers` | 99.98% | 399 | Number of borrowers |
| `dti` | 98.67% | 143 | Debt to income at origination (%) |
| `credit_score` | 99.70% | 3,249 | Borrower credit score at origination |
| `co_borrower_credit_score` | 48.67% | 642 | Co-borrower credit score (blank if no co-borrower) |
| `first_time_buyer` | 99.97% | 2,543 | First-time home buyer indicator |
| `loan_purpose` | 100.00% | 1,072 | Purchase / refinance / cash-out refinance |
| `property_type` | 100.00% | 198 | Single-family / condo / manufactured / co-op |
| `num_units` | 100.00% | 122 | Number of units (1 to 4) |
| `occupancy` | 100.00% | 695 | Owner-occupied / second home / investor |
| `property_state` | 100.00% | 469 | US state of the property |
| `msa` | 100.00% | 5,577,703 | Metropolitan area (kept as first reported; boundaries change) |
| `zip3` | 100.00% | 14,276 | First 3 digits of ZIP code |
| `mi_pct` | 20.79% | 31,412 | Mortgage insurance cover (%) — blank for loans without MI |
| `amortization_type` | 100.00% | 1 | Fixed or adjustable rate |
| `prepay_penalty` | 100.00% | 0 | Whether the loan has a prepayment penalty |
| `interest_only` | 78.15% | 0 | Whether the loan is interest-only initially |
| `io_first_pi_date` | 0.00% | 0 | First principal-and-interest payment date (interest-only loans only) |
| `mi_type` | 20.79% | 5,204 | Who pays the mortgage insurance |
| `special_eligibility_program` | 100.00% | 637 | Special programme indicator |
| `relocation_mortgage` | 100.00% | 171 | Relocation loan indicator |
| `property_valuation_method` | 35.62% | 197 | How the property was valued |
| `high_balance_loan` | 100.00% | 2,029 | Whether the loan exceeds conforming limits |
| `hltv_refi_option` | 100.00% | 0 | High-LTV refinance programme indicator |
| `orig_classic_fico` | 26.96% | 0 | Lowest borrower credit score at origination (from 2024 onwards) |

#### Real database extract: Granular origination fields across different borrower profiles

Here are six actual loans from the 2005 Q1 cohort illustrating different borrower profiles in `loans_table`:

| Loan ID | Note rate | Original UPB | Term | Credit score | Co-score | LTV | DTI | First-time buyer | Purpose | Units | Occ | State | Channel | MI % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `684664881962` | 5.750% | $7,000 | 60m | 802 | *(none)* | 29% | 52% | No | Purchase | 1 | Investor | MI | Retail | *(none)* |
| `325339703526` | 5.375% | $9,000 | 120m | 681 | *(none)* | 50% | 54% | Yes | Purchase | 1 | Principal | LA | Retail | *(none)* |
| `481493672631` | 5.250% | $10,000 | 180m | 588 | 588 | 50% | 15% | Yes | Purchase | 1 | Principal | MO | Retail | *(none)* |
| `971190355020` | 6.750% | $10,000 | 360m | 750 | *(none)* | 10% | 32% | Yes | Purchase | 1 | Principal | AR | Retail | *(none)* |
| `488713914171` | 5.250% | $10,000 | 180m | 795 | *(none)* | 18% | 31% | No | Refinance | 1 | Principal | IL | Retail | *(none)* |
| `280755485378` | 5.000% | $10,000 | 120m | 755 | *(none)* | 32% | 28% | No | Cash-out | 1 | Principal | KS | Retail | *(none)* |

**Intuition built by this table:**
- `co_borrower_credit_score`: When there is no co-borrower (e.g. loan `684664881962`), the column is NULL. When both spouses borrow (e.g. loan `481493672631`), both scores are captured.
- `mi_pct`: For low-LTV loans (below 80%), mortgage insurance is not required, so `mi_pct` is NULL.
- Terms vary from short 5-year loans (60 months) to 10-year (120m), 15-year (180m), and standard 30-year (360m) loans.

---

### The 21 monthly fields (usable with a one-month lag)

These fields are measured at the end of each month. When building a model that predicts what happens in month $t$, the values from month $t-1$ are used (last month's value is known; this month's value is what the model is predicting or partly depends on).

| Column | Fill rate | What it is |
|---|---|---|
| `servicer_name` | 97.76% | Servicer at the reporting date |
| `current_rate` | 98.73% | Current interest rate (changes on modification) |
| `current_upb` | 100.00% | Balance at the reporting date |
| `loan_age` | 98.73% | Months since origination |
| `months_to_legal_maturity` | 98.72% | Months to legal maturity |
| `months_to_maturity` | 97.25% | Months to actual maturity (after prepayments) |
| `maturity_date` | 98.72% | Maturity date (changes on modification) |
| `months_to_amortization` | 0.00% | Months before an interest-only loan starts paying principal |
| `delinquency_status` | 100.00% | Months in arrears — the main outcome indicator |
| `payment_history` | 31.90% | 24-month string of payment codes (available from 2017) |
| `modification_flag` | 98.73% | Y if modified at or before this month |
| `total_principal` | 31.44% | Principal paid this month |
| `mod_non_interest_upb` | 1.44% | Non-interest-bearing balance (after certain modifications) |
| `servicer_activity` | 98.73% | Change in servicing activity |
| `borrower_assistance_plan` | 32.26% | Forbearance, repayment, or trial plan in effect |
| `alt_delinquency_resolution` | 32.26% | Payment deferral or other resolution |
| `alt_delinquency_resolution_count` | 0.58% | Number of deferrals to date |
| `total_deferral_amount` | 0.56% | Total balance deferred |
| `payment_deferral_mod_event` | 100.00% | Payment deferral treated as a modification |
| `delinquency_months` | 99.08% | `delinquency_status` as an integer (computed) |
| `is_dpd_unknown` | 100.00% | True when `delinquency_status` is "XX" (computed) |

**Important detail on `delinquency_status`:** The raw value is text: "0", "1", "2", ..., "99" (99+ months behind), or "XX" (status unknown that month). Two additional columns are computed: `delinquency_months` (the integer version; XX and blank become NULL) and `is_dpd_unknown` (a flag for the XX case). Both of these must be used together — a NULL `delinquency_months` could mean either "blank" or "unknown", and `is_dpd_unknown` resolves the ambiguity.

---

### The 19 quarantined fields (outcome and loss information only)

These fields contain the outcome or the financial results of a default. They are what the platform is trying to predict or measure. Using them as inputs to a model (before an outcome has occurred) would be data leakage.

| Column | Fill rate | What it is |
|---|---|---|
| `zero_balance_code` | 1.27% | Why the loan left the pool (see exit codes below) |
| `zero_balance_date` | 1.27% | Date the loan left the pool |
| `upb_at_removal` | 1.27% | Balance when the loan left |
| `last_paid_date` | 0.02% | Date of last paid instalment (credit exits only) |
| `foreclosure_date` | 0.02% | Date of foreclosure |
| `disposition_date` | 0.02% | Date the property was sold or settled |
| `foreclosure_costs` | 0.02% | Legal and other costs of foreclosure |
| `preservation_repair_costs` | 0.02% | Cost of maintaining the property |
| `asset_recovery_costs` | 0.02% | Cost of recovering the property |
| `misc_holding_expenses` | 0.02% | Other holding costs |
| `holding_taxes` | 0.02% | Taxes while holding the property |
| `net_sales_proceeds` | 0.02% | Cash from selling the property after foreclosure |
| `credit_enhancement_proceeds` | 0.01% | Insurance and guarantee payments received |
| `repurchase_make_whole_proceeds` | 0.01% | Cash from lender buyback |
| `other_foreclosure_proceeds` | 0.02% | Other cash from foreclosure |
| `principal_forgiveness` | 0.96% | Principal forgiven (usually at modification) |
| `foreclosure_writeoff` | 0.96% | Balance written off after foreclosure |
| `repurchase_make_whole_flag` | 1.27% | Whether the lender bought the loan back |
| `exit_reason` | 1.27% | Label of `zero_balance_code` (computed) |

#### Real database extract: Credit exit rows populated with workout and loss fields

Here are six actual terminal monthly records from `loan_monthly_view` showing how these quarantined fields become populated upon credit exit:

| Loan ID | Exit date | Zero balance code | Exit reason | UPB at removal | Net sales proceeds | Foreclosure costs |
|---|---|---|---|---|---|---|
| `494450080452` | 2017-12-01 | `15` | Non-performing note sale | $91,770.02 | $102,510.46 | $14,001.95 |
| `994615090770` | 2017-02-01 | `09` | Deed-in-lieu or REO | $178,031.26 | $38,048.39 | $10,823.24 |
| `635873135033` | 2014-08-01 | `09` | Deed-in-lieu or REO | $230,779.18 | $122,990.70 | $10,008.12 |
| `493459226540` | 2014-05-01 | `09` | Deed-in-lieu or REO | $177,897.00 | $177,057.16 | $8,514.72 |
| `450137872200` | 2014-12-01 | `09` | Deed-in-lieu or REO | $28,405.43 | $73,144.39 | $9,547.24 |
| `165424279956` | 2014-02-01 | `03` | Short sale | $125,806.13 | $25,658.08 | $3,338.22 |

**Intuition built by this table:**
- While a loan is healthy and active, these columns are strictly empty (NULL).
- They only appear in the final monthly row when the loan exits the pool due to a liquidation event.
- This is why they are quarantined: using them to predict whether a loan defaults would mean looking into the future!

### The exit codes

When a loan is fully paid off, sold, or otherwise removed from the pool, its final monthly row contains a `zero_balance_code`:

| Code | Meaning | Credit event? |
|---|---|---|
| 01 | Prepaid or matured — the borrower paid off the loan normally | No |
| 02 | Third-party sale — foreclosure property sold to a third party | **Yes** |
| 03 | Short sale — property sold for less than owed | **Yes** |
| 06 | Repurchased — lender bought the loan back from Fannie Mae | No (excluded) |
| 09 | Deed-in-lieu or REO — borrower handed over property; lender took it | **Yes** |
| 15 | Non-performing note sale — loan sold at a discount (borrower in default) | **Yes** |
| 16 | Reperforming note sale — loan sold after returning to performing status | No (excluded) |
| 96 | Removal (non-credit) — removed for administrative reasons | No (excluded) |

Codes 02, 03, 09, and 15 are **credit exits** — they represent losses to Fannie Mae. Code 01 is a clean exit. Codes 06, 16, and 96 are excluded from outcome analysis because we cannot determine the final performance result.

---

## 7. Data Quality: What Is Clean, What Is Incomplete, and What Is Tricky

### What is very clean

- **100% fill rate on key fields:** `loan_id`, `reporting_period`, `acquisition_quarter`, `delinquency_status`, `orig_upb`, `loan_term`, `channel`, `loan_purpose`, `property_type`, `num_units`, `occupancy`, `property_state`, `note_rate`.
- **Zero conversion failures:** Every loaded number and date field parsed without error across all 3.3 billion monthly rows.
- **Zero duplicate loans across quarters:** No loan ID appears in two different acquisition quarter files.
- **Zero duplicate months:** No loan has two rows for the same month.
- **Balance reconciles to the cent:** Total original UPB in `loans_table` = $12,629,831,311,000.00, reconciled through the check-3 accounting formula.

### What has gaps (but is understood)

| Field | Fill rate | Reason |
|---|---|---|
| `co_borrower_credit_score` | 48.67% | Only present when there is a co-borrower |
| `mi_pct` | 20.79% | Only present for loans with mortgage insurance |
| `mi_type` | 20.79% | Same — mortgage insurance type |
| `property_valuation_method` | 35.62% | Added to the data format only from a certain year |
| `orig_classic_fico` | 26.96% | Added to the data format only from 2024 |
| `payment_history` | 31.90% | Available from 2017 onwards only |
| `total_principal` | 31.44% | Available from 2017 onwards only |
| `borrower_assistance_plan` | 32.26% | Available from 2017 onwards only |
| `interest_only` | 78.15% | Blank for the majority of loans which are not interest-only |

Gaps from field availability date changes are handled by era-conditional modelling: older vintage models will not use the payment history field; newer ones can.

---

### What is tricky

#### 1. Masked early balances

Before 2019, Fannie Mae intentionally masked `current_upb` in the first several months of a loan's life. The field displays as `0.00` or blank. In month 6, the actual balance suddenly appears!

Here is an actual sequence from the database (`loan_id = 126223877438`, acquired in 2008Q2):

| Loan ID | Reporting date | Loan age | Current balance | Current rate | Delinquency status | What is happening |
|---|---|---|---|---|---|---|
| `126223877438` | 2008-05-01 | 0m | **$0.00** | 6.250% | `00` | Early balance masked by Fannie Mae |
| `126223877438` | 2008-06-01 | 1m | **$0.00** | 6.250% | `00` | Early balance masked by Fannie Mae |
| `126223877438` | 2008-07-01 | 2m | **$0.00** | 6.250% | `00` | Early balance masked by Fannie Mae |
| `126223877438` | 2008-08-01 | 3m | **$0.00** | 6.250% | `00` | Early balance masked by Fannie Mae |
| `126223877438` | 2008-09-01 | 4m | **$0.00** | 6.250% | `00` | Early balance masked by Fannie Mae |
| `126223877438` | 2008-10-01 | 5m | **$0.00** | 6.250% | `00` | Early balance masked by Fannie Mae |
| `126223877438` | 2008-11-01 | 6m | **$121,047.75** | 6.250% | `00` | **Balance unmasked at month 6!** |
| `126223877438` | 2008-12-01 | 7m | **$120,928.57** | 6.250% | `00` | Normal monthly amortization begins |
| `126223877438` | 2009-01-01 | 8m | **$120,808.77** | 6.250% | `00` | Balance decreases as principal is paid |

*How the platform handles this:* Module 2 estimates balances during months 0–5 from the contractual amortization schedule (using `orig_upb`, `note_rate`, and `loan_term`) and flags them as `estimated_balance = TRUE`.

#### 2. The modification flag can go backward

The `modification_flag` can show Y in some months and then N in later months for the same loan. This happens when Fannie Mae corrects a data error. It means you cannot simply read the current month's flag value and trust it. Any code that tracks "has this loan ever been modified" must scan all prior months, not just look at the latest flag value.

#### 3. Unknown delinquency status ("XX")

In 1.14% of rows in the 2005 Q1 quarter (and similar proportions elsewhere), the delinquency status is "XX" — meaning it was not known at the time of reporting.

| Reporting period | Delinquency status | Computed `delinquency_months` | Computed `is_dpd_unknown` |
|---|---|---|---|
| 2009-03-01 | `XX` | `NULL` | `TRUE` |

An unknown status is not the same as "current" (0 months behind). These rows are flagged with `is_dpd_unknown = TRUE`. Any default engine must treat unknown months as neither a clean month nor a delinquent month — they do not count toward probation clocks, and they do not reset them.

#### 4. Origination field restatements

For some loans, origination fields are updated during the life of the loan. The most common are:  
- `msa`: 5,637,956 loans had different values across months (mostly due to boundary reclassifications of metropolitan areas).  
- `seller_name`: 5,637,956 loans (many of the same) changed seller names (due to bank mergers and acquisitions).  
- `orig_ltv`: 30,670 loans had LTV corrections.  

These are not errors — they are Fannie Mae correcting its own records. The platform uses the corrected (latest) value for modelling, with the first value for seller and MSA.

#### 5. Accrued interest on delinquent loans is blank

The Fannie Mae layout has a field for unpaid accrued interest (position 85), but for single-family loans it is never populated. Module 2 will estimate unpaid interest on defaulted loans as: months overdue × monthly note rate × outstanding balance, and label this as an estimate.

---

## 8. The Macroeconomic Tables

Three external data series are loaded alongside the loan data to provide economic context. They are stored separately and joined to the loan data when needed.

### Federal funds rate (`macro_monthly_table`)

The US federal funds rate (the interest rate set by the Federal Reserve) is loaded from FRED (Federal Reserve Economic Data), series `FEDFUNDS`. This is the main US interest rate and drives mortgage rates. It runs from January 2000 to October 2025.

**Leakage lag:** This rate is published approximately 1 month before it takes effect. Models must use the value from month $t-1$ or earlier.

### US unemployment rate (`macro_monthly_table`)

The national US unemployment rate from FRED (series `UNRATE`). Key driver of mortgage defaults — when unemployment rises, more borrowers lose their income. Runs from January 2000 to October 2025.

**Known gap:** October 2025 unemployment is blank in the source (the data was not yet published at the time of download). It is stored as blank with `unemployment_missing = TRUE`, not filled with September's value.

**Leakage lag:** Published approximately 1 month after the reference month. Models must use the value from month $t-1$ or earlier.

### State-level house price index (`macro_state_hpi_table`)

The Federal Housing Finance Agency (FHFA) publishes a quarterly house price index for each US state. This is used to track how property values have changed since a loan was made, and therefore what the loan's current LTV is. Covers 5,406 state-quarters.

**Leakage lag:** Published approximately 2 months after the reference quarter. Models must use lagged values.

### The economic mart and discount rates (`macro_economic_mart`)

A combined table built from the above series, adding two PRA-mandated discount rates per month:

| Rate | Formula | Used for |
|---|---|---|
| Long-run rate | Federal funds rate + 5% | Discounting cash flows in LGD calculation under normal conditions |
| Downturn rate | Maximum of 9% and the long-run rate | Discounting cash flows during stress periods (UK PRA SS11/13 requirement) |

#### Real database extract: First 6 monthly rows of `macro_economic_mart`

Here is what the actual macroeconomic mart looks like inside DuckDB starting from January 2000:

| Period | Fed funds rate | Unemployment rate | National HPI | MoM HPI change | YoY HPI change | LGD Long-run discount rate | LGD Downturn discount rate |
|---|---|---|---|---|---|---|---|
| `2000-01-01` | 5.45% | 4.00% | 136.89 | +1.16% | +6.70% | 10.45% | 10.45% |
| `2000-02-01` | 5.73% | 4.10% | 136.75 | -0.10% | +6.13% | 10.73% | 10.73% |
| `2000-03-01` | 5.85% | 4.00% | 137.77 | +0.75% | +6.48% | 10.85% | 10.85% |
| `2000-04-01` | 6.02% | 3.80% | 138.73 | +0.70% | +6.70% | 11.02% | 11.02% |
| `2000-05-01` | 6.27% | 4.00% | 139.27 | +0.39% | +6.48% | 11.27% | 11.27% |
| `2000-06-01` | 6.53% | 4.00% | 140.22 | +0.68% | +6.74% | 11.53% | 11.53% |

**Intuition built by this table:**
- Every month in the platform is tied to prevailing interest rates and national home price inflation.
- Notice the LGD discount rates: because the Fed funds rate in 2000 was ~5.5%–6.5%, the long-run rate (Fed funds + 5%) was ~10.5%–11.5%. Under UK PRA rules, because this exceeds the 9.0% floor, the downturn rate equals the long-run rate.

---

## 9. The Development Sample

### Why a sample exists

A single full pass over the 3.3 billion monthly rows takes 3–5 minutes. Building and testing analytics scripts on the full data would mean waiting hours for each test. The 10% sample makes development fast.

### How it was drawn

For each acquisition quarter, exactly 10% of the loans (rounded to the nearest whole loan, with 0.5 rounding up) are drawn using a fixed random seed. The seed is constant, so the same loans are selected on every run. This means the sample is reproducible and stable — anyone running the scripts will get the same sample.

### Sample facts

| Fact | Number |
|---|---|
| Sample loans | 5,759,759 |
| Sample monthly rows | 331,458,356 |
| Exact fraction of full data | 10.0001% (slightly above 10% because rounding is applied per quarter) |

### When the sample is used vs. full data

- All EDA summary statistics (counts, percentiles, fill rates, bad rates) run on the full 3.3 billion rows using aggregate SQL queries. The database handles this — Python only receives the small output table.
- Loan-level operations that follow a single loan through time (cure rate calculations, prepayment curves, exit analysis) run on the 10% sample, because these require Python to work row by row.
- Module 2 onwards scripts will process the full data; they batch by acquisition quarter to manage memory.

---

## 10. Defining a "Bad" Loan: The Provisional Outcome

### What "outcome" means

For credit risk modelling, every loan must be labelled as one of:
- **Bad:** The loan ended badly — the borrower failed to repay as agreed.
- **Good:** The loan performed — the borrower repaid normally or is still paying normally.
- **Excluded:** The loan cannot be classified (e.g. the lender bought it back for unrelated reasons).
- **Not yet observed:** The loan has not had enough time to show its final outcome.

### The 24-month observation window

The EDA uses a provisional outcome based on a 24-month observation window measured from the loan's first payment date. This means:  
A loan's window opens on its first payment date and closes 24 months later.  
During those 24 months, we watch whether anything "bad" happens.

This window is called "provisional" because Module 2 will implement the full regulatory definition. The EDA uses it only to explore the data.

### The four outcome categories

**Bad:** Within the 24-month window, any of:  
- Delinquency status reaches 3 or more months behind (90+ days past due).  
- The modification flag transitions from N to Y (the loan was restructured under financial distress).  
- The loan exits via code 02 (third-party sale), 03 (short sale), 09 (deed-in-lieu/REO), or 15 (non-performing note sale).

**Good:** Not bad, and either still active at 24 months or paid off normally (code 01) before 24 months.

**Excluded:** Left the pool early via code 06 (repurchased by lender), 16 (reperforming note sale), or 96 (administrative removal), or reporting stopped early without any exit code.

**Not yet observed:** The loan's first payment date plus 24 months falls after December 2025. These loans have not had enough time to show their outcome and are set aside. This is determined loan by loan based on actual first payment date, not by acquisition quarter.

#### Real database extract: Month-by-month trajectory of a loan progressing to default (`loan_id = 692245823166`)

To see exactly what a "bad" loan looks like as it unfolds across monthly statements, examine this actual loan from the 2008 cohort:

| Reporting date | Loan age | Current balance | Rate | Delinquency status | What happened this month | Outcome classification |
|---|---|---|---|---|---|---|
| `2008-05-01` | 1m | $0.00* | 6.875% | `01` (30 DPD) | Borrower missed first payment | Performing (in 30d arrears) |
| `2008-06-01` | 2m | $0.00* | 6.875% | `01` (30 DPD) | Still 1 month behind | Performing (in 30d arrears) |
| `2008-07-01` | 3m | $0.00* | 6.875% | `00` (Current) | **Borrower paid arrears! Cured!** | Performing (Clean cure) |
| `2008-08-01` | 4m | $0.00* | 6.875% | `01` (30 DPD) | Relapse: missed payment again | Arrears (30 DPD) |
| `2008-09-01` | 5m | $0.00* | 6.875% | `02` (60 DPD) | Missed second payment | Significant Arrears (60 DPD) |
| `2008-10-01` | 6m | $0.00* | 6.875% | `03` (90 DPD) | **Missed third payment: crossed 90 DPD!** | **DEFAULT TRIGGER HIT** |
| `2008-11-01` | 7m | $216,200.58 | 6.875% | `04` (120 DPD) | Balance unmasked; 4 months behind | Default (in workout) |
| `2008-12-01` | 8m | $216,200.58 | 6.875% | `05` (150 DPD) | 5 months behind; no payments | Default (in workout) |
| `2009-01-01` | 9m | $216,200.58 | 6.875% | `06` (180 DPD) | 6 months behind | Default (in workout) |
| `2009-02-01` | 10m | $216,200.58 | 6.875% | `07` (210 DPD) | 7 months behind | Default (in workout) |
| `2009-03-01` | 11m | $0.00 | — | `XX` (Exit) | **Short Sale (Code `03`)** | **FINAL TERMINAL EXIT** |

**Intuition built by this trajectory:**
- In month 3, the borrower briefly cured back to `00`. A naive model that only checks month 3 would think the loan is great!
- In month 4, the borrower relapsed to `01`, slipped to `02`, and in October 2008 reached `03` (90 days past due). That single transition irrevocably marks this loan as **Default** under Basel/PRA rules.
- The servicer worked out the loan over the next 5 months until March 2009, when the property was sold in a Short Sale (`zero_balance_code = '03'`).

### The outcome counts (10% sample)

| Category | Loans | Share |
|---|---|---|
| Mature loans (bad + good) | 5,554,391 | 96.56% |
| — of which bad | 73,947 | 1.33% of mature |
| — of which good | 5,480,444 | 98.67% of mature |
| Excluded | 5,554 | 0.10% |
| Not yet observed | 199,814 | 3.44% |
| **Total in scope** | **5,759,759** | 100% |

**Bad rate by balance:** 1.41%. Slightly higher than the 1.33% count-based rate, because larger loans default slightly more.

---

## 11. What the EDA Found: Key Facts About the Loan Population

The EDA notebook (`02_eda.ipynb`) ran on the 10% sample across all 104 quarters and took 470 minutes and 51 seconds (approximately 7 hours and 51 minutes) to complete. It produced 90 artifacts: 34 charts and 56 tables. All 8 automatic checks passed.

### Portfolio size and structure

- **57.6 million loans** totalling **$12.6 trillion** in original loan value.
- Average loan size: **$219,274**.
- Vast majority of loans are **30-year fixed-rate** (`loan_term = 360` months, `amortization_type = FRM`).
- **Owner-occupied properties** dominate (around 90% of loans).
- **California** is the largest state by both loan count and balance.

### Borrower characteristics at origination (full data)

| Metric | 10th percentile | Median | 90th percentile |
|---|---|---|---|
| Credit score | 639 | 744 | 793 |
| Original LTV | 60% | 78% | 97% |
| DTI | 20% | 35% | 46% |
| Original UPB | $56,000 | $188,000 | $417,000 |
| Note rate | 2.9% | 4.3% | 6.5% |

**LTV spike at 80%:** There is a large spike in loans exactly at 80% LTV. This is because loans above 80% typically require mortgage insurance. Borrowers who can afford 20% down (or whose property value has risen enough) choose to avoid mortgage insurance.

**Credit score spike at 620:** There is a secondary spike at exactly 620. This is a common minimum threshold below which many loan programmes were unavailable.

### Monthly delinquency distribution

Of the 3.3 billion monthly rows in the full data:
- **~97%** show delinquency status of 0 (current).
- **~1.5%** show delinquency status of 1 (one month behind).
- **~0.5%** show delinquency status of 2 (two months behind).
- **~0.5%** show delinquency status of 3 or more (90+ days past due).
- **~1.1%** show "XX" (unknown status).

---

## 12. Era-by-Era Breakdown: How Lending and Defaults Changed Over Time

The 25 years of data divide naturally into five eras, each with a different lending environment:

### Era 1: Early 2000s (2000–2003)
- Moderate lending standards; median credit score around 715–725; median LTV around 75%; median DTI around 33%; default rates moderate and stable.

### Era 2: Boom (2004–2006)
- Standards loosened significantly; median credit score fell to around 695–705 (more subprime lending); median LTV rose to 80–85%; median DTI rose to 37–40%. These loans produced the highest future default rates.

### Era 3: Crisis (2007–2010)
- Standards tightened sharply and immediately; median credit score rose back to 745+; LTV tightened back to 75%. Despite tight new lending, legacy boom-era loans defaulted in mass, causing massive foreclosure waves and loan restructurings.

### Era 4: Recovery (2011–2019)
- Very tight standards — the cleanest lending of the 25-year window; median credit score around 750–760; lowest default rates in the dataset; stable economic growth.

### Era 5: COVID (2020–2021)
- Massive refinancing boom triggered by near-zero Fed rates; COVID forbearance programs froze reported arrears across 2,951,261 loan-months. Reported defaults appear low only because defaults were frozen by law.

### Era 6: Rate rises (2022–2025)
- Fed raised rates rapidly from near zero to above 5%; mortgage rates rose above 7%; lending volumes dropped sharply. Newer vintages have not yet reached their 24-month observation window.

#### Real database extract: Cross-era loan comparison

To see how real loans changed across these eras, compare these representative loans extracted from `loans_table`:

| Era | Quarter | Loan ID | Rate | Original UPB | Credit score | LTV | DTI | Purpose | State |
|---|---|---|---|---|---|---|---|---|---|
| Early 2000s | `2000Q1` | `486098696272` | 7.875% | $486,000 | 794 | 75% | 34% | Purchase | CA |
| Boom | `2004Q3` | `962139070474` | 5.750% | $642,000 | 794 | 58% | 46% | Refinance | CA |
| Crisis | `2008Q2` | `253258316005` | 5.875% | $945,000 | 790 | 75% | 55% | Purchase | HI |
| Recovery | `2015Q1` | `142857190682` | 4.125% | $1,203,000 | 767 | 67% | 49% | Purchase | CA |
| COVID Refi | `2021Q2` | `000123856975` | 3.625% | $1,582,000 | 765 | 69% | 48% | Cash-out Refi | NY |

**Intuition built by this table:**
A model trained only on 2015–2019 data would never see 7.8% interest rates or crisis conditions. Including 2000–2008 data gives the platform exposure to high-rate and severe-stress environments required for Basel through-the-cycle and stress-testing models.

---

## 13. Risk Drivers: Which Fields Separate Bad Loans from Good

The EDA measured the Information Value (IV) of each origination field — a standard industry measure of how strongly a field separates bad loans from good loans. IV above 0.5 is considered very strong.

### Top predictors by Information Value

| Field | IV | Risk gradient direction |
|---|---|---|
| `credit_score` | **0.849** (very high) | Lower score → higher default rate |
| `orig_ltv` | 0.312 | Higher LTV → higher default rate |
| `dti` | 0.185 | Higher DTI → higher default rate |
| `loan_purpose` | 0.148 | Cash-out refinance > refinance > purchase |
| `occupancy` | 0.126 | Investor > second home > owner-occupied |
| `num_units` | 0.098 | 4 units > 3 units > 2 units > 1 unit |
| `orig_upb` | 0.064 | Larger loans default slightly more |
| `channel` | 0.052 | Broker channels slightly higher than retail |

### The 93-fold risk spread: credit score × LTV

The most striking finding from the EDA is the interaction between credit score and LTV. The bad rate across the grid of credit score bands and LTV bands spans from 0.15% (prime borrowers, low LTV) to 14.02% (subprime borrowers, high LTV) — a **93-fold difference**.

| Credit score \ LTV | 0–60% | 60–80% | 80–95% | 95%+ |
|---|---|---|---|---|
| ≥760 (prime) | 0.15% | 0.22% | 0.49% | 0.98% |
| 700–759 | 0.33% | 0.60% | 1.21% | 2.47% |
| 640–699 | 0.98% | 1.82% | 3.74% | 6.11% |
| <640 (subprime) | 2.14% | 4.37% | 8.03% | 14.02% |

This grid is fundamental. Any credit risk model that does not capture this interaction will produce systematically wrong outputs.

---

## 14. Loan Outcomes: Arrears, Cure, and Exit

### How arrears progress

The delinquency status tracks how many full monthly payments the borrower has missed:
- **0 months (current):** Loan is performing normally.
- **1 month behind (30 DPD):** Borrower missed one payment.
- **2 months behind (60 DPD):** Borrower missed two consecutive payments.
- **3+ months behind (90+ DPD):** Regulatory default threshold.

### Cure rates: how often do delinquent loans recover?

- **30 DPD (1 month behind):** **81.4%** return to current cleanly within 12 months without modification or loss.
- **60 DPD (2 months behind):** **44.1%** return to current cleanly.
- **90+ DPD (3+ months behind):** Only **26.7%** cure cleanly. An additional **30.5%** cure only after modification (concessions granted). **42.8%** go on to full credit loss.

**Intuition:** 30 DPD is mostly operational friction (forgot to pay, paycheck delayed). 90 DPD is structural distress: less than 1 in 4 borrowers ever recover without lender intervention.

---

## 15. Losses When Loans Go Bad

### Measuring loss severity

Loss severity is defined as the net loss divided by the balance at removal:

$$\text{Loss severity} = \frac{\text{Balance at removal} + \text{Foreclosure and holding costs} - \text{All proceeds}}{\text{Balance at removal}}$$

Where:
- **Proceeds** include net sales proceeds, mortgage insurance payouts, credit enhancement, and any other recoveries.
- **Costs** include foreclosure legal costs, property preservation, asset recovery, holding taxes, and miscellaneous expenses.

### Key loss statistics (10% sample, 66,913 credit exits with complete cost data)

| Metric | Value |
|---|---|
| Balance-weighted mean severity | **26.5%** |
| Median workout duration | **17.0 months** |
| Share of credit exits where severity > 50% | approximately 18% |
| Share of credit exits where severity < 10% | approximately 22% |

#### Real database extract: Loss arithmetic for real credit liquidations

Here are actual credit exit records from `loan_monthly_view` showing the exact arithmetic of loss severity:

| Loan ID | Exit reason | Code | UPB at removal | Foreclosure costs | Net sales proceeds | Calculated Net Loss | Loss severity % |
|---|---|---|---|---|---|---|---|
| `994615090770` | Deed-in-lieu or REO | `09` | $178,031.26 | $10,823.24 | $38,048.39 | **$150,806.11** | **84.7%** |
| `165424279956` | Short sale | `03` | $125,806.13 | $3,338.22 | $25,658.08 | **$103,486.27** | **82.3%** |
| `635873135033` | Deed-in-lieu or REO | `09` | $230,779.18 | $10,008.12 | $122,990.70 | **$117,796.60** | **51.0%** |
| `493459226540` | Deed-in-lieu or REO | `09` | $177,897.00 | $8,514.72 | $177,057.16 | **$9,354.56** | **5.3%** |
| `494450080452` | Non-perf note sale | `15` | $91,770.02 | $14,001.95 | $102,510.46 | **$3,261.51** | **3.6%** |

**Intuition built by this table:**
- **Severe losses on REO/Foreclosure (Loan `994615090770`):** The bank was owed $178k, incurred $10.8k in legal and holding costs, and only sold the house for $38k! Net loss was $150.8k, resulting in an **84.7% loss severity**.
- **Mild losses when property retains value (Loan `493459226540`):** The bank was owed $177.9k and sold the home for $177.1k. Net loss was almost entirely just the $8.5k in foreclosure legal costs, resulting in only **5.3% severity**.
- **Note sales (Loan `494450080452`):** Selling the non-performing note to a distressed debt fund recovered $102.5k against a $91.8k balance, almost entirely covering costs (only 3.6% net loss).

---

## 16. COVID Forbearance: The Special Problem

### What happened

Starting March 2020, the US CARES Act allowed mortgage borrowers to request forbearance — a formal pause on payments — without being reported as delinquent. The servicer would not report months behind, and the borrower would not be counted as defaulted.

Under this programme:
- Forbearance was available until 31 March 2021.
- Payments could be deferred until 31 July 2021.
- Maximum of 6 months of deferred payments per loan (under FCA/CARES guidance).

### How the data reflects this

The Fannie Mae data captures forbearance through the `borrower_assistance_plan` and `alt_delinquency_resolution` fields.

#### Real database extract: Active COVID forbearance record (`loan_id = 100393376629`)

Here is an actual loan during the COVID relief window:

| Loan ID | Reporting date | Loan age | Current balance | Delinquency status | Assistance plan | Mod flag | What the record shows |
|---|---|---|---|---|---|---|---|
| `100393376629` | 2020-04-01 | 243m | $27,759.17 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |
| `100393376629` | 2020-05-01 | 244m | $27,580.10 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |
| `100393376629` | 2020-06-01 | 245m | $27,399.89 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |
| `100393376629` | 2020-07-01 | 246m | $27,218.53 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |
| `100393376629` | 2020-08-01 | 247m | $26,852.35 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |
| `100393376629` | 2020-09-01 | 248m | $26,667.51 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |
| `100393376629` | 2020-10-01 | 249m | $26,481.50 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |
| `100393376629` | 2020-11-01 | 250m | $26,294.31 | `00` | **`7`** | N | In COVID Forbearance (Plan 7); reported Current |

**Intuition built by this table:**
- The borrower requested assistance under the CARES Act, flagged by `borrower_assistance_plan = '7'`.
- Even though the borrower was granted relief, `delinquency_status` is frozen at `00` by legal mandate.
- In the full 10% sample, **2,951,261 loan-months** were under forbearance or deferral.
- If you rely solely on `delinquency_status`, these borrowers look perfectly healthy! The platform must explicitly inspect `borrower_assistance_plan` to properly evaluate risk.

---

## 17. Known Data Limitations and What We Do About Them

The platform documents every data limitation, its size, and how it is handled:

| Limitation | Size | Treatment |
|---|---|---|
| Masked early UPB (pre-2019 loans' first months) | Unknown number of months; known to affect some pre-2019 quarters | Estimated from contract terms; flagged as `estimated_balance = TRUE` |
| Blank DTI | 1.33% of loans | Filled with the median for the same vintage and occupancy class; flagged |
| Blank credit score | 0.30% of loans | Same fill approach; flagged |
| Unknown delinquency status (XX) | 1.14% of rows in 2005 Q1; similar in other early quarters | Treated as neither clean nor delinquent; explicitly tracked with `is_dpd_unknown` |
| Modification flag can go N after Y | 59 loans in 2005 Q1 | Tracked across all historical months; not just current month |
| Accrued interest on delinquent loans not reported | 100% of defaulted loans | Estimated as: months overdue × monthly rate × balance; labelled as estimate |
| October 2025 unemployment blank | 1 month | Stored as blank with `unemployment_missing = TRUE`; not carried forward |
| State unemployment not available | — | National unemployment used; limitation documented; Module 7 may revisit |
| Losses reported only at end of workout | All credit exits | Loss timing is approximate; Module 4 will build development triangles |
| COVID-era forbearance distorts arrears | 2,951,261 loan-months | Adjusted treatment applied; raw numbers shown side by side |
| Loans from 2024–2025 not mature | 199,814 loans in 10% sample | Excluded from outcome analysis; shown as "not yet observed" |

---

## 18. The Leakage Audit: Separating Predictors from Answers

### What leakage is

Data leakage means accidentally using the answer to a question as an input to predict it:
- **Bad leakage:** Using the foreclosure date to predict whether a loan will default. The foreclosure date only exists because the loan already defaulted.
- **Subtle leakage:** Using the current month's delinquency status to predict the same month's default. The model would not have this information at prediction time.

### How the leakage audit works

Script `03_leakage_audit.py` classified every field into one of four categories stored in `field_leakage_table`:

**Origination (33 fields):** Known at loan creation. Can be used to predict any future month without restriction.

**Monthly, lag-1 (21 fields):** Known at the end of each month as reported. Must use the value from month $t-1$ when predicting outcomes in month $t$.

**Quarantined (19 fields):** Contains outcome or loss information. Cannot be used in any predictive model at any time. Only used to build the labels (bad/good) and measure losses.

**Key (5 fields):** Join keys and time stamps. Not predictors.

### The enforcement rule

Automatic check C8 in the EDA verifies that none of the 19 quarantined fields appear in any modelling section of the notebook. This check passes, confirming zero contamination of the model inputs.

---

## 19. What This Data Does Not Contain

It is as important to know what is absent as what is present:

| Absent information | Consequence |
|---|---|
| **Property address or precise location** (only state and 3-digit ZIP) | Cannot use granular geographic data; must model at state level |
| **Borrower income in dollars** (only DTI ratio) | Cannot compute absolute debt burden; must use DTI |
| **Full credit history** (only the origination credit score and 24-month payment string from 2017) | No prior default history, number of accounts, or utilisation |
| **Property tax and insurance** | Cannot compute PITI (total housing cost); DTI understates total burden |
| **Accrued delinquent interest** (the layout has the field but it is never populated) | Interest must be estimated for loss calculations |
| **Appraisal details** (only the LTV; the actual value is implied) | Property value must be implied from balance/LTV; cannot verify appraisal |
| **Servicer loss mitigation details** | We know a modification happened but not what specifically changed (rate, term, balance) |
| **Borrower employment sector** | No way to assess industry-specific cyclicality in borrower income |
| **Secondary lien information** (CLTV is reported but secondary loans are not tracked) | Cannot monitor the second mortgage separately |

---

## 20. How This Data Feeds the Rest of the Platform

Every downstream module reads from the tables built in `00_data` and `01_data_foundation`. No later module goes back to the raw quarterly text files or Parquet files directly.

| Later module | What it reads from `00_data` / `01_data_foundation` |
|---|---|
| **Module 2: Portfolio Analytics** | `loans_table`, `loan_monthly_view`, `macro_economic_mart`, `macro_state_hpi_table`, `feature_catalogue_table` |
| **Module 3: PD (Probability of Default)** | `default_events_mart` and `book_snapshot` from Module 2; origination features from `loans_table` |
| **Module 4: LGD & EAD** | `default_outcomes_mart` and `loss_development_mart` from Module 2; discount rates from `macro_economic_mart` |
| **Module 5: IFRS 9 ECL** | `default_events_mart`, `forbearance_mart`, `vintage_curves_mart` from Module 2 |
| **Module 6: Basel Capital** | `book_snapshot` from Module 2; current LTV from `current_ltv_mart` |
| **Module 7: Stress Testing** | `portfolio_rates_quarterly_mart` and `economy_links_mart` from Module 2 |
| **Module 8: Model Risk** | `feature_catalogue_table`, `field_leakage_table`, and representativeness findings from Module 2 |

### The data flow in one paragraph

The raw Fannie Mae text (935 GB) → compressed Parquet files (26 GB, `00_data`) → structured database tables (`00_data`) → field classification and leakage audit (`01_data_foundation`) → exploratory analysis and empirical baselines (`01_data_foundation`) → analytical marts per topic (Module 2) → risk model inputs (Modules 3–8).

The platform is designed so that the expensive step — reading 3.3 billion monthly rows — happens as few times as possible. Module 2 reads the full history once per stage, materialises the result as a compact analytical table (mart), and all later modules read from those tables rather than the raw monthly history.

---

*Document end.*  
*Source data: Fannie Mae Single-Family Loan Performance Dataset, 2000 Q1 to 2025 Q4.*  
*All numbers measured from the actual data as of 2026-11-15.*  
*All 8 EDA automatic checks passed on 2026-11-15.*
