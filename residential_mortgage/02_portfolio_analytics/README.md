# Module 02 — Portfolio Analytics

Analyses the full 2000–2025 Fannie Mae mortgage portfolio: default definitions, roll rates,
vintage curves, LTV dynamics, risk drivers, segmentation, macro linkages, and representativeness.
Produces 25+ mart tables consumed by Modules 3–8.

---

## Operations

### Prerequisites

- Module 00 complete: `mortgages_sample.duckdb` exists (44.05 MB; or `mortgages.duckdb` for `--full`).
- Module 01 complete: `feature_catalogue_table` exists in the base DB.
- Python 3.11+ `.venv` with `duckdb≥2.0`, `pandas`, `matplotlib`, `numpy`.

### Run the full pipeline

```powershell
# Sample run (~102s on 44 MB sample DB)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py

# Full run (untimed; requires mortgages.duckdb ~2.22 GB)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --full

# Resume from a specific script (e.g. after fixing script 07)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --from-step 07

# Dry-run (print commands without executing)
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py --dry-run
```

### Run individual scripts

```powershell
# Replace <NN> with the script number, e.g. 06
.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\scripts\<NN>_<name>.py [--full]
```

### Outputs

| Output | Location | Description |
|---|---|---|
| Module 2 marts DB (sample) | `outputs/02_portfolio_analytics/sample/module2_sample.duckdb` | 25+ mart tables (27.80 MB) |
| Module 2 marts DB (full) | `outputs/02_portfolio_analytics/full/module2_full.duckdb` | Full-population mart tables |
| `monthly_core` Parquet | `outputs/02_portfolio_analytics/sample/00_build_monthly_core/*.parquet` | Slim 23-column quarterly files |
| `book_snapshot` Parquet | `outputs/02_portfolio_analytics/sample/07_default_rate_history/book_snapshot/year=YYYY/` | December annual loan-level snapshots |
| `book_snapshot_behavioural` | `outputs/02_portfolio_analytics/sample/09_risk_drivers/book_snapshot_behavioural/year=YYYY/` | t-1 lagged behavioural features |
| Findings report | `outputs/02_portfolio_analytics/sample/18_portfolio_findings/18_portfolio_findings.md` | Auto-generated markdown summary |
| Charts | `outputs/02_portfolio_analytics/sample/<NN>_<name>/` | PNG at 300 dpi per script |
| Run log | `.scratch/module2_run_sample.log` | Full stdout for all 19 scripts |

### Script timing (sample DB, 2026-11-25 run)

| Script | Time (s) | | Script | Time (s) |
|---|---|---|---|---|
| 00 | 10.9 | | 10 | 2.3 |
| 01 | 8.7 | | 11 | 7.6 |
| 02 | 6.3 | | 12 | 5.2 |
| 03 | 7.9 | | 13 | 3.5 |
| 04 | 5.0 | | 14 | 2.6 |
| 05 | 8.9 | | 15 | 4.9 |
| 06 | 5.1 | | 16 | 1.8 |
| 07 | 7.7 | | 17 | 2.7 |
| 08 | 1.8 | | 18 | 1.3 |
| 09 | 8.2 | | **Total** | **102.5** |

### Tests

```powershell
# Run 14 known-answer synthetic tests (requires pytest)
.venv\Scripts\python.exe -m pytest residential_mortgage\02_portfolio_analytics\tests\test_module2.py -v
```

---

## Concepts

### `module2_common.py` — Shared Helpers

**Purpose:** Single import point for all 19 scripts. Provides DB connection, path resolution, regulatory constants, validation primitives, and mathematical utilities.

**Key outputs / mathematical content:**
- `scheduled_upb(orig_upb, note_rate, term, mob)` — standard mortgage amortisation formula: $P(k) = P_0 \cdot \frac{(1+r)^n - (1+r)^k}{(1+r)^n - 1}$ where $r = \text{note\_rate}/1200$, $n = \text{term}$, $k = \min(\text{mob}+1, n)$.
- `covid_hold_months(mb, plans, months)` — applies M2-4 UK COVID deferral: holds DPD clock for loans on active relief plans ('F','T','R') that entered a qualifying spell between 2020-03 and 2021-03, up to 6 cumulative months through 2021-07.
- `wilson_ci(events, total)` — Wilson score 95% CI: $\hat{p} \pm z\sqrt{\frac{\hat{p}(1-\hat{p}) + z^2/(4n)}{n}} / (1 + z^2/n)$.
- `Checker` class — collects PASS/FAIL assertions and returns exit code 0 (all pass) or 1 (any fail).
- `write_mart(con, name, sql, keys)` — creates mart table and enforces non-null unique key.

**Regulatory parameters imported from `_settings/`:**
- `DPD_DEFAULT_MONTHS = 3` (Art. 178(1)(b): ≥ 3 whole months behind)
- `PROBATION_ARREARS_MONTHS = 3` (Art. 178(5)(a))
- `PROBATION_RESTRUCTURING_MONTHS = 12` (Art. 178(5A))
- `CREDIT_EXIT_CODES = ('02','03','09','15')` (Fannie Mae foreclosure/third-party sale codes)
- `IRB_RESIDENTIAL_CORRELATION = 0.15` (CRR Art. 154(3))
- `MIN_DATA_YEARS = 5` (Art. 180(2)(e))

---

### `00_build_monthly_core.py` — Stage 0

**Purpose:** Read each quarterly raw Parquet file once, project to 23 essential typed columns, write one `monthly_core` Parquet per quarter, extract workout/exit cashflows, and perform cent-exact cross-checks.

**Mathematical / analytical output:**
- 23-column typed `loan_monthly_core` Parquet (narrow, ZSTD): covers performance fields — `delinquency_months`, `current_upb`, `total_principal`, `borrower_assistance_plan`, `modification_flag`, `zero_balance_code`, plus key cashflow fields.
- `workout_exit_cashflows_mart`: all foreclosure cost/proceeds rows for future LGD computation.
- 8-field cent-exact cross-check: row count, loan count, `active_upb`, `payoff_upb`, `credit_exit_upb`, `other_exit_upb`, `writeoff_upb`, `forgiven_upb` — verifies no rows dropped or values corrupted in the narrow projection.

**Concept embodied:** Column pruning for I/O efficiency. The raw Fannie Mae files have 100+ columns; Module 2 only needs 23. By projecting early and writing compressed Parquet, all 19 downstream scripts scan tiny files instead of the full DB on every pass.

---

### `01_data_audit.py` — Stage A

**Purpose:** Monthly balance roll-forward audit and data plausibility checks. Detects UPB accounting anomalies, servicer-transfer discontinuities, and reporting gaps.

**Mathematical / analytical output:**
- `balance_rollforward_mart`: for each month, `opening_upb + net_advances - principal_paid - prepayments - credit_exit_upb - other_exit_upb = closing_upb`. Residual `unexplained_upb` is the accounting error.
- `data_plausibility_mart`: global metrics — `multi_servicer_loans`, `gap_months_per_loan`, `xx_dpd_rows`, `late_reporting_loans`.

> [!CAUTION]
> **Known P0-2 bug:** `unexplained_upb` reaches -\$360,753 on 2021-10-01 and is not asserted against a tolerance threshold. `cap_added_upb` and `active_forgiven_upb/writeoff_upb` are incorrectly double-counted or omitted. Fix before using roll-forward for LGD or capital purposes.

**Concept embodied:** UPB conservation. In a healthy performing book, the balance roll-forward must reconcile to zero (within payment rounding). A persistent non-zero residual indicates capitalised interest, write-offs, or forgiveness events that are not captured in the servicer reporting. Identifying these is mandatory for IRB data quality (Art. 175(1)(b)).

---

### `02_default_engine.py` — Stage A

**Purpose:** Implement the regulatory default definition and probation state machine for every loan across the full history.

**Mathematical / analytical output:**
- `default_events_mart`: one row per default episode per loan. Fields: `default_month`, `trigger_type`, `probation_months`, `upgraded_by_restructuring`, `balance_at_default`, `cure_month`, `end_reason`, `re_default_number`.
- `default_status_monthly`: expanded monthly status — `loan_id × reporting_period → in_default=TRUE` for every month within a default episode. Derived via SQL `generate_series(default_month, end_month)`.
- `default_sensitivity_mart`: event counts by `treatment` (covid_adjusted vs as_reported) × year × trigger_type for COVID sensitivity analysis.

**Concept embodied:** PRA Art. 178 default definition. Three triggers: (1) **Arrears**: ≥ 3 whole months past due (Art. 178(1)(b)); (2) **Distressed restructuring**: first N→Y `modification_flag` transition after a non-modified observation (Art. 178(2)(d)); (3) **Credit exit**: `zero_balance_code ∈ {02, 03, 09, 15}` (foreclosure/third-party sale). Probation: 3 clean months for arrears (Art. 178(5)(a)); 12 clean months for restructuring (Art. 178(5A)); any month ≥ 1 DPD restarts clean count. Unknown DPD ('XX') and COVID holds pause probation clock without resetting it.

---

### `03_roll_rates.py` — Stage B

**Purpose:** Estimate monthly DPD-state transition matrices and project portfolio arrears over 6, 12, 24, 36 month horizons.

**Mathematical / analytical output:**
- `roll_rates_mart`: monthly transition matrix $T_{ij}$ = P(DPD state = j at $t+1$ | DPD state = i at $t$). States: {0, 1, 2, 3+, credit exit}. Estimated by maximum likelihood: $\hat{T}_{ij} = n_{ij} / n_i$.
- Multi-step projections: $\pi^{(h)} = \pi^{(0)} \cdot T^h$ for horizons $h \in \{6, 12, 24, 36\}$.
- `roll_30day_evidence_mart`: probability of defaulting within 12 months conditional on being 1+ month behind (IFRS 9 30-day backstop evidence with Wilson 95% CI).

**Concept embodied:** Discrete-time Markov chain arrears dynamics. The PRA/FCA IFRS 9 30-day backstop (IFRS 9.B5.5.19) requires that any loan > 30 DPD be classified Stage 2 unless there is rebuttable evidence. The `roll_30day_evidence_mart` provides that evidence: if the transition probability from "1 month behind" to "credit default within 12 months" is statistically low enough, the automatic classification can be rebutted for specific segments.

---

### `04_emergence_and_thresholds.py` — Stage B

**Purpose:** Measure the lag between first missed payment and default recognition, and test sensitivity of event counts to alternative DPD thresholds (60, 90, 120 days).

**Mathematical / analytical output:**
- `emergence_mart`: distribution of months from first DPD ≥ 1 to DPD ≥ 3 (the 90-day trigger), by era and segment.
- `threshold_sensitivity_mart`: count of loans reaching each threshold (60/90/120 DPD), showing how the population changes if the trigger is shifted.

> [!NOTE]
> **Known P1-2 issue:** Loans are assigned to the era of their observation month, not their default month. This can produce cross-era double-counting when the emergence lag spans an era boundary.

**Concept embodied:** Emergence lag / recognition lag. In practice, servicers report delinquency in the month after the payment is missed, adding a 1-month reporting lag. Additionally, the 3-month arrears trigger means a loan first missed in January will typically not be called into default until April. Understanding this lag is critical for IFRS 9 staging (the SICR trigger must look forward to catch the loan before the full 90-day default trigger fires).

---

### `05_vintage_curves.py` — Stage B

**Purpose:** Compute non-parametric cumulative default and prepayment curves by acquisition cohort (origination quarter and acquisition quarter).

**Mathematical / analytical output:**
- `vintage_curves_mart`: Aalen-Johansen cumulative incidence function (CIF) for competing risks — default vs voluntary prepayment.
  - All-cause hazard: $\hat{h}_\cdot(t) = d_\cdot(t) / n(t)$ where $d_\cdot = d_{\text{def}} + d_{\text{pay}}$, $n(t)$ = at-risk count.
  - Survival: $\hat{S}(t) = \prod_{t_k \leq t} (1 - \hat{h}_\cdot(t_k))$.
  - CIF for cause $j$: $\hat{I}_j(t) = \sum_{t_k \leq t} \hat{S}(t_{k-1}) \cdot \hat{h}_j(t_k)$.
- Curves computed at monthly `mob` (months on book) up to 360 months, by cohort quarter.

**Concept embodied:** Competing risks — why naive Kaplan-Meier over-estimates default probability. If a loan prepays, it is "censored" in the KM sense — but it can never subsequently default. Treating prepayment as censoring inflates the estimated default CIF. The Aalen-Johansen estimator avoids this by explicitly modelling prepayment as a competing outcome that removes loans from the default risk set.

---

### `06_current_ltv.py` — Stage B

**Purpose:** Index each loan's property value forward through time using state-level FHFA HPI and compute both indexed and downward-only current LTV distributions.

**Mathematical / analytical output:**
- `loan_origination_value_mart`: per-loan implied origination property value $V_0 = \text{orig\_upb} / (\text{orig\_ltv}/100)$. HPI at origination $\text{HPI}_0$ looked up from `macro_state_hpi_table`.
- `state_hpi_peaktotrough_mart`: per-state peak-to-trough drawdown episodes. Drawdown $= (1 - \text{HPI}_t / \max_{u \leq t} \text{HPI}_u) \times 100\%$ using **running historical peak** (not global max). Flags episodes exceeding 10% (Art. 124D trigger), 25% (LGD floor), 40% (reference downturn).
- `current_ltv_mart`: quarterly LTV band distribution (8 bands from ≤50 to >100):
  - Indexed: $\text{LTV}_{\text{idx}} = 100 \times \text{UPB}_t / (V_0 \times \text{HPI}_t / \text{HPI}_0)$.
  - Downward-only: $\text{LTV}_{\text{down}} = 100 \times \text{UPB}_t / \min(V_0, V_0 \times \text{HPI}_t / \text{HPI}_0)$.

**Concept embodied:** Collateral haircut under CRR Art. 124D and IRB CRM (CRM Art. 208(3)). The downward-only LTV is the PRA's preferred conservative measure — property can never be assumed to have appreciated for risk weight purposes. The 10% decline trigger requires immediate revaluation (or applying a standard haircut) under the SA approach. For IRB, the LTV at origination must be used unless the institution has evidence of market improvement.

---

### `07_default_rate_history.py` — Stage B

**Purpose:** Compute rolling 12-month default rates across all series dimensions, estimate the implied Vasicek asset correlation, and export December annual `book_snapshot` Parquet partitions.

**Mathematical / analytical output:**
- `default_rate_history_mart`: for each observation month × (whole book / era / segment / state), `performing_loans`, `bad_loans_12m`, `default_rate_count` (= bad/performing, only for `window_complete ≤ 2024-12`).
- `implied_correlation_mart`: Vasicek single-factor model maximum likelihood estimate of asset correlation $\rho$. The model is: each year's default rate $\hat{p}_y = k_y/n_y$ is treated as a noisy observation of the latent systematic factor $X$. MLE over 80+41-point adaptive grid search:
  $$\hat{\rho} = \arg\max_\rho \sum_y \log \int \binom{n_y}{k_y} \Phi\!\!\left(\frac{\Phi^{-1}(\bar{p}) - \sqrt{\rho} z}{\sqrt{1-\rho}}\right)^{k_y} \left[1 - \Phi(\ldots)\right]^{n_y - k_y} \phi(z) \, dz$$
  Numerical integration via trapezoidal quadrature on $z \in [-6.5, 6.5]$ with 41 points.
- `book_snapshot/year=YYYY/`: December 31 annual loan-level files. 44+ features per loan including `bad_12m` (binary outcome), `outcome_12m_status`, `exclusion_reason`, `is_oot` (2022–2024 out-of-time window). These are the **primary inputs for Module 3 PD model development**.

**Concept embodied:** Long-run average PD (LRA) and systemic correlation. The IRB formula for risk-weighted assets requires two parameters: (1) the long-run average PD across the cycle, and (2) the asset correlation $\rho$. CRR Art. 154(3) prescribes $\rho = 0.15$ for retail mortgages; the implied correlation from actual data serves as a validation check. The LRA is computed only over `window_complete` months (observations with a full 12-month forward window, through 2024-12) to avoid dilution by truncated 2025 windows.

---

### `08_sample_population.py` — Stage B

**Purpose:** Define and count the PD modelling sample — loans eligible for inclusion in Module 3 scorecard development.

**Mathematical / analytical output:**
- `sample_population_mart`: counts loans by `population_group` (included / excluded_unseasoned / excluded_in_default / excluded_missing_id / excluded_incomplete_window). Included loans must satisfy: `bad_12m ∈ {0,1}`, `mob ≥ 6`, not currently in default, `first_payment_date IS NOT NULL`.

**Concept embodied:** PD estimation sample eligibility. IRB Art. 174(a) requires the reference data set to be representative of the population the model will score. Loans with fewer than 6 months on book may have masked UPB balances (Fannie Mae withholds early-life balances) and are excluded. Loans currently in default are excluded because their future outcome is not independent — they are already in the event state.

---

### `09_risk_drivers.py` — Stage C

**Purpose:** Compute Information Value (IV) and Population Stability Index (PSI) for origination and lagged behavioural risk drivers across calendar eras. Build the `book_snapshot_behavioural` Parquet partitions.

**Mathematical / analytical output:**
- `book_snapshot_behavioural`: t-1 lagged behavioural features for every December snapshot — `worst_dpd_6m_t1`, `worst_dpd_12m_t1`, `months_since_last_arrears_t1`, `ever_modified_t1`, `balance_paid_down_pct_t1`, `ltv_indexed_t1`, `rate_incentive_t1`.
- `risk_drivers_mart`: per-(era, feature, band) — counts, default rate, WOE, IV contribution. WOE uses +0.5 Laplace smoothing: $\text{WOE}_b = \ln\!\left(\frac{(B_b + 0.5)/(B_\cdot + 0.5K)}{(G_b + 0.5)/(G_\cdot + 0.5K)}\right)$. IV $= \sum_b (\text{dist\_good} - \text{dist\_bad}) \times \text{WOE}$.
- `feature_iv_mart`: per-(era, feature) total IV and PSI.
- `driver_correlation_mart`: Spearman rank correlation matrix over a deterministic 100k-row reservoir sample.

**Concept embodied:** Information Value as a feature pre-selection metric. IV < 0.02 = useless, 0.02–0.1 = weak, 0.1–0.3 = medium, >0.3 = strong. PSI > 0.25 signals significant population shift (potential model instability) between the development era and the target era. The t-1 lag rule ensures no features are taken from within the 12-month outcome window.

---

### `10_segmentation.py` — Stage C

**Purpose:** Formally test candidate model segments using Chi-square, Kolmogorov-Smirnov, and symmetric KL divergence. Assess depth-4 risk-cell interaction pockets and 5-year data sufficiency.

**Mathematical / analytical output:**
- `segmentation_mart`: for each of 6 candidate splits, Chi-square $\chi^2 = \sum_{i,j} (O_{ij} - E_{ij})^2 / E_{ij}$ (df=1, exact erfc p-value), binned KS statistic on FICO score distribution, symmetric KL (Jeffrey) divergence on FICO×LTV risk cells.
- `interaction_pockets_mart`: 4-way cells (LTV × FICO × occupancy × region) ranked by default rate; relative risk index (cell DR / portfolio DR).
- `segment_sufficiency_mart`: per-(segment, year) loan count and default count vs. `MIN_DATA_YEARS = 5` threshold (Art. 180(2)(e)).

**Concept embodied:** Segment homogeneity. IRB Art. 170(1)(d) requires that rating grades contain exposures with "sufficiently similar characteristics". A meaningful segment should show statistically different default rates between the two halves (significant Chi-square), similar feature distributions within each half (low KS), but different risk profiles across halves (high KL). The 5-year rule is a regulatory minimum; in practice, 7–10 years covering a full credit cycle is preferred.

---

### `11_default_outcomes.py` — Stage D

**Purpose:** Classify each default episode's resolution and compute net loss, LGD, and loss development triangles for LGD estimation.

**Mathematical / analytical output:**
- `default_outcomes_mart`: per-event — `outcome_category` (credit exit / cured / other exit / end of data), `net_loss` = balance at default − (net sales proceeds + credit enhancement + make-whole − foreclosure costs − preservation costs − recovery costs − holding taxes − taxes), `forced_sale_discount` = $1 - \text{net\_sales\_proceeds} / V_0$.
- `loss_development_mart`: development triangle — cumulative recovery as a percentage of EAD by months since default × vintage, used for Module 4 LGD tail factor estimation.
- `recovery_summary_mart`: per-loan recovery amounts and timelines.

**Concept embodied:** Workout LGD. The bank never loses the full balance — it recovers some value through property sale, mortgage insurance, or government guarantee. LGD = (EAD − present-valued recoveries) / EAD. The PRA requires discounting at a "risk-free rate" (here: FEDFUNDS + 500 bps per D-025). The development triangle is needed because foreclosure is not instant — recoveries arrive over 12–36 months after default and must be discounted.

---

### `12_forbearance.py` — Stage D

**Purpose:** Track loans through active relief plan entries, resolutions, and re-default events. Measure re-default rates at 12 and 24 months post-modification.

**Mathematical / analytical output:**
- `forbearance_mart`: per-loan — relief plan entry/exit dates, plan type (F=forbearance, T=trial modification, R=repayment), resolution code (C=completed, P=payment plan, D=deferral), re-default indicator.
- `redefault_mart`: re-default rates by `event_type` (modification / deferral) × `initial_status_on_entry` × horizon (12m, 24m).

**Concept embodied:** Distressed restructuring recognition and cure rate. Under Art. 178(5A), a loan that cures via modification must remain in probation for 12 months (not the standard 3). The 12-month re-default rate from `redefault_mart` directly validates whether this 12-month window is sufficient — if 20%+ of modifications re-default within 12 months, the probation period is working correctly as a classifier.

---

### `13_economy_links.py` — Stage E

**Purpose:** Measure Pearson correlations between macro-economic series and portfolio default/prepayment rates across observation lags.

**Mathematical / analytical output:**
- `economy_correlations_mart`: for each macro series × rate type (default rate / prepayment rate) × geography (US_NATIONAL / state) × lag (0–12 months), `pearson_corr` and `n_obs`.
- `macro_downturn_mart`: identifies the worst macro observation for each series over the history (used for Module 7 stress scenario calibration).

> [!IMPORTANT]
> FRED series have a 1–2 month publication lag. The `lag_months` in this table represents analyst-chosen observation lag, not adjusted for publication delay. See Module 01 `04_feature_catalogue.py` notes.

**Concept embodied:** Macro conditioning of credit risk. Mortgage default rates are strongly countercyclical — they rise with unemployment and fall with house price appreciation. The lagged correlations identify which macro indicators are leading indicators (i.e., useful for forecasting future default rates in Module 7 stress testing scenarios).

---

### `14_cycle_and_benchmarks.py` — Stage E

**Purpose:** Identify downturn cycle episodes, measure recovery speed, compute 1-month calendar seasonality hazards, and produce a descriptive Age-Period-Cohort (APC) table.

**Mathematical / analytical output:**
- `cycle_mart`: episodes where quarterly annualised default rate exceeds LRA + 1σ. For each episode: `start_quarter`, `peak_quarter`, `end_quarter`, `duration_quarters`, `recovery_halflife_quarters` (quarters from peak to reach 50% of (peak − LRA)).
- `seasonality_mart`: for each calendar month, `monthly_default_hazard = default_starts / performing_loan_months`, `monthly_prepay_hazard`, `monthly_cure_hazard`, and `seasonal_factor = monthly_rate / annual_average`.
- `apc_mart`: defaults and prepayments by cohort_year × age_bucket (0–11m, 12–23m, 24–35m, 36–59m, 60m+) × period_year. Annualised default hazard $= \text{defaults} / \text{loan\_months\_at\_risk} \times 12$.

**Concept embodied:** Seasonality and credit cycle duration. Mortgage defaults and prepayments are seasonal (prepayments peak in summer; defaults may peak in January after holiday spend). These seasonal factors feed Module 7 stress testing. The cycle duration and recovery half-life measure how quickly the portfolio recovers from a downturn — a key input to through-the-cycle vs point-in-time PD calibration.

---

### `15_portfolio_mix.py` — Stage E

**Purpose:** Analyse the portfolio composition (risk factor distributions, geographic and seller concentration), detect Early Payment Default (EPD-3), and measure arrears bounce patterns.

**Mathematical / analytical output:**
- `portfolio_mix_mart`: annual December snapshot means weighted by UPB for FICO, LTV, DTI, note rate by dimension (occupancy, num_units, SA LTV band).
- `concentration_mart`: Herfindahl-Hirschman Index $\text{HHI} = \sum_i s_i^2$ where $s_i$ = balance share of entity $i$. Computed for state, MSA (excluding '00000' sentinel), and seller. HHI ∈ [0,1]; HHI > 0.25 = highly concentrated.
- `early_payment_default_mart`: EPD-3 rate = loans with ≥ 1 DPD in first 3 months on book / eligible loans. Eligibility: `first_obs_mob ≤ 3` and observation window fully covered.
- `arrears_bounce_mart`: loans with ≥ 2 contiguous 0→1→0 DPD cycles within 12 months, by year and segment.

**Concept embodied:** Concentration risk and adverse selection. High EPD-3 rates indicate origination quality problems — loans defaulting within 3 months of first payment typically reflect mortgage fraud, misrepresentation, or originator adverse selection. HHI concentration by seller flags over-reliance on a single origination channel, which is a source of model risk (the future book may differ materially from the reference data). The SA LTV bands align with PRA PS9/24 risk weight schedules.

---

### `16_representativeness.py` — Stage F

**Purpose:** Quantify how representative the reference data set is of the current lending book, and size all Category A (data deficiencies) and Category B (lending/servicing shifts) inputs for the Margin of Conservatism (MoC).

**Mathematical / analytical output:**
- `representativeness_mart`: per-(driver, baseline_window, band) loan shares and PSI. PSI $= \sum_b (A_b - E_b) \ln(A_b / E_b)$ where $A_b$ = current share, $E_b$ = historical share. Three baseline windows: `today_dec_YYYY`, `history_pre_2025`, `history_pre_2022`. Frozen December shares are stored for Module 8 monitoring.
- `data_limits_mart`: 12 quantified limits including unknown-DPD share, masked-balance share, missing FICO/DTI rates, pre-2000 HPI fallback count, territory HPI fallback, accrued interest estimates, restatement events, high-balance loans, HLTV refinance loans, multi-servicer transfers, crisis/COVID era shares.

**Concept embodied:** Margin of Conservatism sizing. PRA SS4/24 §4 requires banks to identify specific gaps between the reference data set and the target portfolio, and add a Margin of Conservatism to the PD/LGD/EAD estimates for each identified gap. Category A gaps are data quality limitations (unknown values, truncation); Category B gaps are population shifts (the current book is riskier or structurally different from the history used to build the model).

---

### `17_survivorship.py` — Stage F

**Purpose:** Measure left-truncation bias — the proportion of loans that were already on book (seasoned) when Fannie Mae began reporting them in the dataset.

**Mathematical / analytical output:**
- `survivorship_mart`: by `cohort_metric` (acquisition_seasoning / credit_history_at_origination), counts loans where `mob_at_first_observation > 3`. `seasoned_gt3m_pct` = truncated loans / total.

**Concept embodied:** Left-truncation and survivorship bias. If a loan is only observed from MOB = 24 onwards (because it was originated in 1998 but Fannie Mae data only starts in 2000), the early-life default risk is unobserved. The loans that survived to MOB=24 are systematically better quality than the original population — they already avoided the high early-life default risk. This biases vintage curve estimates and must be documented as a Category A data limitation.

---

### `18_portfolio_findings.py` — Stage G

**Purpose:** Auto-generate the Module 2 findings markdown report by querying all 25 finished mart tables. No calculations — only mart reads and formatting.

**Mathematical / analytical output:** `18_portfolio_findings.md` — structured summary of all key numbers from Module 2: balance roll-forward status, default rates, LRA, implied correlation, top IVs, outcome distributions, macro correlations, HHI, PSI, survivorship, MoC limits, and the Module 3–8 mart handover register.

**Concept embodied:** Separation of computation from reporting. By generating the findings report from pre-computed marts rather than re-running calculations inline, the report is always consistent with the mart state and can be regenerated in 1.3s without re-running any analysis.

---

### `run_module2.py` — Orchestrator

**Purpose:** Execute scripts 00–18 in dependency order, streaming stdout to both the console and a `.scratch/module2_run_sample.log` file. Stops on the first script failure.

**Mathematical / analytical output:** No modelling. Provides `--from-step` flag to restart from a specific script, `--dry-run` to preview execution plan, `--log` to override log path.

**Concept embodied:** Fail-fast pipeline with partial resume. Rather than silently continuing when a script fails (and producing downstream marts with invalid inputs), `run_module2.py` exits on the first non-zero exit code. The `--from-step` flag allows resuming from where a fix was applied without re-running the entire 102-second pipeline.
