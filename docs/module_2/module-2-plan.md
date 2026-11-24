# Module 2 plan: portfolio analytics

Date: 2026-11-16. Status: DRAFT, not signed off. All decisions M2-1 to M2-14 made (section 5); M2-2 and M2-7 to M2-11 to be walked through before sign-off.
Additions (2026-11-24, DRAFT, not signed off): section 8 adds missing pre-modelling
analytics as separate modular scripts - 01b_data_plausibility, 03b_emergence_and_thresholds,
06b_sample_population, 12b_survivorship - plus two new stages 7b (segmentation) and 10b
(cycle and benchmarks) - and the regulatory analytical items for IFRS 9 provisions and
CRR/PRA capital. All descriptive; no model fitting.
Source: docs\v4_build_plan_revised.md, lines 195-320, corrected by docs\known_issues.md and
docs\plan_corrections_proposal.md (items 7, 8, 10).
Widened on 2026-11-16 at the user's request: Module 2 does all the portfolio analysis that
Modules 3 to 8 need (rating and PD, LGD and EAD, IFRS 9, capital, stress testing, model
risk), so no later module has to go back to the raw monthly data for a basic fact.
Section 2 checks every later script against this plan.
Paths: all Module 2 files live under residential_mortgage\02_portfolio_analytics\.
Packages: none new. duckdb 2.0.0, pandas 3.1.1 and matplotlib 3.11.2 are already installed.

## 1. What Module 2 does

Seven stages. Each script answers one question and writes one main table.

| Stage | # | Script | Question it answers | Main output |
|---|---|---|---|---|
| A. Foundations | 1 | `01_data_audit.py` | Does every loan and every unit of balance roll forward month to month, with every change explained? | `balance_rollforward_mart` |
| | 1b | `01b_data_plausibility.py` | Are field values plausible, are there outliers, re-aging or duplicate records, and how do fill rates move over time? | `data_plausibility_mart` |
| | 2 | `02_default_engine.py` | When is a loan in default, what triggered it, and when has it recovered? | `default_events_mart` |
| B. How loans and values move | 3 | `03_roll_rates.py` | How do loans move between arrears stages, and how often does 1 or 2 months behind lead to default? | `roll_rates_mart` |
| | 3b | `03b_emergence_and_thresholds.py` | How long from first missed payment to default, and does the default rate change under a 60/90/120-day threshold? | `emergence_mart` |
| | 4 | `04_vintage_curves.py` | For each vintage and segment, how fast do loans default and repay early, month by month on book? | `vintage_curves_mart` |
| | 5 | `05_current_ltv.py` | What is each loan's property value and LTV today, indexed and on the capital rule's downward-only basis? How far did house prices fall in past downturns? | `current_ltv_mart` |
| | 6 | `06_default_rate_history.py` | What share of performing loans defaulted within 12 months, at each point in time? Long-run average and downturn years. Also builds the December book snapshot that later modules start from. | `default_rate_history_mart`, `book_snapshot` |
| | 6b | `06b_sample_population.py` | Who is excluded from the PD sample, and how do the excluded loans differ from the included ones? | `sample_population_mart` |
| C. Risk drivers | 7 | `07_risk_drivers.py` | Which origination and behaviour features separate good loans from bad, are they stable over time, and which segments behave differently? | `risk_drivers_mart` |
| | 7b | `07b_segmentation.py` | Are the candidate segments statistically different, and which feature interactions drive the highest-risk pockets? | `segmentation_mart` |
| D. After default | 8 | `08_default_outcomes.py` | What happens after default, how long it takes, how much is lost and recovered, and how losses build up over time since default? | `default_outcomes_mart`, `loss_development_mart` |
| | 9 | `09_forbearance.py` | How much modification, deferral and forbearance is there, and how do those loans perform afterwards? | `forbearance_mart` |
| E. Book and economy | 10 | `10_economy_links.py` | How do default, cure, prepayment and loss rates move with unemployment, house prices and interest rates, with what delay? How severe were past downturns? | `economy_links_mart`, `portfolio_rates_quarterly_mart` |
| | 10b | `10b_cycle_and_benchmarks.py` | How long do downturns last and how fast do rates recover; is there seasonality; do observed rates match industry benchmarks? | `cycle_mart` |
| | 11 | `11_portfolio_mix.py` | What does the book look like over time, where is risk concentrated, and are there early warning signs? | `portfolio_mix_mart` |
| F. Fitness of the data | 12 | `12_representativeness.py` | Is the history a fair guide to today's book? Which data limits and changes in lending need a margin of conservatism? | `representativeness_mart` |
| | 12b | `12b_survivorship.py` | How much do the 2000 panel start and late-acquired loans bias early vintages toward survivors? | `survivorship_mart` |
| G. Handover | 13 | `13_portfolio_findings.md` | What did we find, and what exactly does each later module take from Module 2? | the document itself |

## 2. What each later module needs, and where Module 2 provides it

"Here" means Module 2 provides it. "Later" means the later module does it itself, from
Module 2's tables.

### Module 3: rating and PD

| Later script | Needs | Where |
|---|---|---|
| 01 application scorecard | Default flag and default date | Here: 2 |
| | Loan-level 12-month outcome at fixed observation points, with exclusions, era and segment | Here: 6 (`book_snapshot`) |
| | Default rate by band for each origination feature; rank ordering; stability; pairs that move together | Here: 7 |
| | WoE, IV cut-offs, VIF, the fitted model, score scaling | Later |
| 02 behavioural scorecard | Arrears history (worst in last 6 and 12 months, months since last arrears), modification history, current LTV, balance paid down, months on book, rate incentive; their default rates and stability | Here: 5, 7 |
| 03 PIT PD | Default rate against unemployment and state house price change, with lags | Here: 6, 10 |
| 04 TTC PD | Long-run average default rate over the full history; which years are the downturn; years of data per segment | Here: 6 |
| 05 calibration and cyclicality | Yearly observed default rates by segment | Here: 6 |
| | Grade migration and the PRA cyclicality measure | Later |
| 06 master rating scale | Grades and grade migration | Later |
| 07 validation and MoC | Out-of-time flags on the outcome table | Here: 6 |
| | Data deficiencies sized (MoC A); changes in lending and servicing (MoC B); drift of today's book from history | Here: 12 |
| | Binomial tests, Brier, PSI on scores, Pluto-Tasche | Later |

### Module 4: LGD and EAD

| Later script | Needs | Where |
|---|---|---|
| 01 workout LGD | Default date, end of workout, dates of foreclosure and sale; costs and proceeds by type | Here: 8 |
| | Unresolved workouts and how losses build up by months since default (for a development triangle) | Here: 8 (`loss_development_mart`) |
| | Share of defaults that cure without loss (hurdle stage 1); loss given no cure (stage 2) | Here: 8 |
| | Loss on loans that cure through modification (principal forgiven, balance made interest-free) | Here: 8, 9 |
| | Discount rate at the default month | Module 1 (`macro_economic_mart`) |
| | Discounting, development triangles, hurdle model | Later |
| 02 component LGD | Probability of no cure by segment | Here: 8 |
| | Peak-to-trough house price falls by state (against the 25% minimum and 40% reference) | Here: 5 |
| | Observed forced-sale discount: sale proceeds against indexed property value at sale | Here: 8 |
| | Costs as a share of balance at default | Here: 8 |
| 03 expected loss | Balance at default against balance 6 and 12 months earlier; unpaid interest at default (estimated, see note) | Here: 8 |

Note: Fannie Mae leaves delinquent accrued interest (layout position 85) blank for
single-family loans. Module 2 estimates unpaid interest as months behind x monthly note
rate x balance, and states it as an estimate.

### Module 5: IFRS 9

| Later script | Needs | Where |
|---|---|---|
| 01 staging | In default and in probation by month (Stage 3) | Here: 2 |
| | Loans 1 month behind (30-days backstop) and how often they go on to default; evidence for or against rebutting the backstop | Here: 3 |
| | Forborne loans, performing and non-performing | Here: 9 |
| | PD at origination against current PD | Later (Module 3 PDs) |
| 02 PD term structure | Monthly default and prepayment rates by months on book and segment, for performing loans (competing risks) | Here: 4 |
| | Expected life of a loan | Here: 4 |
| 03 lifetime LGD and EAD | Scheduled repayment and prepayment speeds | Here: 1, 4 |
| | Loss against current LTV at default and house price change from default to sale | Here: 8 |
| 04 scenario ECL | Past downturn severity (unemployment rise, house price fall) nationally and by state | Here: 10 |
| | How sharply loss rises with LTV (the non-linearity the scenarios capture) | Here: 8 |
| 05 movement waterfall | New lending, repayments, prepayments, write-offs, recoveries by month | Here: 1 |
| | Stage moves and ECL amounts | Later |

### Module 6: capital

| Later script | Needs | Where |
|---|---|---|
| 01 standardised RWA | Today's book at a reference date, loan by loan | Here: 6 (`book_snapshot`) |
| | Property value updated downwards only (Article 124D), and LTV on that value | Here: 5 |
| | Book by owner-occupied, second home and investor; by units; by the capital rule's LTV bands (55% split; investor bands) | Here: 11 |
| | Risk weights | Later |
| 02 AIRB | PD and LGD | Later (Modules 3, 4) |
| | Correlation implied by the yearly default rate history, as a check on the fixed 0.15 | Here: 6 |
| 03 economic capital and RAROC | Note rate, balance and segment for each loan in the reference book | Here: 6, 11 |

### Module 7: stress testing

| Later script | Needs | Where |
|---|---|---|
| 01 satellite models | Quarterly default, cure, prepayment and loss rates, ready to join to the economic series | Here: 10 (`portfolio_rates_quarterly_mart`) |
| | First look at lags and links | Here: 10 |
| | Stationarity tests, ARDL models, state inversion | Later |
| 02 stress projection | Prepayment against interest rates; past downturn severity; starting book | Here: 4, 6, 10 |
| | Pre-crisis book (December 2006 or 2007), to test the projection against what happened | Here: 6 |
| 03 reverse stress | Past joint moves of unemployment, house prices and rates | Here: 10 |

### Module 8: model risk

| Later script | Needs | Where |
|---|---|---|
| 01 inventory, 02 conceptual soundness | Data audit, default definition, data limits, exclusions | Here: 1, 2, 12, 13 |
| 03 validation reports | Realised defaults and losses to test against | Here: 2, 6, 8 |
| 04 monitoring | Baseline distributions of each driver for stability checks | Here: 12 |

Gap that Module 2 cannot fill: unemployment by state. Only national unemployment is loaded
(Module 1). The build plan's PIT PD uses national unemployment and state house prices, so
nothing breaks, but regional unemployment effects cannot be measured. See M2-14.

## 3. What Module 1 hands over (measured 2026-11-15)

- `loan_monthly_view`: 3,314,483,004 monthly rows, 104 acquisition quarters (2000Q1 to
  2025Q4), data to December 2025. Reads Parquet; one full pass takes about 3 minutes.
- `loans_table`: 57,597,528 loans, origination fields (latest corrected value, D-017).
- `sampled_loans_table`: 10% subset, 5,759,759 loans, for development runs (`--sample`).
- `field_leakage_table` and `feature_catalogue_table`: field classes and lag rules.
- `macro_economic_mart`, `macro_state_hpi_table`: federal funds rate, national
  unemployment, national and state house prices, LGD discount rates.
- The EDA notebook describes the data using a provisional outcome. Module 2 replaces that
  outcome with the real default definition and goes further; where they differ, Module 2 is
  the reference.

Facts about the data that shape this module:
- Arrears are reported in whole months behind (0, 1, 2, 3, ...), not days. 3 months behind
  means 90 to 119 days past due. Thresholds between whole months cannot be tested.
- Arrears status is unknown (XX) on about 1.1% of monthly rows.
- The modification flag stays Y once set, with rare exceptions (in 2005Q1: 10,549 loans
  ever Y; 59 later show N). A modification is the month the flag first turns from N to Y.
- Exit codes: 01 paid off, 02 third-party sale, 03 short sale, 06 repurchased,
  09 deed-in-lieu or REO, 15 non-performing note sale, 16 reperforming note sale,
  96 removal. Filled only in the exit month.
- Losses are reported once, at the end of the workout: costs, proceeds and write-off. There
  are no cash flows month by month.
- `loan_age` is blank on exit rows; months on book are counted from the first payment date.
- Current balance is masked in a loan's early months (about the first six) and is zero in
  the exit month; `upb_at_removal` holds the exit balance.
- Principal paid in the month (`total_principal`) is filled on only about 31% of rows.
- Delinquent accrued interest is blank for single-family loans.
- All loans are fixed rate (one amortisation type). There is no rate-reset risk to study.
- Credit score, DTI and income are known only at origination. There is no updated score.
- There is no market mortgage rate series. The rate on new loans in the data each month is
  used as the market rate (for rate incentive and prepayment).
- House prices are by state, not by metropolitan area.
- Payment deferral and forbearance fields exist from about 2020 (COVID).
- Loans can be acquired years after origination (2005Q1 holds loans from 1999).

## 4. Execution sequence

Each script: design section signed off, then builder spec, build, known-answer tests,
review of any default, formula or threshold logic, run on the 10% subset, then the full run.

Script granularity (M2-15): one script, one question. Modular scripts are preferred over a
few large ones even when that means more passes. Passes are reduced by reading purpose
marts - tables already filtered and shaped for a script's job - instead of re-scanning the
raw monthly view; a script writes one main mart, and later scripts read marts rather than
raw data wherever a mart exists.

0. **Design doc** `design\module-2-design.md` (working folder), reviewed by readers with no
   earlier context. Copied to `docs\module_2\` on sign-off (D-014). The README, skeleton
   files and build plan are updated to the new file list only after sign-off.
   - Source check first: Article 178(1)(b), 178(2)(d), 178(3)(d), 178(5)(a), 178(5A);
     data rules for PD (at least 5 years for retail, Article 180(2)(e)); Article 124D
     (property value updated downwards). Values go into `regulatory_parameters.py`.
   - New entries in `docs\departures_from_uk_rules.md`: whole months behind instead of days
     past due; no past-due amount, so materiality is met by any missed payment; the
     modification flag as the only restructuring signal; US foreclosure in place of UK
     possession; state house prices for property values; UK limits applied to longer US
     COVID forbearance; estimated unpaid interest.
   - Data checks before the design is final: plan codes in `borrower_assistance_plan`;
     whether months behind rise during forbearance; whether a payment deferral resets them
     and sets the modification flag.

### Stage A. Foundations

1. **01_data_audit.py**
   - Count roll-forward by month: loans open last month + new loans - exits = loans open
     this month. Must tie exactly.
   - Balance roll-forward by month: opening balance + new loans - scheduled principal -
     part prepayments - payoffs (01) - credit exits (02, 03, 09, 15) - other exits
     (06, 16, 96) + balance added on modification - principal forgiven - written off =
     closing balance. Unexplained amount shown, not assumed zero. Masked-balance months on
     their own line.
   - Loan continuity: no missing month between a loan's first and last row; every loan that
     stops reporting before December 2025 has an exit code.
   - Output: `balance_rollforward_mart` (one row per month), waterfall chart, pass or fail.
   - Plausibility and outliers live in the separate modular script `01b_data_plausibility.py`
     (DRAFT, section 8.1), not in this script.

2. **02_default_engine.py** (M2-2 to M2-6)
   - Trigger months found in SQL; probation state machine in Python for loans that ever
     trigger. COVID treatment as in M2-4.
   - Output: `default_events_mart`, one row per default event: loan, default month,
     trigger, balance at default, months behind at default, probation months, cure month or
     end reason (still in default, credit exit, other exit, end of data), re-default number.
     Whether a loan is in default or in probation in any month is read from the event.
   - Cure rates by months behind (1 to 6): own recovery, cured through modification or
     deferral, paid off. This supports the 90-day rule; it does not set it.
   - Known-answer tests: the 6 hand-made loans from plan correction 8, plus modification
     after default, modification while performing, credit exit while in default, XX months,
     COVID forbearance, a modification flag that turns back to N.
   - Then: the EDA's `build_loan_outcome()` reads `default_events_mart`; notebook rerun.

### Stage B. How loans and values move

3. **03_roll_rates.py**
   - States: Current, 1 month behind, 2 months behind, In default (from the engine,
     including probation), Paid off, Credit exit, Other exit. Unknown (XX) rows left out and
     counted. 3 months behind is default, so no separate "90 days" state.
   - Monthly transition matrices by count and by balance, by era.
   - Projection over 6, 12, 24 and 36 months, stated as assuming the monthly rates stay
     the same. Expected months to default or exit from each arrears state.
   - 30-days evidence for IFRS 9: of loans first 1 month behind, the share that default
     within 12 months and over their life, against loans never behind; same for 2 months.
   - Emergence period and the 60/90/120-day threshold sensitivity live in the separate
     modular script `03b_emergence_and_thresholds.py` (DRAFT, section 8.1), not here.

4. **04_vintage_curves.py** (M2-7, M2-8)
   - Cumulative default rate by months on book for each origination quarter (first default
     event only).
   - Monthly default and prepayment rates by months on book for loans still performing,
     by segment and era (the base of the IFRS 9 lifetime PD curve).
   - Competing-risk curves (Aalen-Johansen): default and prepayment as competing first
     exits; repurchase, reperforming note sale, removal and end of data as censored.
   - SMM and CPR by month, era and segment; expected life of a loan; prepayment speed
     against rate incentive (note rate minus the rate on new loans that month).
   - Check: on loans with no censoring, the curve equals the simple share.

5. **05_current_ltv.py** (M2-10)
   - Property value at origination = original balance / original LTV, moved by the state
     house price index to each quarter-end and to the default and sale dates.
   - Two current LTVs: indexed (up and down), and downward-only (value never above the
     origination value, Article 124D, wording to be checked).
   - Book by current LTV band over time; share in negative equity; how far current LTV
     moved from original LTV by era and state.
   - Peak-to-trough house price fall by state and nationally, with dates; against the 25%
     minimum and 40% reference in the PRA's mortgage LGD rules.

6. **06_default_rate_history.py** (M2-9, M2-12, M2-13)
   - 12-month default rate at each month-end, by count and by balance, for the whole book
     and by era, segment and state.
   - Long-run average default rate over the full history, and with and without the crisis
     years. Which years count as the downturn, and why.
   - Years of data per segment, against the 5-year minimum.
   - Default rate by months on book against by calendar time, to separate loan age from
     the economy.
   - Correlation implied by the yearly default rates (one-factor model), shown beside the
     fixed 0.15 used for capital. A check only.
   - `book_snapshot` (Parquet): every open loan at every December, 2000 to 2025, including
     loans in default. Measured: 279,768,672 rows. Columns: balance (blank early balances
     estimated from the repayment schedule and flagged), note rate, remaining term,
     occupancy, units, segment, era, both current LTVs (from script 5), months behind,
     default and probation status (from script 2), forbearance plan, the 12-month outcome
     (blank for December 2025), exclusion reason and an out-of-time flag.
   - One table serves two uses: Module 3 builds its PD samples from the performing rows;
     Modules 5, 6 and 7 take the book on any December as their starting book.
   - Excluded-population profile lives in the separate modular script
     `06b_sample_population.py` (DRAFT, section 8.1), not here.

### Stage C. Risk drivers

7. **07_risk_drivers.py**
   - Origination features (from `feature_catalogue_table`): credit score, original LTV,
     DTI, occupancy, purpose, property type, units, channel, first-time buyer, number of
     borrowers, mortgage insurance, state, loan size, note rate against the rate on new
     loans that month.
   - Behaviour features, each lagged one month: worst arrears in the last 6 and 12 months,
     months since last arrears, ever modified, current LTV, share of balance paid down,
     months on book, rate incentive.
   - For each: default rate by band, rank ordering, information value, and stability of
     both across eras. Pairs that move together.
   - Candidate segments (owner-occupied against investor, first-time buyer, purchase
     against refinance, high LTV): do they differ enough in level and drivers to need
     separate models?
   - Descriptive only. No model is fitted here.

7b. **07b_segmentation.py** (DRAFT, section 8)
   - Formal split tests for each candidate segment (owner-occupied vs investor, purchase vs
     refinance, first-time buyer, high LTV): KS, Chi-square and information-divergence tests.
   - Interaction detection: multi-way risk pockets (e.g. high LTV x low credit score x
     investor x state) found from exploratory trees (CHAID/CART), descriptive only.
   - Informative missingness: whether blank DTI or credit score is itself predictive.
   - Segment x year data-sufficiency grid against the 5-year minimum.
   - Output: `segmentation_mart`. No model is fitted.

### Stage D. After default

8. **08_default_outcomes.py** (M2-11)
   - For each default event: how it ended (cured, cured after modification, paid off,
     credit exit, other exit, unresolved) and how long it took. Share curing without loss.
   - For credit exits: balance at default, unpaid interest (estimated), each cost type,
     sale and other proceeds, mortgage insurance, write-off, net loss and loss rate; time
     from default to foreclosure and to sale; by era, state, LTV at default and exit type.
   - Observed forced-sale discount: net sale proceeds against indexed property value at the
     sale date.
   - Loss rate against current LTV at default (how sharply it rises) and against the house
     price change from default to sale.
   - Loss on cures through modification: principal forgiven and balance made interest-free.
   - Balance at default against balance 6 and 12 months earlier.
   - `loss_development_mart`: losses and recoveries by default year and months since
     default, and the open (unresolved) balance, for a development triangle in Module 4.

9. **09_forbearance.py**
   - Modifications, payment deferrals and forbearance plans by month: loans and balance.
   - Arrears before and after; re-default within 12 and 24 months of a modification or
     deferral.
   - Forborne loans that were performing against those in default when forborne.

### Stage E. Book and economy

10. **10_economy_links.py**
    - `portfolio_rates_quarterly_mart`: quarterly default, cure, prepayment and loss rates,
      for the whole book and by segment, joined to the economic series with their
      publication lags (from Module 1).
    - Links with leads and lags of 0 to 24 months (charts and correlations), nationally and
      by state for house prices.
    - Past downturn severity: unemployment rise and house price fall, peak to trough,
      nationally and by state, with dates.
    - Prepayment against interest rates.
    - Descriptive. The stress models are built in Module 7.

10b. **10b_cycle_and_benchmarks.py** (DRAFT, section 8)
   - Downturn duration and recovery speed, not just peak-to-trough severity: how long rates
     stayed elevated and how fast they normalised after 2008 and 2020.
   - Seasonality: month-of-year effects on default, prepayment and cure.
   - Age-period-cohort decomposition of the 12-month default rate (loan age vs calendar
     time vs vintage), descriptive.
   - External benchmarking: observed default, prepayment and loss rates against industry
     series (MBA delinquency survey, FHFA house prices, FRED macro).
   - Output: `cycle_mart`. No model is fitted.

11. **11_portfolio_mix.py**
    - Book over time: loans, balance, weighted average credit score, LTV, DTI and note
      rate; mix by occupancy, purpose, LTV band, state and seller.
    - Balance and default rate grids: credit score by LTV, DTI by occupancy, vintage by state.
    - Book by the capital rule's LTV bands (55% split for owner-occupied; investor bands),
      by occupancy and by units.
    - Concentration index (HHI) by state, metropolitan area and seller, by year.
    - Early payment default: 1 or more months behind within the first 3 months on book
      (loans first seen after month 3 left out), by vintage and seller.
    - Arrears bounce: loans that go Current to 1 month behind and back twice or more in any
      12 months.
    - Today's book (December 2025) and the pre-crisis book (December 2006 and 2007) read
      from `book_snapshot` and described side by side.

### Stage F. Fitness of the data

12. **12_representativeness.py**
    - Today's book (December 2025) against the history used for models: distribution of
      each driver, with a stability index; where today's book has no history behind it.
    - Data limits, each with its size (loans, rows, balance): unknown arrears, masked early
      balances, blank DTI and credit score, restated origination fields, fields that start
      late (payment history, deferral), estimated unpaid interest. Feeds the margin of
      conservatism (category A).
    - Changes in lending and servicing, with dates and size: the 2008-2009 tightening,
      high-balance loans, high-LTV refinance programmes, servicer transfers, COVID. Feeds
      the margin of conservatism (category B).
    - Baseline driver distributions for Module 8 monitoring.
   - Survivorship and left-truncation live in the separate modular script
     `12b_survivorship.py` (DRAFT, section 8.1), not here.

### Stage G. Handover

13. **13_portfolio_findings.md**
    - Written from run results only: what the book is, how it behaves, which features drive
      risk, what happens after default, how it moves with the economy, and the data limits.
    - Section 2 of this plan, filled with numbers and table names: what each of Modules 3
      to 8 takes from Module 2.

14. **Module close**
    - `docs\module_2\` holds the plan, the signed-off design and the findings.
    - `02_portfolio_analytics\README.md` updated with measured numbers.
    - Git branch `phase-2`: commands given to the user to run.

## 5. Decisions

Decided by Devesh, 2026-11-16 (D-030):
- M2-1: all 104 quarters, results shown by era: 2000-2006 build-up, 2007-2010 crisis,
  2011-2019 recovery, 2020-2021 COVID, 2022-2025 recent.
- M2-3 triggers: (a) 3 or more months behind (Article 178(1)(b)); (b) distressed
  restructuring, the month the modification flag turns N to Y (Article 178(3)(d));
  (c) credit exit, codes 02, 03, 09, 15. Unknown arrears (XX) neither triggers nor counts as
  a clean month.
- M2-5 probation: 3 clean months after an arrears default (178(5)(a)); 12 after a distressed
  restructuring (178(5A)). Any month behind restarts the count. The loan stays in default
  during probation.
- M2-6 re-default: a new default after probation ends is a new event; a slip during
  probation is the same event.
- All rule wording is source-checked before the design is signed off.
- M2-4: follow how UK firms treated COVID payment deferrals under PRA and FCA guidance.
  Source check 2026-11-16 (sources read in full: PRA Dear CEO letters of 26 March 2020 and
  4 June 2020; FCA Payment Deferral Guidance and Tailored Support Guidance, November 2020):
  - A COVID payment deferral under the FCA guidance did not start the days-past-due count
    and did not create arrears (PRA 26 March 2020, Annex para 9; 4 June 2020, Annex para 33).
  - It was not automatically unlikely to pay or a distressed restructuring, but firms had
    to check whether tailored support was one (PRA 4 June 2020, summary and Annex para 38).
  - Payments missed outside the deferral, or on the revised schedule after it, were
    normal arrears (PRA 4 June 2020, Annex para 9; FCA Tailored Support Guidance 3.11).
  - Limits: new deferrals until 31 March 2021, payments up to 31 July 2021, at most 6
    monthly payments per loan (FCA Payment Deferral Guidance 1.7, 1.8, 2.3).
  What we do with the Fannie Mae data:
  - Months behind that build up while a loan is in a forbearance plan that started between
    March 2020 and March 2021 do not count: months behind are held at the level the month
    before the plan started. Arrears from before the plan still count.
  - Relief covers at most 6 months per loan and no month after July 2021. After that, or
    once the plan ends, months behind count as reported.
  - A COVID payment deferral is not a distressed restructuring by itself. A modification
    (flag N to Y) is, as for any other period.
  - The as-reported treatment is shown side by side.
  - Not found: a PRA paragraph on whether arrears from before the deferral kept counting.
    We keep counting them (the cautious reading of FCA guidance).
- Accepted as recommended, to be walked through in detail with Devesh before sign-off:
  - M2-2: plain Python state machine, one loan at a time, only loans that ever trigger;
    triggers found in DuckDB; batches by acquisition quarter.
  - M2-7: vintage = origination quarter; months on book from the first payment date;
    late-acquired loans enter at their first observed month.
  - M2-8: scheduled principal worked out from note rate, remaining term and balance;
    anything above it is a part prepayment.
  - M2-9: 12-month default rate on performing loans (not in default or probation) at each
    month-end; bad if a new default event starts in the next 12 months; non-credit exits
    inside the 12 months shown separately, not counted as good; yearly figure is the
    average of the 12 month-ends.
  - M2-10: value at origination = original balance / original LTV, moved by the state
    house price index; current LTV = current balance / current value.
  - M2-11: default events still open at December 2025 are unresolved, kept out of loss
    rates, counts and balances shown.

Decided by Devesh, 2026-11-16, after checking Modules 3 to 8 (D-030):
- M2-12: one table, `book_snapshot`, with every open loan at every December 2000 to 2025
  (279,768,672 rows, measured). December 2025 is today's book for IFRS 9 and capital;
  December 2006 or 2007 is the pre-crisis book for the stress back-test (chosen in
  Module 7). Opening and closing books for the IFRS 9 movement waterfall come from the
  same table. Known limits: before 2019 balances are blank in a loan's first months
  (669,319 loans in December 2007), estimated and flagged; the data holds only loans
  acquired from 2000, so the early books are younger than a real lender's book.
- M2-13: the PD outcome rows are the performing rows of `book_snapshot` at each December
  2000 to 2024 (264,339,598 open loans before taking out loans in default). The 12-month
  windows do not overlap. Out-of-time flag on December 2022 to December 2024; Module 3 may
  choose another split. The portfolio default rate in script 6 is still worked out at
  every month-end.
- M2-14: no state unemployment for now. National unemployment only; the gap is recorded in
  the findings and the data limits. Revisit as a Module 1 change only if script 10 shows
  states still differ a lot after allowing for house prices. Reason: the stress scenario
  gives one national unemployment path, the build plan's models use national
  unemployment, and adding it would reopen Module 1.
- M2-15: one script, one question - keep many modular scripts instead of a few large ones,
  even when that means more passes. Actively cut passes in other ways, the first being
  purpose marts: a script reads tables already filtered and shaped for its job (for example
  a slim monthly mart with only its columns and rows) instead of re-scanning the raw monthly
  view, and writes one main mart that later scripts read instead of raw data.

## 6. How Module 2 is checked

- Every script prints a short summary: row counts, control totals, pass or fail.
- Every mart has a stated unique key, checked by query.
- Ties to Module 1: loans and balances in each mart match `loans_table` and
  `loaded_quarters_table` totals.
- Ties between scripts: defaults in roll rates, vintage curves, default rate history,
  default outcomes and the quarterly rates all come from `default_events_mart` and agree in
  count. Each December in `book_snapshot` ties to the balance roll-forward for that month.
- Known-answer tests on small made-up tables for every formula (state machine, roll
  matrix, CIF, SMM and CPR, 12-month default rate, current LTV both ways, loss rate,
  forced-sale discount, development triangle, implied correlation, HHI, stability index).
- Subset against full: headline rates on the 10% subset sit close to the full run.
- No result is written as fact before it is run.

## 7. Risks

- Run time: many full passes over 3.3 billion rows. Modular scripts are kept (M2-15), so
  passes are reduced with purpose marts: each script reads a table already filtered to its
  purpose, and slim tables are built per purpose rather than as one monolithic slim table.
  Measure each script on 2005Q1 and on the subset first.
- Memory: 16 GB. Batch by acquisition quarter; DuckDB spill to `.scratch\`.
- Size: 18 scripts and a findings document. Stage A comes first; stages B to F can be built
  in any order once A is done, except that 6 needs 5, 7 needs 5 and 6, 7b needs 7, 10b
  needs 6 and 10, and 12 needs 7 and 11. The DRAFT scripts read existing marts, not raw
  monthly data: 01b reads 01's mart, 03b reads `default_events_mart`, 06b reads
  `book_snapshot`, and 12b reads the loan and vintage tables.
- Masked early balances limit the balance roll-forward in loans' first months.
- COVID-era reporting may bend 2020-2021 rates; shown as its own era.
- Losses are reported only at the end of a workout, so the loss timing in Module 4 is
  approximate (one cash flow at the sale date).

## 8. Proposed additions (DRAFT, not signed off)

Added 2026-11-24 at Devesh's request. Everything here is descriptive: it measures and
describes the book and its history so Modules 3-8 can build models. No model is fitted in
Module 2, and no new pass over the raw monthly data is added where an existing mart already
holds the fact.

Purpose mart (M2-15): a table a producer script builds once - filtered to its columns and
rows and shaped for one purpose - which later scripts read instead of re-scanning the raw
monthly view. Each script writes one main mart; each reader consumes marts, not raw data.

### 8.1 Separate modular scripts (DRAFT)

Kept as their own scripts (one script, one question, per M2-15), separate from the larger
ones. Each reads a purpose mart - a table already filtered and shaped for it - so the extra
scripts do not each re-scan the raw monthly view.

- `01b_data_plausibility.py` -> `data_plausibility_mart`: cross-field checks (LTV over 100%,
  DTI and note-rate extremes, negative balances, impossible arrears sequences, re-aging),
  field fill-rate trends, and duplicate or servicer-overlap records.
- `03b_emergence_and_thresholds.py` -> `emergence_mart`: months from first missed payment to
  default flag, and the 60/90/120-day default-rate sensitivity.
- `06b_sample_population.py` -> `sample_population_mart`: excluded-population profile (who
  is left out of the PD sample and how they differ), reading `book_snapshot`.
- `12b_survivorship.py` -> `survivorship_mart`: survivorship and left-truncation (the 2000
  panel start and late-acquired loans), reading the loan and vintage tables.

### 8.2 Two new stages (7b, 10b)

Together with the four scripts in 8.1, section 8 adds six DRAFT scripts in total.

- `07b_segmentation.py` -> `segmentation_mart`: formal segment split tests (KS, Chi-square,
  information divergence), interaction pockets from exploratory trees, informative
  missingness, and a segment x year sufficiency grid. Descriptive only.
- `10b_cycle_and_benchmarks.py` -> `cycle_mart`: downturn duration and recovery speed,
  seasonality, age-period-cohort decomposition, and external benchmarking. Descriptive only.

### 8.3 Regulatory analytical items: provisions (IFRS 9) and capital

Analytical evidence the UK rules require before modelling, measured here; the model itself
is built later. None of these fit a model.

#### Provisions - IFRS 9 (IASB IFRS 9; PRA expectations)

- 30-day backstop population and rebuttal evidence: size of the 1-month-behind population
  and how often it goes on to default (stage 3), for or against rebutting the 30-days-past-
  due presumption (IFRS 9.B5.5.9).
- SICR indicators: which observable changes (arrears step-up, forbearance, missed payments,
  modification) indicate significant credit deterioration, measured on history.
- Low credit risk exemption: how much of the book could qualify as low credit risk.
- Modification and derecognition: how many modifications are substantial (derecognised) and
  the resulting gain or loss, so stage movement is measured, not assumed.
- Stage population and transition analysis: share in Stage 1, 2 and 3 over time, and the
  movement-waterfall inputs (new lending, repayments, prepayments, write-offs) from stage 1.
- Cure and re-default after cure (stages 2 and 9): the empirical response to a cure, which
  sets the SICR and staging evidence.
- Downturn severity for forward-looking scenarios (stage 10b): how bad and how long, so the
  scenarios are grounded in the book's own history.

#### Capital - CRR / PRA (IRB and standardised)

- Definition of default (CRR Art 178): the trigger, materiality and 90-days-past-due
  thresholds (stages 2 and 3), one definition shared by capital and IFRS 9, with the
  60/90/120 sensitivity showing the choice is measured.
- Long-run average and data sufficiency (CRR Art 180): 5 years of data per segment and
  representativeness of the range of expected conditions (stages 6, 7b and 12).
- Downturn period identification (CRR Art 181, for downturn PD and LGD): severity plus
  duration and recovery speed (stage 10b).
- Property value updated downward only (CRR Art 124D) and negative equity (stage 5).
- Exposure classification: retail exposure class eligibility, secured-by-residential-
  property eligibility, and the LTV bands that drive standardised risk weights (stages 5,
  11), so the risk-weight mapping has measured inputs.
- Margin of conservatism (CRR Art 179; EBA GL on PD/LGD estimation): data limits and changes
  in lending sized into categories A and B (stage 12).
- Concentration and large exposures (CRR Art 395): HHI and single-name concentration
  (stage 11), to check the book against limits before capital is computed.
