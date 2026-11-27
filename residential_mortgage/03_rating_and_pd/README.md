# Module 03 — Rating and PD Estimation

> [!NOTE]
> **Status: Stub.** Scripts are present as empty placeholders; model implementation begins after Module 02 sign-off. This README documents the planned operations and the concept behind each script.

Builds application and behavioural PD scorecards, calibrates through-the-cycle (TTC) and
point-in-time (PIT) PD estimates, constructs the master rating scale, and validates the models.
Consumes `book_snapshot`, `book_snapshot_behavioural`, `default_events_mart`, `risk_drivers_mart`,
and `representativeness_mart` from Module 02.

---

## Operations (Planned)

### Prerequisites

- Module 02 complete and marts DB consistent (`module2_sample.duckdb` or `module2_full.duckdb`).
- `book_snapshot/year=YYYY/*.parquet` and `book_snapshot_behavioural/year=YYYY/*.parquet` available.
- Python 3.11+ `.venv` with `scikit-learn`, `statsmodels`, `scipy` added to `requirements.txt`.

### Planned run order

```powershell
# Application scorecard — origination features only
.venv\Scripts\python.exe residential_mortgage\03_rating_and_pd\scripts\01_application_scorecard.py [--full]

# Behavioural scorecard — lagged behavioural features
.venv\Scripts\python.exe residential_mortgage\03_rating_and_pd\scripts\02_behavioural_scorecard.py [--full]

# PIT PD — economic adjustment of scorecard output
.venv\Scripts\python.exe residential_mortgage\03_rating_and_pd\scripts\03_pit_pd.py [--full]

# TTC PD — cycle-averaged calibration
.venv\Scripts\python.exe residential_mortgage\03_rating_and_pd\scripts\04_ttc_pd.py [--full]

# PD calibration — Hosmer-Lemeshow, Brier score, Gini, KS
.venv\Scripts\python.exe residential_mortgage\03_rating_and_pd\scripts\05_pd_calibration.py [--full]

# Master rating scale — grade boundaries and grade-level PDs
.venv\Scripts\python.exe residential_mortgage\03_rating_and_pd\scripts\06_master_rating_scale.py [--full]

# Model validation — out-of-time and out-of-sample tests
.venv\Scripts\python.exe residential_mortgage\03_rating_and_pd\scripts\07_model_validation.py [--full]
```

### Planned outputs

| Output | Description |
|---|---|
| `application_scorecard_mart` | Binned score, WOE-transformed feature values, raw score, scaled score (0–1000) |
| `behavioural_scorecard_mart` | Same structure with t-1 behavioural features |
| `pit_pd_mart` | PIT PD = $f(\text{scorecard score}, \text{macro index at } t)$ |
| `ttc_pd_mart` | TTC PD = scorecard-score-to-PD mapping averaged over full economic cycle |
| `calibration_mart` | Hosmer-Lemeshow p-value, Brier score, Gini coefficient, KS statistic |
| `master_rating_scale_mart` | 10–20 grades with TTC PD, TTC PD lower/upper 95% CI, grade default count |
| `model_validation_mart` | OOT Gini, PSI of score distribution (development vs OOT), overrides analysis |

---

## Concepts

### `01_application_scorecard.py` — Origination PD

**Purpose:** Train a logistic regression scorecard using origination-time features (FICO, LTV, DTI, loan purpose, occupancy, state tier) on the Module 02 `book_snapshot` with `exclusion_reason = 'included'` and `is_oot = FALSE` (development sample only).

**Mathematical output:** Scorecard coefficients $\hat{\beta}$ from logistic regression after WOE transformation. Scaled score: $s = A - B \times \ln(\text{odds})$ calibrated so score 500 = odds 50:1. Per-loan output: $\hat{P}(\text{default}_{12m}) = \sigma(\hat{\beta}^T x)$.

**Concept:** Application scorecards use only information available at origination — before the loan has any payment history. They are used to price loans at origination and assign initial IRB grades. The logistic regression + WOE approach is the PRA-preferred interpretable method for retail IRB; it makes the relationship between each factor and PD explicit and auditable.

---

### `02_behavioural_scorecard.py` — Behavioural PD

**Purpose:** Train a scorecard using the t-1 lagged features from `book_snapshot_behavioural` (worst DPD 6m/12m, months since last arrears, LTV indexed, balance paid down, rate incentive) combined with origination features.

**Mathematical output:** Same WOE-logistic structure as `01_application_scorecard.py`, using `book_snapshot` joined to `book_snapshot_behavioural` on `(loan_id, snapshot_date)`. Behavioural score typically discriminates 2–3× better than the application score (higher Gini coefficient).

**Concept:** Behavioural scorecards update the PD estimate using the loan's observed payment history. A loan with a 1-month arrears in the past 6 months is materially more likely to default in the next 12 months than one with a perfect record, even given identical origination characteristics. The behavioural score is the primary PD driver for IFRS 9 staging (SICR trigger) and ongoing IRB capital.

---

### `03_pit_pd.py` — Point-in-Time PD

**Purpose:** Adjust the scorecard PD output to reflect current economic conditions using a macro conditioning model.

**Mathematical output:** PIT PD: $\Phi^{-1}(\text{PD}_{\text{PIT}}(t)) = \Phi^{-1}(\text{PD}_{\text{TTC}}) + \gamma Z_t$ where $Z_t$ is a macro index (unemployment rate, house price change) at time $t$. Coefficient $\gamma$ estimated via panel regression of cohort default rates on macro variables from `economy_correlations_mart`.

**Concept:** PIT PD = best estimate of default probability given current economic conditions (high in recession, low in expansion). Required for IFRS 9 ECL calculation. TTC PD = average PD across the full economic cycle. Required for IRB capital calculation. Using PIT PD for capital creates pro-cyclical capital requirements (less capital precisely when more is needed), which is why the two must be maintained separately.

---

### `04_ttc_pd.py` — Through-the-Cycle PD

**Purpose:** Calibrate the scorecard to long-run average default rates from `default_rate_history_mart`, respecting the data minimums from `segment_sufficiency_mart`.

**Mathematical output:** TTC PD per grade and segment = scorecard-band-level default rate averaged over all complete 12-month windows (`window_complete = TRUE`), weighted by performing loan count, with Wilson 95% CI. Floor: at least 1 default per 100 loans per grade (PRA PS11/23 §4.14 minimum).

**Concept:** Long-run calibration prevents cyclical bias. If the model is calibrated only on 2010–2015 (low-default recovery period), TTC PD will be understated. The LRA from `default_rate_history_mart` (complete windows through 2024-12) provides the target. The Vasicek implied correlation from `implied_correlation_mart` cross-checks the grade-level PD confidence intervals.

---

### `05_pd_calibration.py` — Validation Metrics

**Purpose:** Test the calibrated PD model against known outcomes on the development and OOT samples using discrimination and calibration metrics.

**Mathematical output:**
- Gini coefficient (= 2 × AUC − 1): rank-ordering discrimination.
- KS statistic: max difference in cumulative bad/good distributions across score bands.
- Hosmer-Lemeshow $\chi^2$ (10 deciles, df=8): calibration test — are predicted PDs close to observed default rates in each decile?
- Brier score: $\text{BS} = \frac{1}{N}\sum_i (p_i - y_i)^2$.

**Concept:** A PD model must be both **discriminating** (rank-order bads above goods) and **calibrated** (the stated probability must be numerically accurate). Hosmer-Lemeshow p-value < 0.05 indicates systematic miscalibration in at least one score band — a critical failure for ECL computation.

---

### `06_master_rating_scale.py` — Grade Structure

**Purpose:** Define 10–20 rating grades by binning TTC PD estimates and mapping each grade to a PD range, default count, and regulatory description.

**Mathematical output:** `master_rating_scale_mart`: per grade — `pd_lower`, `pd_upper`, `ttc_pd`, `loans`, `bads`, `wilson_ci_low`, `wilson_ci_high`. Grade boundaries chosen so each grade spans ≥ 5 years of observed data and ≥ 20 defaults (Art. 180(1)(a)).

**Concept:** The master rating scale is the IRB model's public interface. Every loan is assigned a grade (not a raw PD), and the grade maps to a PD. This discrete structure makes the model robust to small changes in scorecard output, satisfies the PRA's requirement for "overrides" to be tracked at grade level, and enables Pillar 3 disclosure of grade-level concentration.

---

### `07_model_validation.py` — Out-of-Time Validation

**Purpose:** Assess model performance on the OOT period (2022–2024, `is_oot = TRUE`) and test for population shift using PSI of score distribution.

**Mathematical output:** OOT Gini, OOT KS, PSI of score distribution (development vs OOT), grade migration matrix (% of loans moving ≥ 2 grades), overrides analysis (% of grades manually adjusted, override accuracy vs default rate).

**Concept:** PRA SS4/24 requires out-of-time testing on a held-out period. The 2022–2024 OOT window spans rising interest rates, house price corrections, and post-COVID normalisation — a stress period that tests whether the model extrapolates correctly to regimes not seen in development.
