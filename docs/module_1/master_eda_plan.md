# EDA plan: Fannie Mae mortgage data (Module 1, step 5)

Status: signed off by Devesh 2026-11-15. Replaces the earlier version of this file.
Notebook: `residential_mortgage\01_data_foundation\02_eda.ipynb`. It is already built
(98 cells, D-024) and will be changed to match this plan after sign-off.
Reference: the LendingClub EDA notebook in `E:\Repos\credit-risk-portfolio\phase0_data_platform\`
(read only).

## What the EDA is for
Describe the loan data before anything is modelled:
- what is in it and how complete it is;
- what changes over time;
- what a bad loan looks like;
- which fields later modules may use.

The EDA describes; it does not build models or set the default definition.

## Rules for the whole notebook
1. **Plain words.** Every step says, in a sentence or two, why it is there, how it is worked
   out and what it answers. A credit analyst who reads simple Python must follow it.
2. **Numbers in the text come from the code.** Result and interpretation cells are filled from
   computed values, never typed by hand. The LendingClub notebook typed its numbers in, and
   they can drift from the results.
3. **Work happens in the database.** Counts, percentiles and rates are aggregate SQL over the
   full data. Python only receives small summary tables.
   Steps that follow a loan from month to month (cure rates, exit curves) run on the 10%
   development subset, and the step says so.
4. **Read the existing registers, do not redo them.** Field classes come from
   `field_leakage_table` (03_leakage_audit.py). Field descriptions and fill rates come from
   `feature_catalogue_table` (04_feature_catalogue.py). The EDA adds its findings to them.
5. **Show the size of a difference, not a p-value.**
   - Rates carry a 95% confidence interval (Wilson).
   - Differences are given in percentage points and as a ratio.
   - Cells with fewer than 1,000 loans are not shown on their own.
   - With millions of loans every p-value is about zero, so p-values tell us nothing.
6. **Count and balance.** Bad rates are shown by loan count, and also weighted by original
   balance where the two can differ.
7. **Rules of thumb are called rules of thumb.** IV bands (0.02 weak, above 0.5 check for
   leakage), PSI bands (0.10 and 0.25) and VIF above 10 are industry practice, not
   regulation.
8. **Regulation.** Cite a UK rule only after the source-checker has confirmed its wording.
   Where the US data departs from UK rules, point to `docs\departures_from_uk_rules.md`
   (D-025). No US supervisory references.
9. **Reproducible.** The first table records the run date, the database file, the loaded
   quarters, whether `--sample` is on, and the package versions. No hashes.
10. **Outputs.** Charts go in `02_eda_outputs\charts\` and tables in `02_eda_outputs\tables\`.
    The notebook keeps one list of every output it writes, and check C7 reads that list.

## The provisional outcome (D-024, for the EDA only)
This is not the default definition. Module 2 (`02_default_engine.py`) builds the real one, and
only the function `build_loan_outcome()` then changes.

- **Window:** 24 months counted from the loan's first payment date. `loan_age` is blank on
  exit rows, so it is not used.
- **Bad:** within the window, any of:
  - 3 or more months behind;
  - modification flag Y;
  - exit by third-party sale, short sale, deed-in-lieu/REO or non-performing note sale
    (codes 02, 03, 09, 15).
- **Good:** not bad, and either still reporting at 24 months or paid off (code 01) earlier.
- **Excluded:** left early by repurchase, reperforming note sale or removal
  (06, 16, 96), or reporting stopped early without an exit.
- **Not yet observed:** decided loan by loan. First payment date plus 24 months falls after
  the last month in the data (December 2025).
  - This is a change from the old plan, which cut off by acquisition quarter at 2023Q4.
  - That cut-off was wrong for two reasons. Loans acquired in 2023Q4 first pay in early 2024,
    so they cannot have 24 months by December 2025. And one quarter can hold loans
    originated years earlier: 2005Q1 holds loans from 1999.
- **Open question for Module 2:** payment deferrals and COVID forbearance (section 09 shows
  how much they matter).

## Sections
The numbers follow the LendingClub notebook where the step is the same. The last column says
what changed.

| # | Section | Answers | Compared with LendingClub |
|---|---|---|---|
| 00 | Setup and scope | What data is loaded, and is this a full or a subset run? | Same, plus a run record (rule 9) |
| 01 | What is in the data | Which fields, their types, how full they are, and any conversion failures | Same; reads the catalogue |
| 02 | Data quality and leakage | Keys, restated origination fields, missing values by vintage, whether a blank field is linked to bad loans, field classes and the lag on economic data | Same; field classes read, not redone |
| 03 | Monthly history checks | Are loan histories complete and in order? | New: mortgages are monthly histories |
| 04 | One field at a time | Spread, spikes (such as LTV exactly 80), category mix, impossible values, skew and tails | Same; transformation choices left to Module 3 |
| 05 | Two fields at a time | Which fields separate bad from good, and which repeat each other? | LendingClub 04 and the VIF part of 09; no logistic model |
| 06 | Over time and by place | How lending standards and results changed, by era and by state | Same, plus eras and indexed LTV |
| 07 | The outcome | How many loans are bad, good, excluded or not yet observed; delinquency steps and cure rates; the FICO x LTV grid | Same; maturity decided loan by loan |
| 08 | Defaults and prepayments together | How fast loans default and how fast they repay early, by vintage | New: replaces hypothesis tests |
| 09 | Payment deferral and forbearance | How the 2020-2021 relief changed delinquency, and what that means for the outcome | New |
| 10 | Losses on credit exits | How much is lost when a loan ends badly, and how long it takes | New: LendingClub had only simple recovery fields |
| 11 | Who is in and who is out | How all loans narrow to the outcome population, and is the 10% subset a fair copy? | Same, plus the subset check |
| 12 | Fields with many values | Seller and servicer concentration, sparse MSA and ZIP3 groups | Same |
| 13 | Checking the story | Do the main risk gaps hold within FICO and LTV bands? | Same, with intervals |
| 14 | Summary and hand-off | Headline numbers, EDA findings per field, open items for later modules | Same; joins to the catalogue |
| 15 | Automatic checks | Did every total add up? | New: LendingClub had no checks |

**Left out on purpose** (each needs loan-level rows in Python, or belongs to Module 3):
- clustering, PCA and Isolation Forest;
- the logistic regression baseline;
- p-value tests;
- choosing transformations.

## What each section does

### 00 Setup and scope
- Open the database read-only. Write the run record (rule 9).
- List the tables and the view, with row counts.
- Show the loaded quarters, loans, monthly rows and total original balance, from
  `loaded_quarters_table`.
- Build the provisional outcome once, and show its counts.

### 01 What is in the data
- Read the field list, types and fill rates from `feature_catalogue_table`.
- Fill rates of the monthly fields by decade, so a field that is normally empty (such as the
  exit fields) is not mistaken for a gap.
- Values that failed number or date conversion: expected 0.

### 02 Data quality and leakage
- No loan twice; no duplicate (loan, month).
- Restated origination fields from `origination_restatements_table`, ranked.
- Missing values by vintage, as a heatmap (loans and monthly fields).
- Blank against filled: the bad rate when a field is blank against when it is filled, for
  fields at least 0.1% blank.
- Field classes from `field_leakage_table`: origination, one-month lag, quarantined, key.
- Economic data lag: unemployment is published about 1 month late and house prices about
  2 months late. The EDA states the lag any model must apply.

### 03 Monthly history checks (new)
- Months missing inside a loan's history.
- Rows after the loan's exit.
- Loans that stop reporting without an exit code, before December 2025 (these are cut
  short, not good).
- Seasoned loans: the gap between origination date and acquisition quarter. Vintage curves
  start from the origination date, and allow for loans that join the data late.
- Servicer changes per loan.

### 04 One field at a time
- Percentiles (1, 5, 25, 50, 75, 95, 99), mean, skew, and share in the top and bottom 1%,
  for FICO, LTV, CLTV, DTI, rate, balance and term.
- Small histograms. Spikes at round values (such as LTV 80 or 95) are named.
- Category mix with shares (channel, purpose, property type, occupancy, borrowers).
- Impossible-value rules, such as FICO outside 300-850, LTV above 150 or DTI above 100.
  These are reported, not failed.

### 05 Two fields at a time
- IV and weight of evidence on 10 bands against the provisional outcome. Fields above 0.5
  are checked for leakage.
- Bad rate by band for the top fields, to see whether risk rises steadily.
- Pearson and Spearman correlations. Pairs above 0.7 are named (such as LTV and CLTV).
- Cramer's V for category pairs.
- VIF from the correlation matrix.
- All run on origination fields only; quarantined fields never enter.

### 06 Over time and by place
- Medians with a 10th-90th percentile band by vintage, for FICO, LTV, DTI, rate and balance.
- Six eras:

  | Era | Years |
  |---|---|
  | Early 2000s | 2000-2003 |
  | Boom | 2004-2006 |
  | Crisis | 2007-2009 |
  | Recovery | 2010-2019 |
  | Pandemic | 2020-2021 |
  | Rate rises | 2022-2025 |

- PSI of each era against one reference era, recovery (2010-2019), stated in the text.
- Bad rate by vintage, beside the federal funds rate and unemployment at origination.
- Indexed LTV over the loan's life. Original property value = original balance / original
  LTV, moved with the state house price index from the origination month. This runs after
  the fixed macro script has rebuilt the macro tables.
- State: loans, balance share and bad rate with intervals; the concentration index.
- Active loans by month.

### 07 The outcome
- Bad, good, excluded and not yet observed, by count and by balance. What bad is made of
  (first trigger).
- Delinquency status counts, including XX (unknown).
- Cure rates: of loans 1, 2, 3 and 4 months behind, the share back to current within
  12 months (subset). This shows support for the 90-day line; it does not set it. The UK
  backstop is in the regulation, cited once confirmed.
- Exit codes, all 8 kinds.
- FICO x LTV grid: bad rate with intervals.
- Occupancy x LTV: loans and balance (a description only; risk weights are Module 6).

### 08 Defaults and prepayments together (new)
- For each era: of the loans that started, the share that had defaulted, prepaid or were
  still open by each month on book (cumulative default and prepayment curves; subset).
  Prepayment is a competing exit: a loan that repays early cannot default later.
- Monthly and yearly prepayment speed (SMM and CPR) by era.

### 09 Payment deferral and forbearance (new)
- Loans and months under payment deferral or an assistance plan, by month (peak in
  2020-2021).
- How delinquency status behaves during and after deferral.
- What happens to the outcome counts if deferral months are left out. This gives Module 2
  the size of the question.

### 10 Losses on credit exits (new)
- Net loss = balance at removal + costs - sale and other proceeds. Severity = net loss /
  balance at removal.
- Severity by era, state and LTV band.
- Months from default to sale.
- Sales in the last 6 months of the data are left out, because the proceeds fields arrive
  about 90 days after the sale (Fannie Mae FAQ).

### 11 Who is in and who is out
- Waterfall: all loans, then with first payment date, then observed for 24 months, then
  the outcome population.
- Kept against left-out loans: median FICO, LTV and DTI.
- 10% subset against full data: bad rate and medians, with the gap and its interval
  (full run only).

### 12 Fields with many values
- Top 5, 10 and 20 sellers and servicers by share; the concentration index.
- MSA and ZIP3: groups with fewer than 1,000 loans, and how to pool them.

### 13 Checking the story
- Bad rate by loan purpose within FICO bands.
- Bad rate by occupancy within LTV bands.
- Each with intervals. A gap that holds in every band is a real effect, not a mix effect.

### 14 Summary and hand-off
- Headline numbers, from code.
- One row per field: the catalogue columns plus the EDA findings (IV, PSI, VIF, blank-rate
  gap, impossible values). Saved as a CSV and joined to `feature_catalogue_table`. Not a
  second register.
- Open items, each naming the later module and script that takes it.

### 15 Automatic checks (stop the run on failure)
| Check | Passes when |
|---|---|
| C1 | Loans in scope = loans in `loans_table` (or in the subset with `--sample`) |
| C2 | Monthly rows by vintage = monthly rows by month = the ledger total |
| C3 | Vintages = rows in `loaded_quarters_table` |
| C4 | For each histogram: band counts + blanks = loans |
| C5 | Bad + good + excluded + not yet observed = loans |
| C6 | The waterfall's start minus its steps = its end |
| C7 | Every output in the notebook's list exists and is not empty |
| C8 | No quarantined field is used in sections 05, 06 or 13 |

## Order of work
1. Sign-off of this plan.
2. The EDA session changes `02_eda.ipynb` to this plan, and tests it on the test database.
3. After the full build: run the post-load checks, then rerun the fixed macro script,
   then the leakage audit and the feature catalogue.
4. Run the notebook with `--sample`, then on the full data.
