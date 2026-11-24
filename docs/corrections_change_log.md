# V4 Build Plan Corrections Change Log

> **Repository:** `E:\Repos\V4_bank-credit-risk-platform`  
> **Target Plan:** `docs/v4_build_plan_revised.md`  
> **Backup Created:** `docs/build_plan/v4_build_plan_revised_before_corrections.md`  
> **Date:** 14 November 2026  
> **Authoritative Basis:** UK PRA Rulebook (1 January 2027), PRA Policy Statement PS1/26, UK-adopted IFRS 9, PRA Supervisory Statements SS3/24, SS4/24, and SS1/23.  
> **Audience:** Chief Risk Officer and Senior Model Risk Oversight Committee.

---

## 1. Executive Summary

This document provides a line-by-line audit trail of all corrections, regulatory reconciliations, and architectural refinements applied to `docs/v4_build_plan_revised.md`. All fourteen reviewer findings, along with the foundational gaps in Block E (data sampling, balance sheet definitions, testable hypothesis framing, folder structures, and execution design), have been resolved.

Every formula, regulatory parameter, and SQL state machine in the updated build plan has been tested and independently verified using Python 3.12 and DuckDB 1.5.3.

---

## 2. Section-by-Section Change Audit

| # | Topic | Plan Section | Previous Plan (Defect) | Corrected Plan (Approved Implementation) | Primary Authority |
|:---|:---|:---|:---|:---|:---|
| **1** | Standardised Risk Weights | Module 6 (`06_basel_capital`) | Applied flat LTV banding table to all mortgages (derived from older Basel II / draft CRR text). | Implemented PRA Rulebook Article 124F loan-splitting for Owner-Occupied (`P`) and Second Homes (`S`): 20% on exposure up to 55% property value, 75% counterparty weight (Article 124L) on remainder. Investor loans (`I`) evaluated under Article 124G Table 6B (80% LTV = 50% risk weight). | PRA Rulebook Part: Credit Risk: Standardised Approach, Articles 124E, 124F, 124G, 124L; PS1/26 |
| **2** | Retail AIRB Vasicek Formula | Module 6 (`06_basel_capital`) | Included corporate maturity adjustment factor ($M = 2.5$) in retail mortgage RWA formula, overstating RWA by ~26%. | Omitted maturity adjustment factor entirely: $K = \text{LGD} \times [\text{PD}_{cond} - \text{PD}]$. Retail exposures under Article 154 / CRE31.14 are exempt from maturity scaling. | PRA Rulebook Part: Credit Risk: Internal Ratings Based Approach, Article 154; BCBS CRE31.13 & CRE31.14 |
| **3** | LGD Cash Flow Discount Rate | Module 4 (`04_lgd_ead`) | Labeled 9.0% as a generic LGD downturn floor. | Clarified that the statutory input floor is 5.0% (Article 164(4)(a)). Replaced SONIA with Federal Funds Effective Rate (EFFR) at default date + 500 bps (substituting for SONIA+500 bps under SS4/24 §13.16), floored at 9.0% for downturn LGD under SS4/24 §13.17. | PRA SS4/24 paragraphs 13.16 & 13.17; PRA Rulebook Article 164(4)(a) |
| **4** | Vasicek State Inversion Formula | Module 7 (`07_stress_testing`) | Formula inverted the numerator sign ($z^* = (\Phi^{-1}(\text{DR})\sqrt{1-\rho} - \Phi^{-1}(\text{PD})) / \sqrt{\rho}$), yielding positive shocks under severe stress. Used average-PD shortcut for multi-grade books. | Fixed sign: $z^* = (\Phi^{-1}(\text{PD}_{TTC}) - \Phi^{-1}(\text{DR}_{stress})\sqrt{1-\rho}) / \sqrt{\rho}$, ensuring adverse stress yields negative $z^*$. Specified 1D root-finding (`scipy.optimize.brentq`) for multi-grade books. | ASRF Framework; Vasicek (2002); Gordy (2003) |
| **5** | PIT / TTC Relationship | Module 3 (`03_rating_and_pd`) | Used ungrounded blending formula ($w = \sqrt{\rho/(1-\rho)}$) and arbitrary alpha weights. | Calibrates rating grades directly to the Long-Run Average Default Rate (LRADR) including the 2007–2009 downturn. Measures model cyclicality $\alpha \in [0, 1]$ directly against the 30% cap under SS4/24 §11.38. Decoupled Step 12 from Module 7. | PRA SS4/24 paragraphs 11.38 & 11.42 |
| **6** | Build Order Dependency | Build Order Table | Step 12 (PIT PD) had circular/forward dependency on Step 28 (Satellite models). | Step 12 decoupled to depend only on Step 10 (Application scorecard). Step 13 (TTC PD) depends on Step 6 (Default engine). Step 28 connects macro models without circularity. | Structural Design |
| **7** | Default Definition & Restructuring | Module 2 (`02_portfolio_analytics`) | Arbitrary DPD candidate thresholds (45, 75, 105 DPD). Generic UTP triggers. | Analysis structured in whole months delinquent ($m \in \{0, 1, 2, \dots\}$) and whole-month DPD ($m \times 30$). `Modification_Flag == 'Y'` established as the sole restructuring trigger, described as a simplifying choice. Forbearance is a Stage 2 trigger. | PRA SS3/24; PRA Rulebook Article 178 |
| **8** | Probation State Machine SQL | Module 2 (`02_portfolio_analytics`) | Flawed window function query failed on non-instant cures, post-cure 30 DPD, and multiple defaults. | Replaced with recursive state machine query in DuckDB. Proved 70/70 rows matching on 6 test loans. Cites Article 178(5) (3 clean months for arrears) and Article 178(5A) (12 clean months for restructuring). No EBA reference. | PRA Rulebook Article 178(5) & 178(5A) |
| **9** | Raw Data Layout & Ingestion | Module 1 (`01_data_foundation`) | Documented legacy two-file structure (`_acq.txt`, `_perf.txt`). | Documented Fannie Mae's single consolidated 110-field pipe-delimited file layout. `field_map.py` establishes the canonical 110-field position and type mapping. | Fannie Mae Single-Family Loan Performance Specification |
| **10** | Competing Risks & Exits | Module 2 & Module 5 | Suggested `lifelines` Fine-Gray regression. | Implemented non-parametric Aalen-Johansen Cumulative Incidence Function (CIF) directly in DuckDB SQL. Voluntary prepayment is competing terminal event; administrative removals/sales censored for default curve; note sales remain loss outcomes for LGD. | Aalen-Johansen (1978); IFRS 9 §B5.5.40 |
| **11** | Stress Testing Framework | Module 7 (`07_stress_testing`) | Referenced outdated "Biennial Exploratory Scenario" and flat 4.5% hurdle. | Framed under the Bank of England 2025 Bank Capital Stress Test (BCST). Total bank hurdle set to 6.2% (4.5% Pillar 1 + 1.7% assumed Pillar 2A); 4.5% is the breaking point. | Bank of England 2025 BCST Key Elements |
| **12** | Model Risk Management | Module 8 (`08_model_risk_mgmt`) | Centered on US Fed SR 11-7 with misplaced paragraph citations (§4). | Primary standard: UK PRA SS1/23 (effective 17 May 2024, updated April 2026). Mapped to Principle 4 (Validation/monitoring) and Principle 5 (Risk mitigants/governance). US Fed SR 11-7 / SR 26-2 maintained as secondary reference. | PRA SS1/23 Principles 4 & 5; Federal Reserve SR 11-7 |
| **13** | Scorecard & Validation Standards | Module 3 (`03_rating_and_pd`) | Used "Basel-standard" 1:1 odds at 600. Basel 3-zone traffic lights (market risk). | Scorecard scaling calibrated to chosen anchor: 50:1 odds at 650, PDO = 20. Exact binomial test at 95% (amber) and 99% (red) confidence thresholds per SS4/24 §18.17 and BCBS CRE36.87. | PRA SS4/24 paragraph 18.17; BCBS CRE36.87 |
| **14** | Economic Capital Scope | Module 6 (`06_basel_capital`) | Ambiguous Monte Carlo simulation scope with unneeded granularity adjustments. | Closed-form Vasicek model implemented for the baseline build ($\text{EC} = \text{VaR}_{99.9\%} - \text{EL}$). Portfolio of 100k+ loans is asymptotically granular. Multi-factor simulation moved to Later Extensions. | Vasicek (2002); Gordy (2003) |
| **15A** | Data Scope & Sampling | Module 1 (`01_data_foundation`) | Unclear cohort span and disk management on 16 GB RAM system. | 2000Q1 to 2008Q4 (36 quarters) capturing 2007–2009 downturn. Fixed 10% seeded random sample of loans per cohort saved in `sampled_loans` table (1.5–2.0M loans, 25–30M rows, ~1.5–2.0 GB in DuckDB; full load ~15–20 GB). | Implementation Architecture |
| **15B** | Standardized Balance Sheet | Module 7 (`07_stress_testing`) | No standardized balance sheet for stress testing. | Assets = 11,765 (Mortgages 10,000, Gilts 1,765); Liabilities = 9,800 deposits, 1,000 wholesale, 200 Tier 2, 765 CET1 equity. 14.0% starting CET1 ratio evaluated on SA RWA. All items labeled as assumed. | Stress Test Baseline Specification |
| **15C** | CRO-Facing Tone | Entire Document | Empirical assertions stated prior to running scripts. | Re-framed unverified empirical claims as testable quantitative hypotheses and acceptance criteria. | Professional Integrity Standards |
| **15D** | Repository Layout & Testing | Repository Structure | Module import collision risks with leading digits. | Numbered folders and files preserved. Pytest test suite uses a single test helper (`tests/test_helpers.py` via `importlib.util.spec_from_file_location`) to load modules by file path cleanly. | Python Testing Architecture |
| **15E** | Output Conventions | Entire Document | Mixed currency and country references. | All outputs and tables present plain numeric amounts with no currency symbols and no country names; original regional identifiers from the dataset are preserved. | Clean Data Reporting Standard |
| **15F** | Memory & DuckDB Execution | Entire Document | Inefficient Pandas data movement in 16 GB RAM environment. | All heavy panel operations, roll rates, state machines, and CIF calculations run natively in DuckDB vectorized SQL; Python receives aggregated arrays. | High-Performance Analytics Standard |

---

## 3. Mathematical & Numerical Verifications

All numerical examples in the corrected build plan were executed and validated in Python 3.12 and DuckDB 1.5.3:

### 3.1 Standardised Approach (Article 124F vs Article 124G Table 6B)
*Exposure:* 80,000 loan on 100,000 property valuation (80% LTV).
- **Article 124F (Owner-Occupied / Second Home):**
  - Secured portion: $\min(80,000, 0.55 \times 100,000) = 55,000$ at $20\% = 11,000$ RWA.
  - Residual portion: $80,000 - 55,000 = 25,000$ at $75\% = 18,750$ RWA.
  - **Total RWA:** $11,000 + 18,750 = 29,750$ (Effective risk weight = **37.19%**).
- **Article 124G Table 6B (Investor / Buy-to-Let):**
  - 80% LTV falls in band $60\% < \text{LTV} \le 80\%$, assigning a flat **50% risk weight**.
  - **Total RWA:** $80,000 \times 50\% = 40,000$ (Effective risk weight = **50.00%**).
- *Status:* **Verified.**

### 3.2 Retail AIRB Vasicek vs Corporate Overstatement
*Parameters:* $\text{PD} = 1.0\%$, $\text{LGD} = 20.0\%$, $\rho = 0.15$, $\text{EAD} = 100,000$.
- **Retail Formula (CRE31.14 / Article 154):**
  $$\text{PD}_{conditional} = \Phi\left(\frac{\Phi^{-1}(0.01) + \sqrt{0.15}\Phi^{-1}(0.999)}{\sqrt{1-0.15}}\right) = 11.026\%$$
  $$K = 0.20 \times (0.11026 - 0.01000) = 0.020053$$
  $$\text{RWA} = 0.020053 \times 12.5 \times 100,000 = 25,066.19 \quad (25.07\% \text{ weight})$$
- **Corporate Formula with $M = 2.5$:**
  $$b = (0.11852 - 0.05478 \times \ln(0.01))^2 = 0.13745$$
  $$\text{Maturity Factor} = \frac{1 + (2.5 - 2.5)b}{1 - 1.5b} = \frac{1}{1 - 1.5 \times 0.13745} = 1.25977$$
  $$\text{RWA}_{corp} = 25,066.19 \times 1.25977 = 31,577.67 \quad (31.58\% \text{ weight})$$
- *Status:* **Verified.** Removing the corporate maturity factor eliminates a 25.98% overstatement of retail RWA.

### 3.3 Vasicek State Inversion
*Parameters:* $\text{PD}_{TTC} = 1.0\%$, $\rho = 0.15$, $\text{DR}_{stress} = 5.0\%$.
- **Corrected Formula:**
  $$z^* = \frac{\Phi^{-1}(0.01) - \Phi^{-1}(0.05)\sqrt{1-0.15}}{\sqrt{0.15}} = \frac{-2.326348 - (-1.644854 \times 0.921954)}{0.387298} = -2.0911$$
- **Reconstruction Check:**
  $$\text{PD}_{cond} = \Phi\left(\frac{\Phi^{-1}(0.01) - \sqrt{0.15}(-2.0911)}{\sqrt{1-0.15}}\right) = \Phi(-1.644854) = 5.000\%$$
- **Flawed Formula (prior plan):**
  $$z^*_{wrong} = +2.0911 \implies \text{PD}_{cond} = \Phi(-3.4013) = 0.0335\% \quad (\text{massive error})$$
- **Multi-Grade Portfolio Root-Finding:**
  Two-grade book (Grade 1: 0.5%, Grade 2: 2.0%, equal weights, target stressed DR = 4.0%).
  Solving $\sum_g w_g \text{PD}_g(z^*) = 0.040$ via `scipy.optimize.brentq` yields $z^* = -1.6459$, confirming $\text{DR}(z^*) = 4.000\%$.
- *Status:* **Verified.**

### 3.4 Scorecard Scaling
*Parameters:* Anchor score = 650 at 50:1 odds; PDO = 20.
$$\text{Factor} = \frac{20}{\ln(2)} = 28.853901, \quad \text{Offset} = 650 - 28.853901 \times \ln(50) = 537.1229$$
$$\text{Score}(50:1) = 537.1229 + 28.853901 \times \ln(50) = 650.0$$
$$\text{Score}(100:1) = 537.1229 + 28.853901 \times \ln(100) = 670.0$$
- *Status:* **Verified.** Exactly doubles odds every 20 points.

### 3.5 Pluto-Tasche Low-Default Estimation
*Parameters:* $n = 500$ loans, $k = 3$ observed defaults, $\alpha = 0.95$ confidence.
- **General Beta Quantile Formula:**
  $$\text{PD}_{upper} = \text{BetaQuantile}(0.95; 3 + 1, 500 - 3) = \text{BetaQuantile}(0.95; 4, 497) = 1.543\%$$
- **Flawed $k=0$ Shortcut (prior plan):**
  $$\text{PD}_{upper, k=0} = 1 - (1 - 0.95)^{1/501} = 0.596\% \quad (\text{understates default risk by 61\%})$$
- *Status:* **Verified.**

---

## 4. DuckDB Recursive Probation State Machine Test Results

The recursive state machine query embedded in `02_portfolio_analytics/02_default_engine.py` was executed in DuckDB against a test panel of 6 distinct loan trajectories spanning 70 monthly observation periods.

| Loan ID | Archetype Description | Total Months | Default Trigger | Required Clean Months | Months in Default / Probation | Month Exiting to Performing | Matching Rows | Status |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Loan 1** | Chronic delinquency; never cures | 8 | 90 DPD (m5) | 3 | Months 5–8 | Never exits | 8 / 8 | PASS |
| **Loan 2** | Standard arrears cure | 10 | 90 DPD (m5) | 3 | Months 5–8 | Month 9 | 10 / 10 | PASS |
| **Loan 3** | Probation slip and recovery | 11 | 90 DPD (m5) | 3 | Months 5–10 (slip at m7 resets clock) | Month 11 | 11 / 11 | PASS |
| **Loan 4** | Post-cure minor delinquency | 11 | 90 DPD (m5) | 3 | Months 5–8 (m10 reaches 30 DPD) | Month 9 (stays Performing at m10) | 11 / 11 | PASS |
| **Loan 5** | Cure, probation completion, re-default | 13 | 90 DPD (m5, m12) | 3 | Months 5–8, Months 12–13 | Month 9 (re-defaults at m12) | 13 / 13 | PASS |
| **Loan 6** | Distressed restructuring (modification) | 17 | Modification (m4) | 12 | Months 4–16 | Month 17 | 17 / 17 | PASS |
| **Total** | **Comprehensive Panel Verification** | **70** | — | — | — | — | **70 / 70** | **100% PASS** |

*Verification summary:* 0 mismatches across all 70 loan-months. The loan remains in In-Default status throughout the probation period; resets immediately upon delinquency; and does not re-default on 30 DPD post-cure.

---

## 5. Five Verification Proof Checks Summary

| Check # | Description | Criteria | Result | Notes |
|:---|:---|:---|:---:|:---|
| **Check 1** | Forbidden Leftovers Search | 20 terms checked case-insensitively (`Maturity Adjustment`, `MATURITY_RETAIL`, `LGD_DOWNTURN_FLOOR`, `Biennial`, `SR 11-7 §`, `Fine-Gray`, `_acq`, `_perf`, `45 DPD`, `75 DPD`, `105 DPD`, `Basel-standard`, `Moody`, `blend`, `1:1`, `granularity`, `Article 125`, `SOFR`, `EBA`, `§15`) | **PASS** | 0 hits across all 20 forbidden search patterns. |
| **Check 2** | Numerical Formula Evaluation | Evaluated SA weights, retail AIRB, state inversion, scorecard scaling, and Pluto-Tasche | **PASS** | All numerical values match mathematical assertions and code proofs. |
| **Check 3** | Citation & Regulatory Mapping | Confirmed presence and validity of 16 key regulatory citations (Rulebook Articles, SS3/24, SS4/24, SS1/23, CRE, BCST) | **PASS** | All citations verified against PRA Rulebook 1 Jan 2027 and PS1/26. |
| **Check 4** | Parameter Block Reconciliation | Checked all 24 parameters in `regulatory_parameters.py` against body text | **PASS** | 100% concordance between configuration constants and narrative text. |
| **Check 5** | Whole-Plan Consistency Read | Audited build order dependencies, folder names, balance sheet totals, and sampling rules | **PASS** | 34 steps verified; circular dependency between Step 12 and Step 28 eliminated. |

---

## 6. Open Items & Project Status

There are **zero remaining defects or unresolved decisions**. All fourteen reviewer inquiries and all six Block E architectural gaps have been resolved, codified into the revised build plan, and proven by executable code.
