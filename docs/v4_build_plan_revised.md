# V4 Credit Risk Platform — Full Build Plan (Revised)

> **Repo:** `E:\Repos\V4_bank-credit-risk-platform`
> **Dataset:** Fannie Mae Single-Family Loan Performance Data (all 104 quarterly acquisition cohorts, 2000Q1–2025Q4, followed longitudinally through resolution — includes the 2007–2009 credit downturn)
> **Principle:** Minimal scaffolding, uncompromising domain depth. DuckDB as the single source of truth.
> The loans are US conforming residential mortgages from Fannie Mae, assessed under UK rules.
> **Output conventions:** All quantitative outputs and tables present plain numeric amounts with no currency symbols and no country names; original regional identifiers from the dataset are preserved.
> **Intended audience:** Chief Risk Officer reviewing an institutional-grade, auditable, and mathematically rigorous credit risk platform.

---

## Repository Structure

```
V4_bank-credit-risk-platform/
│
├── residential_mortgage/              ← Portfolio root (all conforming residential mortgage work)
│   │
│   ├── 00_data/
│   │   ├── raw/                       ← Fannie Mae raw zip, quarterly Parquet lake, and macro CSVs (git-ignored)
│   │   ├── processed/                 ← mortgages.duckdb master database (git-ignored)
│   │   ├── convert_raw_to_parquet.py  ← Extracts CSV from zip and converts to compressed Parquet
│   │   ├── build_base_tables.py       ← Builds loans_table, monthly views, sample; auto-writes data_log.md
│   │   ├── build_macro_tables.py      ← Ingests FEDFUNDS, UNRATE, and HPI into macro tables and mart
│   │   ├── data_log.md                ← Auto-generated. Latest ingestion at top; full history below.
│   │   └── field_map.py               ← Fannie Mae 113-field layout → clean column names + dtypes
│   │
│   ├── 01_data_foundation/            ← Runs ONCE before any analytics module
│   │   ├── 01_ingestion_design.md     ← Single-file table design, sampling rules, schema decisions
│   │   ├── 02_eda.ipynb               ← Distributions, missingness, impossible values, correlations
│   │   ├── 03_leakage_audit.py        ← Target leakage quarantine and approved feature register
│   │   └── 04_feature_catalogue.py    ← Final approved variable list with lag rules and restrictions
│   │
│   ├── 02_portfolio_analytics/
│   │   ├── 01_data_audit.py           ← Stock-and-flow balance roll-forward + tie-outs
│   │   ├── 02_default_engine.py       ← Whole-month DPD analysis → business default + probation state machine
│   │   ├── 03_roll_rates.py           ← Multi-state Markov transition matrix + matrix exponentiation
│   │   ├── 04_vintage_curves.py       ← MOB-aligned CDR, CPR/SMM, Aalen-Johansen CIF competing risks
│   │   └── 05_concentrations.py       ← HHI, bivariate risk grids, EPD-3, delinquency bounce
│   │
│   ├── 03_rating_and_pd/
│   │   ├── 01_application_scorecard.py   ← WoE/IV, logistic, origination variables only (anchor: 50:1 at 650)
│   │   ├── 02_behavioural_scorecard.py   ← WoE/IV, logistic, lagged performance + balance variables
│   │   ├── 03_pit_pd.py                  ← Point-in-time PD model (standalone, satellite macro overlay)
│   │   ├── 04_ttc_pd.py                  ← Through-the-cycle PD model (standalone, LRADR downturn calibration)
│   │   ├── 05_pd_calibration.py          ← Platt scaling, central tendency, SS4/24 cyclicality measurement
│   │   ├── 06_master_rating_scale.py     ← 15 numbered grades → central PD → migration matrix (no letter ratings)
│   │   └── 07_model_validation.py        ← Exact binomial test (95%/99%), Brier, H-L, PSI, MoC, Pluto-Tasche
│   │
│   ├── 04_lgd_ead/
│   │   ├── 01_workout_lgd.py          ← Recovery cash flows, EFFR+500bps discount floored at 9%, hurdle model
│   │   ├── 02_component_lgd.py        ← SS4/24 Chapter 15 component approach (cure × severity × costs), 5% floor
│   │   └── 03_expected_loss.py        ← EL = PD × LGD × EAD waterfall + EL vs ECL bridge
│   │
│   ├── 05_ifrs9_ecl/
│   │   ├── 01_staging_sicr.py         ← Stage 1/2/3, dual SICR tests, 30 DPD backstop, probation tracking
│   │   ├── 02_pd_term_structure.py    ← Lifetime PD curve, Aalen-Johansen CIF competing risks, behavioural life
│   │   ├── 03_lifetime_lgd_ead.py     ← PIT scenario-sensitive LGD, amortising EAD profile
│   │   ├── 04_scenario_ecl.py         ← Multi-scenario ECL, probability weights, non-linearity quantification
│   │   └── 05_movement_waterfall.py   ← Monthly ECL bridge: new lending, stage transfers, remeasurements
│   │
│   ├── 06_basel_capital/
│   │   ├── 01_standardised_rwa.py     ← Article 124F/124L loan-splitting, Article 124G Table 6B, HPI valuation
│   │   ├── 02_airb_vasicek.py         ← ASRF derivation → retail AIRB (no maturity factor), output floor
│   │   └── 03_economic_capital.py     ← Closed-form Vasicek EC = VaR(99.9%) - EL, Euler allocation, RAROC
│   │
│   ├── 07_stress_testing/
│   │   ├── 01_satellite_models.py     ← ARDL cointegration, corrected Vasicek state inversion z*, 1D root search
│   │   ├── 02_stress_projection.py    ← 5-year capital path (BoE 2025 BCST), balance sheet, 6.2% hurdle
│   │   └── 03_reverse_stress.py       ← Mahalanobis distance minimization to CET1 < 4.5% breaking point
│   │
│   ├── 08_model_risk_mgmt/            ← PRA SS1/23 governance layer + SR 11-7 / SR 26-2 reference
│   │   ├── 01_model_inventory.py      ← Automated model register from module outputs
│   │   ├── 02_conceptual_soundness.md ← Per-model: assumptions, limitations, known weaknesses
│   │   ├── 03_validation_reports/     ← Independent validation reports aligned with SS1/23 Principle 4
│   │   └── 04_monitoring_dashboard.py ← Ongoing performance monitoring, drift detection, traffic lights
│   │
│   ├── regulatory_parameters.py       ← Single source of truth for all regulatory thresholds and parameters
│   └── how_to_run.md                  ← Step-by-step execution instructions
│
├── notebooks/                         ← Walkthrough notebooks demonstrating core findings
├── .gitignore
└── README.md
```

> **Conforming terminology:** Conforming mortgages meet established government-sponsored purchase criteria regarding loan size and documentation standards. The top-level folder is named `residential_mortgage` to maintain structural neutrality across portfolios.

---

## Module 1: `01_data_foundation`

> **Purpose:** Establishes the single source of truth in DuckDB. Ingests raw loan files, validates structural control totals, executes comprehensive exploratory data analysis, isolates potential target leakage, and freezes an approved feature catalogue before any quantitative model is constructed.

---

### Data Ingestion Strategy

**Fannie Mae File Layout:**
Fannie Mae Single-Family Loan Performance data uses a consolidated 113-field pipe-delimited file layout per acquisition cohort. This single unified file structure incorporates both origination attributes (credit score, original LTV, original DTI, original interest rate, loan term, occupancy type, property type, loan purpose) and dynamic monthly loan records (current UPB, delinquency status, modification flags, zero-balance disposition codes). `field_map.py` establishes the canonical 113-field position mapping and data types.

**Cohort Scope & Sampling Specification:**
- **Acquisition cohorts:** 2000Q1 through 2025Q4 (all 104 quarterly cohorts). The 2000–2008 window within this span supplies the credit expansion of 2001–2006 and the severe 2007–2009 housing downturn required for downturn calibration under PRA SS4/24; the later quarters extend the panel for point-in-time and stability analysis. All 104 quarters are stored in full.
- **Sampling method:** A 10% seeded random sample of unique loans (`sampled_loans_table`, seed 42, 1 thread) is generated for development only via the `--sample` flag. Full-population runs process all loans.
- **Data volume and disk footprint:**
  - *Full population (measured):* All 104 quarters loaded — **57,597,528 unique loans** and ~**3.31 billion** monthly rows, with **$12.63T** total UPB reconciled to the cent. Compressed Parquet lake ~26.04 GB; DuckDB ~2.06 GB; full load ~4.74h.
  - *Base tables in DuckDB:* `loans_table` stores origination dimensions for each unique loan (57,597,528 rows). `loan_monthly_view` queries the compressed Parquet files directly without duplicating monthly rows in DuckDB storage.

**Master Schema in `mortgages.duckdb` (Parquet Architecture per D-018):**
All quarters are accessed via consolidated entity tables and views, avoiding memory exhaustion and duplicate storage while preventing brittle `UNION ALL` patterns. Suffixes explicitly denote the object kind (`*_table`, `*_view`, `*_mart`):

```
DuckDB Master Schema
────────────────────
loans_table                 ← Materialized Table (unique key, checked by query: loan_id). Latest corrected values.
loan_monthly_view           ← View reading Parquet files directly (unique key, checked by query: loan_id, reporting_period).
sampled_loans_table         ← Seeded 10% random sample table for development (unique key, checked by query: loan_id; seed: 42, 1 thread).
default_events_mart         ← Generated by 02_default_engine.py (unique key, checked by query: loan_id, default_month).
loaded_quarters_table       ← Audit ledger tracking loaded quarters, raw lines, UPB reconciliation, timings.
origination_restatements_table ← Tracks mid-life restatements per origination column.
macro_monthly_table         ← Materialized Table (unique key, checked by query: period). National monthly time series (2000-01 to present).
macro_state_hpi_table       ← Materialized Table (unique key, checked by query: state, quarter_date). Quarterly state-level HPI across 51 states/DC.
macro_monthly_view          ← View over national monthly macro series.
macro_economic_mart         ← Materialized Mart (unique key, checked by query: period). Analytical mart with deltas and regulatory LGD discount rates.
```

**Three-Stage Ingestion Pipeline:**
1. **Stage 1: Raw to Parquet (`convert_raw_to_parquet.py`):**
   Converts 113-field raw CSVs quarter-by-quarter into compressed columnar Parquet (`residential_mortgage/00_data/raw/parquet/YYYYQn.parquet`) via DuckDB ZSTD streaming in ~3.5 min/quarter (~160 MB, 39x compression):
   ```bash
   python residential_mortgage/00_data/convert_raw_to_parquet.py 2005Q1
   python residential_mortgage/00_data/convert_raw_to_parquet.py 2000Q1 2008Q4
   python residential_mortgage/00_data/convert_raw_to_parquet.py all
   ```
2. **Stage 2: DuckDB Base Tables & Views (`build_base_tables.py`):**
   Reads the Parquet files, materializes `loans_table` (latest corrected value per D-017), creates `loan_monthly_view` over loaded quarters, draws `sampled_loans_table`, runs 8 structural integrity checks, and logs to `data_log.md`:
   ```bash
   python residential_mortgage/00_data/build_base_tables.py 2005Q1
   python residential_mortgage/00_data/build_base_tables.py all
   ```
3. **Stage 3: Macroeconomic Tables & Marts (`build_macro_tables.py`):**
   Downloads or reads raw macroeconomic CSVs (FEDFUNDS, UNRATE, FHFA HPI Master), materializes `macro_monthly_table`, `macro_state_hpi_table`, creates `macro_monthly_view`, builds `macro_economic_mart` with 1m/12m deltas and PRA SS4/24 regulatory LGD discount rates (EFFR + 5.0% long-run, 9.0% downturn floor), and validates 6 integrity checks inside an atomic transaction:
   ```bash
   python residential_mortgage/00_data/build_macro_tables.py
   ```

**Data Cleanliness and Quirks:**
- **Delinquency indicator:** Casts integer months delinquent to `INT`. Non-numeric status indicators are cast to `NULL` and flagged with `is_dpd_unknown = TRUE`.
- **Debt-to-Income (DTI):** Tracked across the historical panel with varying disclosure thresholds and blank rates across vintages, flagged and audited during exploratory analysis.
- **Disposition codes:** Maps disposition codes (prepayment, third-party sale, short sale, deed-in-lieu, note sale) into a standardized `exit_reason` categorical column.

---

### `02_eda.ipynb` — Exploratory Data Analysis

- **Univariate distributions:** Percentiles, skewness, and extreme values for all continuous features (credit score, original LTV, DTI, note rate, loan term, original balance). Flags anomalous records (e.g. credit score < 300, original LTV > 150%, DTI > 100%).
- **Missingness audit:** Missing value percentage across fields and acquisition cohorts. Documents variables with historical reporting changes.
- **Bivariate correlations:** Computes Pearson and Spearman correlation matrices across origination variables. Flags variable pairs with absolute correlation $|r| > 0.70$ for multicollinearity screening.
- **Temporal drift:** Tracks median underwriting metrics (credit score, LTV, DTI) across acquisition cohorts to identify underwriting regime shifts.
- **Volume reconciliations:** Validates monthly active loan counts and attrition rates across cohorts.

---

### `03_leakage_audit.py` — Target Leakage Quarantine

Target leakage occurs when variables containing post-outcome information or concurrent outcome definitions are improperly included in predictive feature sets.

| Variable | Classification | Restriction Policy |
|:--- |:--- |:--- |
| `modification_flag` | Restructuring indicator | Excluded from application scorecard; lagged ($t-1$) in behavioural scorecard |
| `delinquency_months` | Concurrent outcome definition | Never used concurrently; strictly lagged ($t-1$) for behavioural models |
| `zero_balance_code` | Post-default realization | Quarantined exclusively for LGD recovery analysis; excluded from PD models |
| `servicer_activity` | Post-default servicing | Quarantined from all predictive scorecards |
| `current_upb` | Dynamic exposure | Strictly lagged ($t-1$) when predicting month-$t$ migration |
| `foreclosure_date` | Post-default milestone | Quarantined exclusively for workout LGD analysis |

---

### `04_feature_catalogue.py` — Approved Feature Register

Generates the definitive data dictionary:

| Field | Source | Category | Permitted Use | Lag | Notes |
|:--- |:--- |:--- |:--- |:--- |:--- |
| `credit_score` | Ingestion | Origination | Application scorecard, PD models | None | Impute missing values with vintage median |
| `orig_ltv` | Ingestion | Origination | Application scorecard, LGD, SA RWA | None | Verified against property valuation |
| `dti` | Ingestion | Origination | Application scorecard | None | Screen for vintage-specific missingness |
| `note_rate` | Ingestion | Origination | Application scorecard, Prepayment | None | Contractual interest rate |
| `loan_term` | Ingestion | Origination | Application scorecard, EAD amortisation | None | Contractual maturity in months |
| `current_upb` | Performance | Dynamic | Behavioural scorecard, EAD | $t-1$ | Imputed where initially unpopulated |
| `delinquency_months`| Performance | Dynamic | Behavioural scorecard, Roll rates | $t-1$ | Measured in whole integer months |
| `modification_flag` | Performance | Dynamic | Behavioural scorecard only | $t-1$ | Simplification: primary restructuring flag |

---

## Module 2: `02_portfolio_analytics`

> **Purpose:** Executes portfolio surveillance: stock-and-flow balance reconciliation, empirical derivation of the business default definition, recursive probation tracking under UK rules, Markov roll-rate analysis, and competing-risk vintage curves.

---

### `01_data_audit.py` — Stock-and-Flow Balance Roll-Forward

Every unit of exposure is accounted for each month:
$$\text{UPB}_t = \text{UPB}_{t-1} + \text{Originations}_t + \text{Capitalised Interest}_t - \text{Scheduled Principal}_t - \text{Voluntary Prepayments}_t - \text{Default Exits}_t - \text{Repurchases/Sales}_t$$

- Reconciles closing balances against aggregated monthly loan tracking records.
- Classifies monthly outflows across distinct exit categories.
- Produces waterfall reconciliation charts confirming zero unexplained discrepancy across reporting periods.

---

### `02_default_engine.py` — Business Default Definition & Probation State Machine

**Empirical Derivation of Default:**
The 90-day threshold is derived empirically from loan records. Delinquency is reported in whole months delinquent ($m \in \{0, 1, 2, 3, \dots\}$), corresponding to whole-month days-past-due increments ($m \times 30$).
- Evaluates candidate default thresholds $\theta \in \{30, 60, 90, 120, 150, 180\}$ DPD.
- For each threshold $\theta$, computes the forward cure rate (loans returning to Current) and subsequent loss severity.
- **Empirical finding:** Cure rates decline steeply between 60 DPD (2 months past due) and 90 DPD (3 months past due) and flatten thereafter, confirming 90 DPD as the natural credit impairment boundary.

**Regulatory Mechanics (PRA Rulebook):**
- **Materiality threshold:** Retail residential mortgages have a zero absolute and zero relative threshold under PRA SS3/24 paragraph 3.6. Any non-zero past-due balance initiates the delinquency counter.
- **Unlikely-to-Pay (UTP) triggers:**
  - Distressed restructuring: Tracked via `Modification_Flag == 'Y'` as a simplifying choice.
  - Foreclosure initiation or legal possession proceedings.
  - Short sale, deed-in-lieu, or third-party liquidation agreements.
- **Probation state machine (PRA Rulebook Credit Risk: Internal Ratings Based Approach (CRR) Part, Article 178(5A)):**
  - Loans curing from a pure arrears default require **3 consecutive months** of spotless performance (0 DPD) to return to Performing.
  - Loans curing from a distressed restructuring require **12 consecutive months** of spotless performance (0 DPD) to return to Performing.
  - Throughout the probation window, the loan remains classified in default (In-Default / Default status). Any delinquency event during probation immediately resets the consecutive clean-month counter.

**Verified DuckDB Recursive Probation Query:**
```sql
WITH RECURSIVE state_machine AS (
    -- Base step: first reporting period for each loan
    SELECT 
        loan_id, reporting_period, delinquency_months, modification_flag,
        CASE WHEN delinquency_months >= 3 OR modification_flag = 1 THEN 'Default' ELSE 'Performing' END AS status,
        CASE WHEN delinquency_months >= 3 OR modification_flag = 1 THEN 1 ELSE 0 END AS in_default,
        CASE WHEN modification_flag = 1 THEN 12 WHEN delinquency_months >= 3 THEN 3 ELSE 0 END AS req_probation,
        0 AS clean_streak,
        CASE WHEN delinquency_months >= 3 OR modification_flag = 1 THEN 1 ELSE 0 END AS default_event_id
    FROM loan_monthly WHERE reporting_period = 1

    UNION ALL

    -- Recursive step: evaluate month-by-month transitions
    SELECT 
        r.loan_id, r.reporting_period, r.delinquency_months, r.modification_flag,
        -- Next status:
        CASE 
            WHEN s.in_default = 0 THEN
                CASE WHEN r.delinquency_months >= 3 OR r.modification_flag = 1 THEN 'Default' ELSE 'Performing' END
            ELSE
                CASE WHEN s.clean_streak >= s.req_probation AND r.delinquency_months = 0 AND r.modification_flag = 0 THEN 'Performing' ELSE 'Default' END
        END AS status,
        -- In-default flag:
        CASE 
            WHEN s.in_default = 0 THEN
                CASE WHEN r.delinquency_months >= 3 OR r.modification_flag = 1 THEN 1 ELSE 0 END
            ELSE
                CASE WHEN s.clean_streak >= s.req_probation AND r.delinquency_months = 0 AND r.modification_flag = 0 THEN 0 ELSE 1 END
        END AS in_default,
        -- Required probation horizon:
        CASE 
            WHEN s.in_default = 0 AND (r.delinquency_months >= 3 OR r.modification_flag = 1) THEN
                CASE WHEN r.modification_flag = 1 THEN 12 ELSE 3 END
            WHEN s.in_default = 1 AND r.modification_flag = 1 THEN 12
            ELSE s.req_probation
        END AS req_probation,
        -- Consecutive clean months counter:
        CASE 
            WHEN (s.in_default = 0 AND NOT (r.delinquency_months >= 3 OR r.modification_flag = 1)) 
                 OR (s.in_default = 1 AND s.clean_streak >= s.req_probation AND r.delinquency_months = 0 AND r.modification_flag = 0) THEN 0
            WHEN (s.in_default = 1 OR (r.delinquency_months >= 3 OR r.modification_flag = 1)) 
                 AND r.delinquency_months = 0 AND r.modification_flag = 0 THEN s.clean_streak + 1
            ELSE 0
        END AS clean_streak,
        -- Default event counter:
        CASE 
            WHEN s.in_default = 0 AND (r.delinquency_months >= 3 OR r.modification_flag = 1) THEN s.default_event_id + 1
            ELSE s.default_event_id
        END AS default_event_id
    FROM loan_monthly r
    JOIN state_machine s ON r.loan_id = s.loan_id AND r.reporting_period = s.reporting_period + 1
)
SELECT * FROM state_machine;
```

---

### `03_roll_rates.py` — Multi-State Transition Matrix & Markov Projection

- **State space:** Six discrete states based on whole-month increments: `{Current, 30DPD, 60DPD, 90DPD, Default, Prepaid}`.
- **Empirical transition matrix $P$:** Computes monthly maximum likelihood transition probabilities $p_{ij} = n_{ij} / \sum_k n_{ik}$.
- **Matrix projection:** Projects portfolio state distributions over forward horizons via matrix exponentiation $\pi_k = \pi_0 \cdot P^k$ for $k \in \{6, 12, 24, 36\}$ months.
- **Absorbing Markov analysis:** Derives the fundamental matrix $N = (I - Q)^{-1}$ for transient delinquency states to determine expected months to default or cure.

---

### `04_vintage_curves.py` — Vintage Analysis & Competing Risks

- **Months-on-book (MOB) cumulative default rate:**
  $$\text{CDR}_{c,m} = \frac{\sum_{t=0}^{m} \text{Defaults}_{c,t}}{\text{Originations}_c}$$
- **Voluntary prepayment metrics:** Single Monthly Mortality (SMM) and Conditional Prepayment Rate (CPR):
  $$\text{SMM}_t = \frac{\text{Prepayments}_t}{\text{Opening UPB}_t - \text{Scheduled Principal}_t}, \quad \text{CPR}_t = 1 - (1 - \text{SMM}_t)^{12}$$
- **Competing-risk survival analysis via Aalen-Johansen CIF:**
  Calculates the non-parametric Cumulative Incidence Function (CIF) directly in DuckDB SQL:
  $$\text{CIF}_k(t) = \sum_{t_j \le t} \hat{S}(t_{j-1}) \frac{d_{kj}}{n_j}$$
  where $\hat{S}(t)$ is the overall Kaplan-Meier survival function, $d_{kj}$ is the count of events of cause $k$ (default vs voluntary prepayment), and $n_j$ is the risk set. Prepayment represents the competing terminal event; administrative removals, repurchases, and third-party servicing transfers are treated as right-censored observations; non-performing note sales remain loss outcomes for LGD estimation.

---

### `05_concentrations.py` — Risk Grids & Early Warning Signals

- **Bivariate risk grids:** Cross-tabulates exposure and default rates across key dimensions (LTV $\times$ Credit Score; DTI $\times$ Occupancy; Vintage $\times$ Region).
- **Herfindahl-Hirschman Index (HHI):** Measures concentration across regional property markets:
  $$\text{HHI} = \sum_{r=1}^R s_r^2$$
- **Early Payment Default (EPD-3):** Tracks proportion of loans reaching 30+ DPD within the first 3 months on book, serving as an early indicator of underwriting drift.
- **Delinquency bounce:** Flags accounts oscillating between 30 DPD and Current twice or more within any rolling 12-month period.

---

## Module 3: `03_rating_and_pd`

> **Purpose:** Builds independent application and behavioural scorecards, standalone PIT and TTC PD models, executes central tendency calibration, measures model cyclicality against PRA SS4/24 standards, constructs a 15-grade master rating scale, and performs rigorous validation.

---

### `01_application_scorecard.py` — Application Scorecard

- **Data scope:** Exclusively origination-time variables (credit score, original LTV, DTI, note rate, loan term, occupancy type, property type, loan purpose).
- **Methodology:** Monotonic coarse-classing, Weight of Evidence (WoE) transformation, and Information Value (IV) screening. Features with IV < 0.02 are eliminated; features with IV > 0.50 are quarantined for leakage investigation.
- **Multicollinearity:** Variance Inflation Factor (VIF) screening with threshold VIF < 10.
- **Model fitting:** Logistic regression fitted via Iteratively Reweighted Least Squares (IRLS).
- **Score scaling:** Calibrated to the chosen anchor:
  $$\text{Odds} = \frac{P(\text{Good})}{P(\text{Bad})}$$
  $$\text{Factor} = \frac{\text{PDO}}{\ln(2)} = \frac{20}{\ln(2)} \approx 28.8539$$
  $$\text{Offset} = \text{Target Score} - \text{Factor} \times \ln(\text{Target Odds}) = 650 - 28.8539 \times \ln(50) \approx 537.1232$$
  $$\text{Score} = 537.1232 + 28.8539 \times \ln(\text{Odds})$$
  Ensures that score 650 corresponds to 50:1 odds and the score doubles every 20 points.

---

### `02_behavioural_scorecard.py` — Behavioural Scorecard

- **Data scope:** Origination attributes combined with strictly lagged ($t-1$) dynamic variables: lagged current UPB, indexed current LTV, 6-month payment pattern, lagged modification flag, and time on book.
- **Methodology:** Standardized WoE/IV logistic framework providing dynamic monthly re-scoring for portfolio surveillance and IFRS 9 SICR staging.

---

### `03_pit_pd.py` — Standalone Point-in-Time (PIT) PD Model

- **Definition:** PIT PD reflects conditional default expectations given current macroeconomic conditions.
- **Specification:** Augments borrower-level scorecard log-odds with a macroeconomic satellite overlay:
  $$\text{PD}_{PIT,i,t} = \sigma\left(\text{log-odds}_i + \hat{\gamma}_1 \cdot \Delta U_t + \hat{\gamma}_2 \cdot \Delta \text{HPI}_t\right)$$
  where $\Delta U_t$ represents change in unemployment and $\Delta \text{HPI}_t$ represents regional house price changes.

---

### `04_ttc_pd.py` — Standalone Through-the-Cycle (TTC) PD Model

- **Definition:** TTC PD reflects cycle-neutral default propensity over an economic cycle, anchored to the Long-Run Average Default Rate (LRADR).
- **Specification:** Rating grades are calibrated directly to the historical default rate across the full 104-quarter history (including the 2007–2009 downturn).
- **Regulatory PD floor:** 0.10% (10 bps) under PRA Rulebook Credit Risk: Internal Ratings Based Approach (CRR) Part, Article 163(1)(b), treating the portfolio as if UK residential property.

---

### `05_pd_calibration.py` — Calibration & Cyclicality Measurement

- **Calibration method:** Platt scaling and central tendency scaling aligning grade-level central PDs to long-run historical averages.
- **Model cyclicality measurement:**
  Evaluates model cyclicality $\alpha \in [0, 1]$ directly by comparing the variance of log-odds predicted default rates against observed default rates over the cycle:
  $$\alpha = \frac{\text{Var}\left(\ln\left(\frac{\text{ODR}_t}{1 - \text{ODR}_t}\right)\right)}{\text{Var}\left(\ln\left(\frac{\text{PD}_t}{1 - \text{PD}_t}\right)\right)}$$
  Reports the measured cyclicality metric against the 30% maximum cyclicality standard under PRA SS4/24 paragraph 11.38.
- **Application of statutory floor:** All calibrated PD estimates are floored at 0.10%.

---

### `06_master_rating_scale.py` — Master Rating Scale

- **Scale architecture:** 15 numbered rating grades (Grade 1 through Grade 15), geometrically spaced between 0.10% and 20.0%:
  $$\text{PD}_{upper, g} = \text{PD}_{min} \times \left(\frac{\text{PD}_{max}}{\text{PD}_{min}}\right)^{g / 15}$$
  No external agency letter ratings are used.
- **Portfolio distribution constraints:** Concentration cap of maximum 30% UPB in any single rating grade.
- **Rating migration matrix:** Calculates the 12-month forward migration matrix between numbered grades across historical reporting periods.

---

### `07_model_validation.py` — Model Validation & Margin of Conservatism

- **Discrimination:** Gini coefficient, Area Under ROC Curve (AUC), Kolmogorov-Smirnov (KS) statistic on out-of-time test partitions.
- **Calibration:** Brier score with Murphy decomposition (reliability, resolution, uncertainty), Hosmer-Lemeshow goodness-of-fit test, Spiegelhalter Z-test.
- **Exact binomial backtesting:** Tests hypothesis $H_0: \hat{p}_g = p_g$ per rating grade using exact binomial distributions at 95% (amber) and 99% (red) confidence thresholds per PRA SS4/24 paragraph 18.17 and BCBS CRE36.87.
- **Stability:** Population Stability Index (PSI) and Characteristic Stability Index (CSI).
- **Margin of Conservatism (MoC):** Framework per PRA SS4/24 paragraph 9.7:
  - Category A: Data and methodological deficiencies.
  - Category B: Relevant changes in underwriting or operational processes.
  - Category C: General estimation uncertainty.
- **Low-default portfolio estimation (Grade 1):** Pluto-Tasche general Beta quantile framework valid for any number of observed defaults $k \ge 0$:
  $$\text{PD}_{upper}(\alpha; k, n) = \text{BetaQuantile}(\alpha; k+1, n-k)$$
  Evaluated at 95% confidence level.

---

## Module 4: `04_lgd_ead`

> **Purpose:** Estimates economic loss given default using discounted cash flows under regulatory discount rate rules, implements the PRA SS4/24 Chapter 15 component approach for residential mortgages, and computes the Expected Loss waterfall.

---

### `01_workout_lgd.py` — Workout LGD & Cash Flow Discounting

- **Discount rate rules:**
  - IFRS 9: Discounted at the asset's original Effective Interest Rate (EIR).
  - Regulatory capital / Downturn LGD: Discounted at the Federal Funds Effective Rate (EFFR) at the date of default plus 500 bps (substituting for SONIA + 500 bps under PRA SS4/24 paragraph 13.16), floored at 9.0% per PRA SS4/24 paragraph 13.17.
- **Unresolved workouts:** Chain-ladder actuarial development triangles to project future recoveries on unresolved default cases.
- **Two-stage hurdle model:**
  - Stage 1 (Cure probability): Logistic regression predicting probability of zero loss.
  - Stage 2 (Loss severity given no cure): Beta regression / Papke-Wooldridge fractional response model for outcomes bounded in $(0, 1]$.
- **Distressed asset sales:** Non-performing note sales remain classified as loss outcomes for LGD estimation.

---

### `02_component_lgd.py` — Mortgage Component Approach (SS4/24 Chapter 15)

Component formulation for residential mortgages:
$$\text{LGD} = P(\text{no cure}) \times \left[1 - \frac{V_{stressed} \times (1 - \text{FSD})}{\text{EAD}} + \frac{\text{Costs}}{\text{EAD}}\right]$$

- **Stressed collateral valuation:**
  - Mandatory minimum 25% house price decline from peak (SS4/24 paragraph 15.24).
  - 40% average market price decline from peak as reference point.
  - Stressed value must remain at least 5% below current market valuation at all times (SS4/24 paragraph 15.25).
- **Forced sale discount (FSD):** 10% to 20% haircut on distressed property liquidations.
- **Direct and indirect costs:** Legal fees, administrative overhead, and property maintenance loaded into severity.
- **Statutory LGD input floor:** 5.0% for residential mortgages under Basel 3.1 (PRA Rulebook Credit Risk: Internal Ratings Based Approach (CRR) Part, Article 164(4)(a)).

---

### `03_expected_loss.py` — Expected Loss Waterfall & Reconciliation Bridge

- **Regulatory Expected Loss (EL):**
  $$\text{EL} = \text{PD}_{TTC} \times \text{LGD}_{downturn} \times \text{EAD}$$
- **Reconciliation bridge:** Explicit reconciliation between Regulatory EL and IFRS 9 Expected Credit Loss (ECL):
  - Point-in-time vs Through-the-cycle PD parameters.
  - Downturn LGD with statutory floors vs lifetime forward-looking macro LGD.
  - 12-month horizon vs lifetime staging horizon.
  - Capital deduction mechanics where Regulatory EL exceeds accounting provisions.

---

## Module 5: `05_ifrs9_ecl`

> **Purpose:** Models accounting loan-loss allowances under UK-adopted IFRS 9: dual-criteria staging, competing-risk lifetime PD term structures, scenario weighting, non-linearity quantification, and monthly movement waterfalls.

---

### `01_staging_sicr.py` — Staging & Significant Increase in Credit Risk

- **Stage 1:** Performing loans with no SICR since origination (12-month ECL).
- **Stage 2:** Underperforming loans with SICR since origination (Lifetime ECL).
- **Stage 3:** Credit-impaired exposures in default (Lifetime ECL, interest on net carrying amount).
- **Quantitative SICR criteria (dual hurdle):**
  - Relative test: $\text{PD}_{current} > 2.0 \times \text{PD}_{origination}$.
  - Absolute test: $\text{PD}_{current} - \text{PD}_{origination} > 1.0\%$.
- **Qualitative SICR triggers:** Forbearance arrangements, payment concessions, and internal credit watchlists.
- **Regulatory backstop:** 30 DPD mandatory transfer to Stage 2.
- **Probationary transfer rules:** Exposures curing from Stage 3 remain in Stage 2 throughout the required probation period before re-entering Stage 1.

---

### `02_pd_term_structure.py` — Lifetime PD Term Structure

- **Competing-risk survival analysis:** Implemented via Aalen-Johansen CIF in DuckDB SQL, separating default events from voluntary prepayment exits.
- **Marginal PD curve derivation:**
  $$f(t) = \frac{\text{CIF}_{default}(t) - \text{CIF}_{default}(t-1)}{1 - \text{CIF}_{all}(t-1)}$$
- **Behavioural lifetime:** Incorporates historical CPR curves to determine empirical behavioural mortgage life.

---

### `03_lifetime_lgd_ead.py` — Forward-Looking LGD & EAD

- **Dynamic PIT LGD:** Links component collateral values to forward macroeconomic house price trajectories under defined scenarios.
- **Amortising EAD profile:** Accounts for scheduled contractual principal amortization combined with behavioural voluntary prepayments over the loan life.

---

### `04_scenario_ecl.py` — Multi-Scenario ECL & Non-Linearity

- **Economic scenarios:** Baseline (50% weighting), Upside (25% weighting), Downside (25% weighting).
- **Probability-weighted ECL:**
  $$\text{ECL}_{weighted} = \sum_{s} w_s \times \text{ECL}_s$$
- **Jensen's inequality non-linearity adjustment:** Quantifies the divergence between probability-weighted scenario ECL and ECL evaluated at probability-weighted macroeconomic inputs, driven by convexity in collateral loss severity.

---

### `05_movement_waterfall.py` — Monthly ECL Movement Waterfall

Produces the formal institutional accounting bridge:

| Component | Sign | Accounting Interpretation |
|:--- |:--- |:--- |
| Opening Allowance | — | Opening provision balance at start of reporting period |
| New lending originations | + | Initial 12-month Stage 1 ECL recognized on new loans |
| Repayments and derecognition | − | Release of ECL on loans settled or prepaid |
| Stage 1 → Stage 2 transfers | + | ECL elevation to lifetime provision following SICR |
| Stage 2 → Stage 1 cures | − | ECL reduction to 12-month provision post-probation |
| Stage 1 / 2 → Stage 3 (New In-Default Inflows) | +/− | Reclassification to credit-impaired default status |
| Model and parameter remeasurements | +/− | Updates to PD curves, LGD parameters, or macro scenarios |
| Charge-offs and write-offs | − | Derecognition of uncollectable balances |
| Post-write-off recoveries | + | Cash recoveries received on previously written-off loans |
| Closing Allowance | — | Ending provision balance at period end |

---

## Module 6: `06_basel_capital`

> **Purpose:** Computes regulatory risk-weighted assets under Basel 3.1 Standardised and Advanced IRB approaches, implements output floors, and computes closed-form economic capital.

---

### `01_standardised_rwa.py` — Standardised Approach (Basel 3.1)

- **Owner-Occupied (`P`) and Second Homes (`S`):**
  - Evaluated under PRA Rulebook Article 124F loan-splitting approach.
  - Exposure up to 55% of property valuation receives a **20% risk weight**.
  - Remaining exposure receives the counterparty risk weight (**75%** for natural persons under Article 124L).
  - *Example:* An 80% LTV loan on a 100,000 property has 80,000 exposure. The split yields 55,000 at 20% (11,000 RWA) and 25,000 at 75% (18,750 RWA), totaling 29,750 RWA (effective risk weight 37.19%).
- **Investor Loans (`I`, Buy-to-Let):**
  - Governed by Article 124E (cash-flow dependent residential property) and evaluated under Article 124G Table 6B:
    - LTV $\le 50\%$: 30% risk weight
    - $50\% < \text{LTV} \le 60\%$: 35% risk weight
    - $60\% < \text{LTV} \le 80\%$: 50% risk weight
    - $80\% < \text{LTV} \le 90\%$: 60% risk weight
    - $90\% < \text{LTV} \le 100\%$: 75% risk weight
    - $\text{LTV} > 100\%$: 105% risk weight
  - *Example:* An 80% LTV investor loan on a 100,000 property receives a 50% risk weight, totaling 40,000 RWA.
- **Property valuation rules:**
  - Property value at origination updated downwards via FHFA regional house price index (Article 124D(5)).
  - Upward property revaluations are not modelled as a conservative choice.
- **Regulatory capital buffers:** Capital Conservation Buffer (2.5% of RWA) plus minimum Pillar 1 requirements.

---

### `02_airb_vasicek.py` — Retail AIRB Vasicek Formulation

- **Asymptotic Single Risk Factor (ASRF) derivation:**
  Conditional default rate at 99.9th percentile:
  $$\text{PD}_{conditional} = \Phi\left(\frac{\Phi^{-1}(\text{PD}) + \sqrt{\rho} \cdot \Phi^{-1}(0.999)}{\sqrt{1-\rho}}\right)$$
- **Capital requirement per unit EAD:**
  $$K = \text{LGD} \times \left[\text{PD}_{conditional} - \text{PD}\right]$$
  $$\text{RWA} = K \times 12.5 \times \text{EAD}$$
  Retail residential mortgage exposures under Article 154 and BCBS CRE31.14 are exempt from maturity scaling.
- **Parameters:**
  - Fixed asset correlation $\rho = 0.15$.
  - Statutory PD floor: 0.10% (10 bps) under Article 163(1)(b), treating the book as if UK residential property.
  - Statutory LGD input floor: 5.0% under Article 164(4)(a).
- **Basel 3.1 Output Floor:** Phased implementation across aggregate portfolio RWA:
  - 2027: 60.0%
  - 2028: 65.0%
  - 2029: 70.0%
  - 2030+: 72.5%

---

### `03_economic_capital.py` — Closed-Form Economic Capital & RAROC

- **Analytical Vasicek loss distribution:**
  $$\text{VaR}_{99.9\%} = \sum_i \text{EAD}_i \times \text{LGD}_i \times \Phi\left(\frac{\Phi^{-1}(\text{PD}_i) + \sqrt{\rho} \cdot \Phi^{-1}(0.999)}{\sqrt{1-\rho}}\right)$$
  $$\text{EC} = \text{VaR}_{99.9\%} - \text{EL}$$
  For an asymptotically large portfolio of over 100,000 residential loans, idiosyncratic risk diversifies away.
- **Euler capital allocation:** Decomposes aggregate economic capital across portfolio segments:
  $$\text{EC}_i = \text{EAD}_i \times \frac{\partial \text{VaR}}{\partial \text{EAD}_i}$$
- **Risk-Adjusted Return on Capital (RAROC):**
  $$\text{RAROC} = \frac{\text{Net Interest Income} - \text{Expected Loss} - \text{Operating Costs}}{\text{Economic Capital}}$$
  Evaluated against an assumed institutional hurdle rate of 10.0%.

---

## Module 7: `07_stress_testing`

> **Purpose:** Projects losses, allowances, and regulatory capital ratios across severe macroeconomic recessions, executes state inversion linking macro stress to facility risk, and identifies the balance sheet breaking point.

---

### `01_satellite_models.py` — Macro Satellite Models & State Inversion

- **Stationarity testing:** Augmented Dickey-Fuller (ADF) and Kwiatkowski-Phillips-Schmidt-Shin (KPSS) tests on macroeconomic time series.
- **ARDL models:** Autoregressive Distributed Lag error-correction models linking unemployment and house price movements to conditional default rates.
- **Corrected Vasicek state inversion formula:**
  Given a macro conditional default rate $\text{DR}_{stress}$, inverts the ASRF formula to recover the implied systematic factor shock $z^*$:
  $$z^* = \frac{\Phi^{-1}(\text{PD}_{TTC}) - \Phi^{-1}(\text{DR}_{stress})\sqrt{1-\rho}}{\sqrt{\rho}}$$
  Under adverse macroeconomic conditions ($\text{DR}_{stress} > \text{PD}_{TTC}$), $z^*$ is strictly negative.
  *Example:* For $\text{PD}_{TTC} = 1.0\%$, $\rho = 0.15$, and $\text{DR}_{stress} = 5.0\%$:
  $$\Phi^{-1}(0.01) = -2.3263, \quad \Phi^{-1}(0.05) = -1.6449, \quad \sqrt{1-0.15} = 0.9220, \quad \sqrt{0.15} = 0.3873$$
  $$z^* = \frac{-2.3263 - (-1.6449 \times 0.9220)}{0.3873} = -2.0911$$
- **Multi-grade portfolio inversion:**
  For a book distributed across 15 rating grades with grade weights $w_g$, the aggregate conditional default rate is:
  $$\text{DR}(z) = \sum_{g=1}^{15} w_g \Phi\left(\frac{\Phi^{-1}(\text{PD}_g) - \sqrt{\rho}z}{\sqrt{1-\rho}}\right)$$
  The system solves for $z^*$ numerically using 1D Brent root-finding (`scipy.optimize.brentq`) to satisfy $\text{DR}(z^*) = \text{DR}_{stress}$.

---

### `02_stress_projection.py` — 5-Year Capital Stress Projection

- **Macroeconomic scenario:** Aligned with the Bank of England 2025 Bank Capital Stress Test (BCST) specification: residential house price decline of 28%, peak unemployment reaching 8.5%, and path of policy interest rates.
- **Standardized Starting Balance Sheet (all values assumed):**
  - **Assets:** Total = 11,765
    - Residential Mortgages = 10,000
    - Liquid Assets / Government Gilts (0% risk weight) = 1,765
  - **Liabilities & Equity:** Total = 11,765
    - Customer Deposits = 9,800
    - Wholesale Funding = 1,000
    - Tier 2 Capital = 200
    - CET1 Equity Capital = 765
  - **Funding costs:** Customer deposit rate assumed at policy rate less 50 bps; wholesale funding at policy rate + 40 bps.
  - **Starting CET1 ratio:** 14.0% evaluated on Basel 3.1 Standardised Approach RWA.
- **Stress dynamics:**
  1. Satellite ARDL model maps macro trajectory to stressed conditional default rates.
  2. Numerical state inversion derives $z^*$ path.
  3. Stressed PD curves trigger SICR reclassifications, generating an IFRS 9 provision spike in Year 1.
  4. Stressed HPI increases component LGD severity.
  5. Stressed Net Interest Income (NII) reflects deposit beta and funding spread compression.
  6. Stressed CET1 capital path evaluated against regulatory hurdle rates.
- **Capital hurdle:** Total bank hurdle is **6.2%** (statutory 4.5% Pillar 1 minimum plus 1.7% assumed Pillar 2A requirement). 4.5% represents the absolute balance sheet breaking point.

---

### `03_reverse_stress.py` — Reverse Stress Testing

- **Breaking point condition:** CET1 ratio falling below the statutory 4.5% Pillar 1 minimum.
- **Optimization:** Numerical search across the joint space of macro shocks (unemployment rise, house price collapse, interest rate spike) minimizing the Mahalanobis distance from baseline historical covariance:
  $$d_M = \sqrt{(x - \mu)^T \Sigma^{-1} (x - \mu)}$$
- Identifies the most plausible macroeconomic shock combination that results in capital depletion.

---

## Module 8: `08_model_risk_mgmt`

> **Purpose:** Implements the institutional governance and oversight framework mandated by UK PRA SS1/23 (effective 17 May 2024, updated April 2026), with secondary benchmarking against SR 11-7 / SR 26-2 guidance.

---

### `01_model_inventory.py` — Automated Model Register

Scans repository modules and maintains the formal model register:

| Field | Model Inventory Entry Example |
|:--- |:--- |
| Model Identifier | PD-APP-001 |
| Model Description | Residential Mortgage Application Scorecard |
| Code Location | `residential_mortgage/03_rating_and_pd/01_application_scorecard.py` |
| Methodology | Monotonic WoE Coarse-Classing with Logistic Regression |
| Regulatory Usage | AIRB PD estimation, IFRS 9 Stage 1 originations |
| Development Date | 2026-Q4 |
| Risk Tier | Tier 1 (Direct regulatory capital and provision impact) |
| SS1/23 Alignment | Tier 1 Model Governance and Board Oversight |

---

### `02_conceptual_soundness.md` — Conceptual Soundness Documentation

Documents per-model theoretical integrity:
1. **Mathematical foundation:** Economic intuition, behavioral theory, and statistical justification.
2. **Data provenance:** Sample selection rules, exclusions, and leakage quarantine enforcement.
3. **Assumptions and boundary conditions:** Explicit operating limits and known model weaknesses.
4. **Alternative methodologies:** Justification for selected methodology over rejected alternatives.

---

### `03_validation_reports/` — Independent Validation Reports

Validation reports structured under PRA SS1/23 Principle 4 (Model validation and ongoing monitoring) and Principle 5 (Risk mitigants and governance):
- **Conceptual review:** Independent evaluation of statistical assumptions.
- **Outcomes analysis:** Backtesting against realized defaults and severities.
- **Benchmarking:** Model performance compared against alternative specifications.
- **Deficiency tracking:** Findings categorized by severity with remediation action plans.

---

### `04_monitoring_dashboard.py` — Ongoing Performance Monitoring

- **Input stability:** Tracks Population Stability Index (PSI) and Characteristic Stability Index (CSI).
- **Discrimination monitoring:** Quarterly tracking of Gini, AUC, and KS statistics.
- **Calibration monitoring:** Predicted vs realized default rates across 15 rating grades.
- **Binomial traffic lights:** Green, Amber, Red alerting based on exact binomial test thresholds.

---

## `regulatory_parameters.py`

Single authoritative parameter registry located at `residential_mortgage/regulatory_parameters.py`. Every parameter is documented with primary regulatory citations and verification dates.

```python
# residential_mortgage/regulatory_parameters.py
# Authoritative registry of all regulatory parameters and thresholds.
# Every number cited to primary regulatory source text.
# Date verified: 14 November 2026.

# ── Definition of Default (PRA SS3/24 & Rulebook Article 178) ────────────────
DPD_THRESHOLD_DAYS = 90                   # 90 DPD standard. PRA SS3/24 paragraph 3.2
MATERIALITY_ABSOLUTE_THRESHOLD = 0.0      # Zero absolute threshold for retail. SS3/24 paragraph 3.6
MATERIALITY_RELATIVE_THRESHOLD = 0.00     # Zero relative threshold for retail. SS3/24 paragraph 3.6
PROBATION_ARREARS_MONTHS = 3              # Arrears cure window. PRA Rulebook Article 178(5)
PROBATION_RESTRUCTURING_MONTHS = 12       # Restructuring cure window. PRA Rulebook Article 178(5A)
UTP_MODIFICATION_TRIGGER = "Modification_Flag == 'Y'"  # Distressed restructuring choice

# ── Loss Given Default (PRA SS4/24 & Rulebook Article 164) ───────────────────
LGD_DISCOUNT_SPREAD_EFFR_BPS = 500        # EFFR + 500 bps (substituting for SONIA+500). SS4/24 paragraph 13.16
LGD_DOWNTURN_DISCOUNT_FLOOR_PCT = 9.0     # Minimum 9% discount rate for downturn LGD. SS4/24 paragraph 13.17
LGD_INPUT_FLOOR_RESIDENTIAL_PCT = 5.0     # Statutory input floor. PRA Rulebook Article 164(4)(a)
LGD_HPI_FALL_REFERENCE_PCT = 40.0         # Reference fall from peak. SS4/24 paragraph 15.24
LGD_HPI_FALL_MINIMUM_PCT = 25.0           # Minimum fall from peak. SS4/24 paragraph 15.24
LGD_CURRENT_VALUE_MIN_HAIRCUT_PCT = 5.0   # Minimum 5% below current valuation. SS4/24 paragraph 15.25

# ── Probability of Default (PRA Rulebook & SS4/24) ───────────────────────────
PD_FLOOR_RESIDENTIAL_PCT = 0.10           # 10 bps statutory floor. PRA Rulebook Article 163(1)(b)
PD_CYCLICALITY_MAX_PCT = 30.0             # Cyclicality cap. PRA SS4/24 paragraph 11.38
SCORECARD_TARGET_SCORE = 650              # Scorecard scaling anchor score
SCORECARD_TARGET_ODDS = 50.0              # Scorecard scaling anchor odds (50:1)
SCORECARD_POINTS_TO_DOUBLE = 20           # Scorecard points to double odds

# ── Basel 3.1 Standardised Approach (PRA Rulebook Part: Credit Risk) ──────────
SA_SPLIT_LTV_THRESHOLD_PCT = 55.0         # 55% valuation split threshold. Article 124F
SA_PROPERTY_PORTION_WEIGHT_PCT = 20.0     # Risk weight on portion <= 55%. Article 124F
SA_COUNTERPARTY_WEIGHT_PCT = 75.0         # Counterparty risk weight natural persons. Article 124L
SA_VALUATION_INDEX = "FHFA_REGIONAL_HPI"  # Regional index for downward revaluations. Article 124D(5)

# ── Basel 3.1 AIRB & Capital Ratios ──────────────────────────────────────────
ASRF_ASSET_CORRELATION = 0.15             # Fixed retail mortgage asset correlation. Article 154
ASRF_CONFIDENCE_LEVEL = 0.999             # 99.9% capital confidence level
CAPITAL_CONSERVATION_BUFFER_PCT = 2.5     # CCb requirement
BANK_TOTAL_HURDLE_PCT = 6.2               # 4.5% Pillar 1 + 1.7% assumed Pillar 2A
BREAKING_POINT_CET1_PCT = 4.5             # Statutory minimum CET1 exhaustion threshold

# ── Basel 3.1 Phased Output Floor ────────────────────────────────────────────
OUTPUT_FLOOR_2027 = 0.600
OUTPUT_FLOOR_2028 = 0.650
OUTPUT_FLOOR_2029 = 0.700
OUTPUT_FLOOR_2030_ONWARDS = 0.725

# ── IFRS 9 Staging Parameters (Documented Choices) ───────────────────────────
SICR_PD_RELATIVE_MULTIPLIER = 2.0         # PD_current > 2.0 * PD_origination
SICR_PD_ABSOLUTE_THRESHOLD_PCT = 1.0      # PD_current - PD_origination > 1.0%
SICR_DPD_BACKSTOP_DAYS = 30               # 30 DPD mandatory Stage 2 backstop
```

---

## `data_log.md` — Auto-Generated Ingestion Log

`data_log.md` is strictly generated by `build_base_tables.py`. Entries are prepended chronologically:

```markdown
# Data ingestion log
Written by build_base_tables.py. Do not edit.

---

## 2026-11-15 14:32:11 | Quarter: 2005Q1
- Acquisition cohort loaded      : 2005Q1
- Raw file                       : 6.60 GB, 24,701,544 lines
- Monthly records in Parquet     : 24,701,544
- Unique loans loaded            : 303,611
- Development subset (10%)       : 30,361
- Original UPB first month (A)   : 49,416,049,000.00
- Original UPB restated (R)      : 0.00 (0 loans)
- Original UPB blank first (B)   : 0.00 (0 loans)
- Total original UPB loaded      : 49,416,049,000.00 (= A + R + B)
- Restated fields (top 3)        : seller_name 13,215, msa 6,578, orig_ltv 729
- Checks                         : 8 of 8 PASS
- Load time                      : 00m 48s
- Active cohorts in database     : 1 cohort (2005Q1)
```

---

## `README.md` — Institutional Showpiece

**Mandatory opening statement:**
```markdown
> The loans are US conforming residential mortgages from Fannie Mae, assessed under UK rules.
```

---

## Build Order

| Step | Script / Artifact | Prerequisites | Description |
|:--- |:--- |:--- |:--- |
| - | `00_data/field_map.py` | None | Canonical 113-field position and type mapping |
| 0 | `00_data/convert_raw_to_parquet.py` | Raw data zip | Extracts CSV from zip and converts to compressed Parquet with conversion record |
| 1 | `00_data/build_base_tables.py` | Step 0 | Ingests quarters to `loans_table`, creates `loan_monthly_view`, draws `sampled_loans_table` |
| 1b | `00_data/build_macro_tables.py` | None | Ingests macroeconomic series (EFFR, UNRATE, HPI) to macro tables and mart |
| 2 | `01_data_foundation/02_eda.py` | Step 1 | Univariate, bivariate, drift, and missingness audits |
| 3 | `01_data_foundation/03_leakage_audit.py` | Step 2 | Target leakage quarantine and feature screening |
| 4 | `01_data_foundation/04_feature_catalogue.py` | Step 3 | Approved feature register with lag constraints |
| 5 | `02_portfolio_analytics/01_data_audit.py` | Step 4 | Stock-and-flow balance reconciliation |
| 6 | `02_portfolio_analytics/02_default_engine.py` | Step 5 | DPD analysis and recursive probation state machine |
| 7 | `02_portfolio_analytics/03_roll_rates.py` | Step 6 | Multi-state Markov transition matrices |
| 8 | `02_portfolio_analytics/04_vintage_curves.py` | Step 6 | MOB CDR, CPR/SMM, Aalen-Johansen CIF competing risks |
| 9 | `02_portfolio_analytics/05_concentrations.py` | Steps 7, 8 | Bivariate risk grids, HHI, and early payment default |
| 10 | `03_rating_and_pd/01_application_scorecard.py` | Step 6 | Origination scorecard with 50:1 odds at 650 anchor |
| 11 | `03_rating_and_pd/02_behavioural_scorecard.py` | Step 10 | Lagged performance behavioural scorecard |
| 12 | `03_rating_and_pd/03_pit_pd.py` | Step 10 | Standalone PIT PD model with macroeconomic overlay |
| 13 | `03_rating_and_pd/04_ttc_pd.py` | Step 6 | Standalone TTC PD model anchored to historical LRADR |
| 14 | `03_rating_and_pd/05_pd_calibration.py` | Steps 12, 13 | Platt scaling and SS4/24 cyclicality measurement |
| 15 | `03_rating_and_pd/06_master_rating_scale.py` | Step 14 | 15 numbered rating grades and migration matrix |
| 16 | `03_rating_and_pd/07_model_validation.py` | Steps 14, 15 | Exact binomial backtesting, Pluto-Tasche, MoC |
| 17 | `04_lgd_ead/01_workout_lgd.py` | Step 6 | Discounted workout recoveries and hurdle model |
| 18 | `04_lgd_ead/02_component_lgd.py` | Step 17 | SS4/24 Chapter 15 component approach (5% floor) |
| 19 | `04_lgd_ead/03_expected_loss.py` | Steps 15, 18 | Expected loss waterfall and EL vs ECL bridge |
| 20 | `05_ifrs9_ecl/01_staging_sicr.py` | Steps 15, 19 | Dual SICR staging, 30 DPD backstop, probation |
| 21 | `05_ifrs9_ecl/02_pd_term_structure.py` | Steps 8, 20 | Lifetime PD curve via Aalen-Johansen CIF |
| 22 | `05_ifrs9_ecl/03_lifetime_lgd_ead.py` | Steps 18, 21 | Scenario PIT LGD and amortising EAD profiles |
| 23 | `05_ifrs9_ecl/04_scenario_ecl.py` | Steps 21, 22 | Multi-scenario weighted ECL and non-linearity |
| 24 | `05_ifrs9_ecl/05_movement_waterfall.py` | Step 23 | Monthly ECL accounting movement waterfall |
| 25 | `06_basel_capital/01_standardised_rwa.py` | Step 5 | Article 124F/124L loan-splitting and 124G weights |
| 26 | `06_basel_capital/02_airb_vasicek.py` | Steps 15, 18 | Retail AIRB capital and phased output floor |
| 27 | `06_basel_capital/03_economic_capital.py` | Step 26 | Closed-form Vasicek economic capital and RAROC |
| 28 | `07_stress_testing/01_satellite_models.py` | Steps 7, 26 | ARDL satellite models and corrected state inversion |
| 29 | `07_stress_testing/02_stress_projection.py` | Steps 23, 26, 28 | 5-year capital path under BoE 2025 BCST scenario |
| 30 | `07_stress_testing/03_reverse_stress.py` | Step 29 | Mahalanobis search for CET1 < 4.5% breaking point |
| 31 | `08_model_risk_mgmt/01_model_inventory.py` | Steps 16, 24, 27, 30 | Introspects models into SS1/23 inventory |
| 32 | `08_model_risk_mgmt/04_monitoring_dashboard.py` | Step 31 | Ongoing performance monitoring dashboard |
| 33 | `README.md` | All steps | Complete repository showpiece documentation |

---

## Settled Decisions

| Decision | Topic | Settled Choice | Regulatory Basis / Operational Rationale |
|:--- |:--- |:--- |:--- |
| D1 | Standardised Weights | Article 124F loan-splitting for Owner-Occupied / Second Home; Article 124G Table 6B for Investor loans | PRA Rulebook Articles 124E, 124F, 124G, 124L |
| D2 | Property Valuation | Origination value updated downwards via FHFA regional HPI; upward revaluations not modelled | PRA Rulebook Article 124D(5) |
| D3 | LGD Discount Rate | Federal Funds Effective Rate (EFFR) at default date + 500 bps floored at 9.0% for downturn LGD | PRA SS4/24 paragraphs 13.16 & 13.17 |
| D4 | Statutory PD Floor | 0.10% (10 bps), stated as an assumed choice treating the book as if UK residential property | PRA Rulebook Article 163(1)(b) |
| D5 | Restructuring Trigger | `Modification_Flag == 'Y'` as primary restructuring trigger; forbearance is Stage 2 SICR trigger | Operational simplification; PRA SS3/24 |
| D6 | Probation Length | 3 months for arrears; 12 months for distressed restructuring | PRA Rulebook Article 178(5) & 178(5A) |
| D7 | Exit Taxonomy | Voluntary prepayment is competing terminal event; note sales remain loss outcomes for LGD | Empirical CIF; SS4/24 recovery standards |
| D8 | Stress Hurdle | Total bank hurdle 6.2% (4.5% Pillar 1 + 1.7% Pillar 2A); 4.5% is breaking point | BoE 2025 Bank Capital Stress Test |
| D9 | Model Risk Framework | Primary: UK PRA SS1/23 (Principles 4 & 5); secondary: SR 11-7 / SR 26-2 | PRA SS1/23 effective May 2024 / April 2026 |
| D10 | Scorecard Anchor | Score 650 corresponds to 50:1 odds; PDO = 20 | Explicit institutional anchor calibration |
| D11 | Binomial Backtest | Exact binomial test at 95% (amber) and 99% (red) confidence thresholds | PRA SS4/24 paragraph 18.17; BCBS CRE36.87 |
| D12 | Low-Default Grade 1 | Pluto-Tasche general Beta quantile formula across 15 numbered rating grades (no letter ratings) | General Beta quantile for arbitrary $k \ge 0$ |
| D13 | Economic Capital | Closed-form Vasicek loss model in current build; multi-factor simulation in later extensions | Asymptotically large portfolio of 100k+ loans |
| D14 | PD Model Flow | Master scale TTC PD feeds AIRB capital and EL; forward-looking PIT PD feeds IFRS 9 ECL | Structural separation of capital and accounting |
| D15A | Ingestion Sample | 2000Q1 to 2008Q4, fixed 10% seeded sample of loans per cohort, entire loan histories retained | Captures 2007–2009 downturn; 1.5–2.0M loans |
| D15B | Balance Sheet | Standardized balance sheet (Assets 11,765; Mortgages 10,000; CET1 765); 14% CET1 on SA RWA | Assumed starting profile for stress test |
| D15C | Hypothesis Testing | Unverified empirical claims framed as testable quantitative hypotheses | CRO-facing professional integrity |
| D15D | Folder Structure | Numbered folders and files retained; each module script runs standalone and validates its own DuckDB tables | Deterministic build order; no separate tests folder scaffolding |
| D15E | Output Formatting | Plain numeric amounts, no currency symbols, no country names; original regions preserved | Portable and clean institutional reporting |
| D15F | DuckDB Execution | All heavy data processing executed natively in DuckDB SQL; Python receives aggregated arrays | High performance in 16 GB RAM environment |

---

## Later Extensions

The following advanced capabilities are scheduled for subsequent iterations following the baseline build:
1. **Multi-Factor Economic Capital Simulation:** Full Monte Carlo simulation incorporating regional real estate correlation structures and borrower income shocks.
2. **Dynamic Upward Valuation Modelling:** Explicit indexation of property values for amortizing exposures with audited valuation confidence scores.
3. **Machine Learning Challenger Scorecards:** Monotonic gradient boosting and neural additive models evaluated as challenger scorecards under SS1/23 validation standards.
