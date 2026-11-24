# V4 Build Plan — Corrections Proposal (Final)

> **Plan file:** `docs/build_plan/v4_build_plan_revised.md`  
> **Prepared by:** Quantitative Credit Risk Audit  
> **Status:** Final proposal, verified against primary official sources and executed DuckDB tests.

---

## A. Summary Table

| Point | Topic | Verdict | One-line reason |
|:---|:---|:---|:---|
| 1 | Standardised risk weights for residential mortgages | **Plan is wrong** | The plan mixes whole-loan weights with loan-splitting wording. The PRA rule is Article 124F/L (20% up to 55% valuation, 75% on remainder for natural persons); investor loans take Article 124G Table 6B (80% LTV = 50% risk weight, not 45%). |
| 2 | IRB capital formula for retail mortgages | **Plan is wrong** | Retail IRB has no maturity adjustment (CRE31.13). The formula is CRE31.14 with fixed $\rho=0.15$ (Article 154(3)); the 1.06 scalar is abolished under Basel 3.1. |
| 3 | The 9% in LGD | **Plan is wrong** | The 9% in SS4/24 §13.17 is a minimum discount rate for downturn cash flows, not an LGD floor. The statutory LGD floor is 5% (Article 164(4)(a)); the USD discount benchmark is EFFR at default + 500 bps (floored at 9%). |
| 4 | Vasicek state inversion | **Plan is wrong** | The plan omits a minus sign in $z^*$, causing stress to collapse defaults. On a multi-grade book, $z^*$ must be solved numerically ($z^* = -1.646$ exact vs $-1.620$ shortcut). |
| 5 | PIT/TTC blend weight $w = \sqrt{\rho / (1-\rho)}$ | **Plan is wrong** | $\sqrt{\rho/(1-\rho)}$ is a probit factor loading, not a probability weight. SS4/24 §11.41 prohibits pure TTC; calibration must anchor master scale grades to LRADR including downturn (2007–2009) and measure cyclicality against §11.38. |
| 6 | Build order circular dependency | **Plan is wrong** | Step 12 (PIT PD) depends on Step 28 (macro satellites), creating an impossible cycle. Decouple Step 12 by fitting a direct historical ODR macro overlay. |
| 7 | Default definition analysis | **Plan is partly wrong** | Whole-month data cannot test 45/75/105 DPD. 90 DPD is statutory (Article 178(1)(b)); distressed restructuring is Article 178(3)(d); retail materiality is Article 178(2)(d) (above £0 and 0%); modification flag is a simplifying choice; probation is Article 178(5)(a) and 178(5A). |
| 8 | Probation SQL logic | **Plan is wrong** | The plan's query marked active defaults as 'Performing', failed to reset probation streaks on slips, and duplicated rows. The corrected recursive query matches 100% of rows across all 6 test loans. |
| 9 | Fannie Mae file layout | **Plan is wrong** | Fannie Mae disclosures use a single consolidated 110-field layout. DTI is an origination attribute populated since 2000Q1; the contradictory missingness notes must be removed. |
| 10 | Competing risks and `lifelines` | **Plan is wrong** | `lifelines` lacks Fine-Gray regression. Compute discrete Aalen-Johansen CIF natively in DuckDB SQL; use `lifelines.AalenJohansenFitter` on a validation sample. Prepayment is the competing exit; sales/removals are censored. |
| 11 | Stress test references | **Plan is partly wrong** | 2025 exercise was the Bank Capital Stress Test (BCST). The bank's hurdle is 4.5% Pillar 1 + 1.7% assumed Pillar 2A = 6.2%; 4.5% is the breaking point (statutory Pillar 1 depletion). |
| 12 | SR 11-7 status | **Plan is partly wrong** | SR 11-7 was superseded by SR 26-2 in April 2026. UK PRA SS1/23 (effective 23 April 2026) is the primary standard; Principle 4 covers validation and monitoring, Principle 5 covers risk mitigants. |
| 13 | Labels claiming official authority | **Plan is wrong** | Basel traffic lights apply to market risk VaR (MAR32), not PD. Score 600 at 1:1 odds is a chosen anchor, not a Basel rule. The Pluto-Tasche formula shown applies only to $k=0$ defaults; use the general Beta quantile formula for numbered Grade 1. |
| 14 | Economic capital definitions & scale | **Plan is wrong** | EC is $\text{VaR}_{99.9\%} - \text{EL}$. Single-factor simulation is redundant against the closed-form Vasicek distribution. Loan-level simulation ($50k \times 150k$) crashes a 16 GB laptop. Implement closed form in this build; multi-factor simulation is a later extension. |

---

## B. Point-by-Point Analysis

### B1. Standardised Risk Weights for Residential Mortgages (06_basel_capital/01_standardised_rwa.py)

#### 1. What the plan says
> "Basel 3.1 SA risk weights for residential mortgage exposures are applied by LTV band — the weight applies to the portion of the loan within each band, not to the whole loan.
> 
> | LTV Band | Risk Weight |
> | ≤ 50% | 20% |
> | 50–60% | 25% |
> | 60–80% | 30% |
> | 80–90% | 40% |
> | 90–100% | 50% |
> | > 100% | 70% |
> 
> Property value: Use value at origination. Updated at least every 5 years; updated immediately if evidence of significant decline (§15 of the PRA's Credit Risk Part of the Rulebook)." (lines 567–578).

Appears also in lines 59, 166, and 884.

#### 2. Reviewer's concern
The table matches Basel's whole-loan table (CRE20.81), but the caption claims the weight applies to the portion in each band. Under the PRA Rulebook (version of 1 January 2027), the rule is Article 124F (loan-splitting: 20% on the part up to 55% of property value, counterparty weight on the remainder under Article 124L). Article 124D governs valuation, and Article 124E/124G governs income-producing loans. Under Table 6B (Article 124G), an 80% LTV loan takes 50%, not 45%.

#### 3. Primary source check
- **Document:** PRA Rulebook (CRR), Credit Risk: Standardised Approach (CRR) Part (version effective 1 January 2027, as set out in PS1/26 and PS9/24).
- **Articles:** Article 124D(5), 124E, 124F, 124G (Table 6B), 124L.
- **Date:** Final rules published in PS1/26 (January 2026), in force 1 January 2027.
- **URL:** [PRA Rulebook Credit Risk SA 01-01-2027](https://www.prarulebook.co.uk/pra-rules/credit-risk---standardised-approach-crr/01-01-2027)
- **Date checked:** 14 November 2026.
- **Exact rules (in summary):**
  - **Article 124F(1):** For residential property exposures not materially dependent on property cash flows: the portion up to 55% of the property value receives a **20% risk weight**.
  - **Article 124L:** The remaining portion of the exposure receives the counterparty risk weight (75% for natural persons under Article 123).
  - **Article 124E & 124G (Table 6B):** If repayment is materially dependent on cash flows generated by the property (investor / buy-to-let loans), loan-splitting does not apply. The entire exposure receives the whole-loan risk weight from Table 6B:
    $$\le 50\%: 30\%, \quad 50–60\%: 35\%, \quad 60–70\%: 40\%, \quad 70–80\%: \mathbf{50\%}, \quad 80–90\%: 60\%, \quad 90–100\%: 75\%, \quad >100\%: 105\%$$
    Second homes (occupancy type 'S') are personal residences occupied by the borrower/family where repayment comes from personal borrower income (not rent), so they qualify under Article 124F.
  - **Article 124D(5):** Property valuation requires independent valuation or statistical valuation models. Revaluations are required upon material price declines, with monitoring backstops (at least every 5 years for residential property).

#### 4. Independent check (run in Python)
Consider an £80,000 loan on a £100,000 property (80% LTV):
- **PRA Article 124F/124L (Owner-occupied 'P' and Second Home 'S'):**
  - Part up to 55% of property value (£55,000): $55,000 \times 20\% = £11,000$ RWA.
  - Remaining part (£25,000): $25,000 \times 75\% = £18,750$ RWA.
  - Total RWA = $11,000 + 18,750 = \mathbf{£29,750}$ (effective risk weight = $\mathbf{37.19\%}$).
- **PRA Article 124G Table 6B (Investor 'I'):**
  - 80% LTV falls in band $70\% < \text{LTV} \le 80\%$, where the risk weight in Table 6B is **50%** (not 45%).
  - Total RWA = $80,000 \times 50\% = \mathbf{£40,000}$ (effective risk weight = $\mathbf{50.00\%}$).

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. Replace the whole-loan table with PRA Article 124F/124L loan-splitting for owner-occupied (`P`) and second-home (`S`) loans:
   $$\text{RWA} = \min(\text{UPB}, 0.55 \times V) \times 20\% + \max(0, \text{UPB} - 0.55 \times V) \times 75\%$$
2. For investor loans (`I`), apply the whole-loan table under Article 124G (Table 6B).
3. Value $V$: use origination property value, updated downwards using the FHFA regional House Price Index; state explicitly that upward revaluations are not modelled.

#### 7. Devesh decisions incorporated
- Decision 1 accepted: Owner-occupied (`P`) and Second Home (`S`) take Article 124F; Investor loans (`I`) take Article 124G Table 6B.
- Decision 2 accepted: Property value updated via FHFA regional HPI; upward revaluations not modelled.

---

### B2. IRB Capital Formula for Retail Mortgages (06_basel_capital/02_airb_vasicek.py)

#### 1. What the plan says
> "$$K = \text{LGD} \times \left[\text{PD}_{conditional} - \text{PD}\right] \times \text{Maturity Adjustment}$$
> $$\text{RWA} = K \times 12.5 \times \text{EAD}$$
> - Correlation: $\rho = 0.15$ (fixed under Basel 3.1 for retail mortgages)
> - Maturity simplification for retail: $M = 2.5$ years" (lines 597–604, 780).

#### 2. Reviewer's concern
Retail residential mortgage exposures have no maturity adjustment under Basel IRB (CRE31.13). The retail formula is CRE31.14. Correlation $\rho = 0.15$ is set in PRA Rulebook Article 154(3) and dates from Basel II (2006). The 1.06 supervisory scalar was removed under Basel 3.1.

#### 3. Primary source check
- **Document:** BIS Basel Framework CRE31; PRA Rulebook (CRR), Credit Risk: Internal Ratings Based Approach (CRR) Part (version 1 January 2027).
- **Articles:** BIS CRE31.13, CRE31.14; PRA Rulebook Article 154(3).
- **Date:** In force 1 January 2027.
- **URL:** [BIS CRE31](https://www.bis.org/basel_framework/chapter/CRE/31.htm); [PRA Rulebook Credit Risk IRB 01-01-2027](https://www.prarulebook.co.uk/pra-rules/credit-risk-internal-ratings-based-approach-crr/01-01-2027)
- **Date checked:** 14 November 2026.
- **Exact rules (in summary):**
  - **CRE31.13:** The maturity adjustment ($M$) does not apply to retail exposures.
  - **CRE31.14 & Article 154(3):** For retail exposures secured by residential property, the asset correlation $R$ is fixed at 0.15. The capital requirement is:
    $$K = LGD \times N\left( \frac{G(PD) + \sqrt{R} \times G(0.999)}{\sqrt{1-R}} \right) - LGD \times PD$$
    $$RWA = K \times 12.5 \times EAD$$
  - The 1.06 scalar from Basel II is removed.

#### 4. Independent check (run in Python)
With $\text{PD} = 1.0\%$, $\text{LGD} = 20.0\%$, $\rho = 0.15$, $\text{EAD} = £100,000$:
- $\text{PD}_{cond} = 11.026\%$.
- $K = 0.20 \times (0.11026 - 0.01) = 0.020053$.
- Retail RWA = $0.020053 \times 12.5 \times 100,000 = \mathbf{£25,066.19}$ (effective risk weight = $\mathbf{25.07\%}$).
- Plan's formula with corporate maturity adjustment ($M=2.5$): factor 1.2598 $\to$ RWA = $\mathbf{£31,578.62}$ (26% overstatement).

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. Remove `\times \text{Maturity Adjustment}` from the formula in Module 6.
2. Delete `MATURITY_RETAIL_YEARS = 2.5` from `regulatory_parameters.py`.
3. Cite BIS CRE31.13 and CRE31.14, and PRA Rulebook Article 154(3). Note correlation 0.15 dates from Basel II and 1.06 scalar is removed.

#### 7. Devesh decisions incorporated
- Decision 4 accepted: PD floor 0.10% (Article 163(1)(b)), stated as a choice treating the book as if UK residential property.

---

### B3. The 9% in LGD (04_lgd_ead/01_workout_lgd.py and regulatory_parameters.py)

#### 1. What the plan says
> "For regulatory capital: SONIA + 500 bps (SS4/24 §13.16). For downturn LGD floor: 9% (§13.17)." (line 443).
> ```python
> LGD_DOWNTURN_FLOOR_PCT = 9  # Min 9% for downturn LGD. SS4/24 §13.17
> LGD_INPUT_FLOOR_RESIDENTIAL_PCT = 5  # Input floor. Basel 3.1 / PRA
> ``` (lines 767–768).

#### 2. Reviewer's concern
SS4/24 paragraph 13.17 specifies a minimum discount **rate** of 9% for downturn recovery cash flows, not a floor on the resulting LGD value. The statutory LGD floor is 5% (Article 164(4)(a)). Furthermore, SONIA is sterling-only; a dollar benchmark with history back to 2000 is required.

#### 3. Primary source check
- **Document:** Bank of England Supervisory Statement SS4/24, January 2026 update; PRA Rulebook (CRR) Credit Risk: IRB Part, Article 164(4)(a); Federal Reserve Bank of New York (FRED: `FEDFUNDS`).
- **Date:** In force 1 January 2027; FRED series active from 1 July 1954.
- **URL:** [Bank of England SS4/24](https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/supervisory-statement/2026/ss424-january-2026-update.pdf); [FRED FEDFUNDS](https://fred.stlouisfed.org/series/FEDFUNDS)
- **Date checked:** 14 November 2026.
- **Exact rules (in summary):**
  - **SS4/24 §13.16:** For long-run average LGD, discount recovery cash flows using an overnight risk-free rate at the date of default plus 5 percentage points.
  - **SS4/24 §13.17:** For downturn LGD, use a discount rate of at least 9%.
  - **Article 164(4)(a):** For retail exposures secured by residential property, the LGD input floor is **5%**.
  - **USD Benchmark Choice:** The Federal Funds Effective Rate (EFFR) is the US unsecured overnight interbank rate published daily by the NY Fed since 1954. It is the exact US operational equivalent to UK SONIA. (SOFR only began publication in April 2018, so it cannot be used for defaults occurring between 2000 and 2017).

#### 4. Independent check (run in Python)
Discounting £10,000 recovery received 3 years post-default:
- At long-run rate (EFFR 4% + 5% = 9%): $\text{PV} = 10,000 / (1.09)^3 = £7,721.83$.
- Stressed recovery of 97% produces $\text{LGD} = 3\%$. This is valid under the 9% cash flow discount rate rule, but is bound upwards to **5.0%** by the Article 164(4)(a) input floor.

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. In `regulatory_parameters.py`:
   ```python
   LGD_DISCOUNT_BENCHMARK = "EFFR"              # Federal Funds Effective Rate (FRED: FEDFUNDS, 1954-present)
   LGD_DISCOUNT_SPREAD_BPS = 500                # EFFR + 500bps for long-run LGD (SS4/24 §13.16 principle)
   LGD_DOWNTURN_DISCOUNT_RATE_MIN_PCT = 9.0     # Minimum discount rate of 9% for downturn recovery cash flows (SS4/24 §13.17)
   LGD_INPUT_FLOOR_RESIDENTIAL_PCT = 5.0        # Statutory LGD input floor for residential mortgages (PRA Article 164(4)(a))
   ```
2. Update Module 4 text to apply the 9% minimum discount rate to cash flows, while applying the 5% input floor to the resulting LGD estimate.

#### 7. Devesh decisions incorporated
- Decision 3 accepted: EFFR at default date + 500 bps (floored at 9.0% for downturn LGD).

---

### B4. Vasicek State Inversion Sign (07_stress_testing/01_satellite_models.py)

#### 1. What the plan says
> "$$z^* = \frac{\Phi^{-1}(\text{DR}_{stress}) \cdot \sqrt{1-\rho} - \Phi^{-1}(\text{PD}_{TTC})}{\sqrt{\rho}}$$" (line 647).

#### 2. Reviewer's concern
The formula omits a minus sign. Put back into the plan's conditional PD formula, a severe stress reduces defaults instead of increasing them. On a multi-grade book, solving for $z^*$ using the average portfolio PD misses the target rate ($z^* = -1.620$ gives 3.91% vs target 4.00%). Exact root-finding gives $z^* = -1.646$.

#### 3. Primary source check
Derivation from the plan's conditional PD formula:
$$\text{DR}_{stress} = \Phi\left(\frac{\Phi^{-1}(\text{PD}_{TTC}) - \sqrt{\rho} \cdot z^*}{\sqrt{1-\rho}}\right)$$
$$\Phi^{-1}(\text{DR}_{stress}) \cdot \sqrt{1-\rho} = \Phi^{-1}(\text{PD}_{TTC}) - \sqrt{\rho} \cdot z^*$$
$$\sqrt{\rho} \cdot z^* = \Phi^{-1}(\text{PD}_{TTC}) - \Phi^{-1}(\text{DR}_{stress}) \cdot \sqrt{1-\rho}$$
$$z^* = \frac{\Phi^{-1}(\text{PD}_{TTC}) - \Phi^{-1}(\text{DR}_{stress}) \cdot \sqrt{1-\rho}}{\sqrt{\rho}} = - \left(\frac{\Phi^{-1}(\text{DR}_{stress}) \cdot \sqrt{1-\rho} - \Phi^{-1}(\text{PD}_{TTC})}{\sqrt{\rho}}\right)$$

#### 4. Independent check (run in Python)
1. **Single loan:** $\text{PD}_{TTC} = 1.0\%$, target $\text{DR}_{stress} = 5.0\%$, $\rho = 0.15$.
   - Plan's formula gives $z^* = +2.0911 \to \text{PD}_{cond} = \mathbf{0.0335\%}$ (defaults drop by 97%).
   - Correct formula gives $z^* = -2.0911 \to \text{PD}_{cond} = \mathbf{5.0000\%}$.
2. **Two-grade book:** Grade 1 (0.5%), Grade 2 (2.0%), equal weights, target $\text{DR} = 4.0\%$. Average $\text{PD} = 1.25\%$.
   - Average-PD shortcut: $z^* = \mathbf{-1.6198} \to$ book DR = $\mathbf{3.910\% \neq 4.000\%}$.
   - Exact numerical root-finding (`scipy.optimize.brentq`): solves $0.5 \cdot \text{PD}_{cond}(0.5\%, z^*) + 0.5 \cdot \text{PD}_{cond}(2.0\%, z^*) = 4.0\%$, yielding $\mathbf{z^* = -1.6459}$ (reproducing $\mathbf{4.000\%}$ exactly).

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. Fix the minus sign in the analytical single-loan formula:
   $$z^* = \frac{\Phi^{-1}(\text{PD}_{TTC}) - \Phi^{-1}(\text{DR}_{stress}) \cdot \sqrt{1-\rho}}{\sqrt{\rho}}$$
2. For multi-grade portfolios, implement 1D numerical root-finding (`scipy.optimize.brentq`) across master rating scale grades.

#### 7. Devesh decisions incorporated
- Mathematical correction verified and accepted.

---

### B5. PIT and TTC Blend Weight $w = \sqrt{\rho / (1 - \rho)}$ (03_rating_and_pd/05_pd_calibration.py)

#### 1. What the plan says
> "$$\text{PD}_{blend} = w \cdot \text{PD}_{PIT} + (1-w) \cdot \text{PD}_{TTC}, \quad w = \sqrt{\frac{\rho}{1-\rho}}$$
> This is the theoretically justified link between the IFRS 9 PD and the IRB PD" (lines 392–395).

#### 2. Reviewer's concern
$\sqrt{\rho/(1-\rho)}$ is a factor loading in latent probit space, not a probability interpolation weight. If $\rho > 0.5$, $w > 1$. Furthermore, SS4/24 §11.41 explicitly prohibits fully TTC models for residential mortgages, while §11.42 warns against overly cyclical PiT models. The 30% in §11.38 caps cyclicality assumed when backcasting missing grade default rates, not a formula for blending two PDs.

#### 3. Primary source check
- **Document:** Bank of England Supervisory Statement SS4/24, Chapter 11.
- **Paragraphs:** 11.14, 11.38, 11.41, 11.42.
- **Date:** January 2026 update.
- **URL:** [Bank of England SS4/24](https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/supervisory-statement/2026/ss424-january-2026-update.pdf)
- **Date checked:** 14 November 2026.
- **Exact rules (in summary):**
  - **§11.41:** The PRA expects firms not to use fully Through-the-Cycle (TtC) approaches for residential mortgages.
  - **§11.42:** The PRA expects firms to avoid overly cyclical Point-in-Time rating systems that produce excessive capital volatility.
  - **§11.14:** Calibration history must include a period of significant economic stress (in this US Fannie Mae book: the 2007–2009 Great Financial Crisis).
  - **§11.38:** Where historical grade-level default rates are missing, no more than 30% of the movement in the portfolio default rate may be attributed to grade migration.

#### 4. Independent check
In factor model theory, $\sqrt{\rho/(1-\rho)}$ is the factor loading on systematic shock $Z$ in probit space: $\Phi^{-1}(\text{PD}_{cond}) = \frac{\Phi^{-1}(\text{PD}_{TTC})}{\sqrt{1-\rho}} - \sqrt{\frac{\rho}{1-\rho}} Z$. It has standard deviation units, not probability units. If $\rho = 0.60$, $w = \sqrt{0.60/0.40} = 1.225 > 1$, making $1-w = -0.225$.

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. Remove the equation $w = \sqrt{\rho/(1-\rho)}$ and the claim of a theoretical linear blend.
2. Replace `04_ttc_pd.py` with `04_lradr_pd.py` (Long-Run Average Default Rate model anchoring grades over 2000–2008 including the 2007–2009 downturn).
3. In `05_pd_calibration.py`, calibrate master scale grades directly to the LRADR. Measure the model's cyclicality:
   $$\text{Cyclicality} = \frac{\Delta \text{PD from Grade Migration}}{\Delta \text{Portfolio Observed Default Rate}}$$
   Report measured cyclicality against the PRA's 30% supervisory expectation (SS4/24 §11.38).
4. Master scale grade PDs feed AIRB capital and regulatory EL; forward-looking PIT PD term structure feeds IFRS 9 ECL.

#### 7. Devesh decisions incorporated
- Decision 14 accepted: Master rating scale grade PDs (LRADR with downturn) feed AIRB capital and regulatory EL; forward-looking PIT PD term structure feeds IFRS 9 ECL.

---

### B6. Build Order Circular Dependency

#### 1. What the plan says
- Step 12: `03_rating_and_pd/03_pit_pd.py` uses macro overlay coefficients from Module 7 (lines 362–364).
- Step 28: `07_stress_testing/01_satellite_models.py` (Prereq: Steps 7, 26).
- Step 26: `06_basel_capital/02_airb_vasicek.py` (Prereq: Steps 15, 18).
- Step 15: `03_rating_and_pd/06_master_rating_scale.py` (Prereq: Step 14).
- Step 14: `03_rating_and_pd/05_pd_calibration.py` (Prereq: Steps 12, 13).

#### 2. Reviewer's concern
Step 12 requires Step 28, which requires Step 26, which requires Step 15, which requires Step 14, which requires Step 12. A closed circular loop.

#### 3. Primary source check
Topological sorting in a directed acyclic graph (DAG).

#### 4. Independent check
Trace: $\text{Step 12} \to \text{Step 28} \to \text{Step 26} \to \text{Step 15} \to \text{Step 14} \to \text{Step 12}$. Sequential build fails on Step 12.

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
Decouple Step 12 from Module 7:
- In Step 12 (`03_pit_pd.py`), fit a direct single-period log-odds macro regression:
  $$\text{logit}(\text{ODR}_t) = \gamma_0 + \gamma_1 \Delta U_t + \gamma_2 \Delta \text{HPI}_t$$
  This uses only observed quarterly default rates from Module 2 (`03_roll_rates.py`) and historical macro series.
- Module 7 (`01_satellite_models.py`) remains dedicated to multi-period ARDL dynamic forecasting and stress test projections.

#### 7. Devesh decisions incorporated
- Confirmed and accepted.

---

### B7. Default Definition Analysis (02_portfolio_analytics/02_default_engine.py)

#### 1. What the plan says
> "For each candidate threshold $\theta \in \{30, 45, 60, 75, 90, 105, 120, 150, 180\}$ DPD...
> Modification with concession (NPV of concession > 1% of outstanding balance)...
> 3+ consecutive months with delinquency_months = NULL (unknown)" (lines 213–227).

#### 2. Reviewer's concern
Delinquency is reported in integer months (cannot observe 45/75/105 DPD). 90 DPD is statutory (Article 178(1)(b)). Distressed restructuring is Article 178(3)(d). Retail materiality is Article 178(2)(d) (above £0 and 0%) and SS3/24 §7.18. Modification flag is a simplifying choice. Probation is Article 178(5)(a) and 178(5A). 3 months of unknown status is invented.

#### 3. Primary source check
- **Fannie Mae:** Glossary and File Layout (110 fields). Fields include: `Current_Interest_Rate`, `Modification_Flag`, `Mortgage_Loan_Delinquency_Status`, `Non_Interest_Bearing_UPB`, `Principal_Forgiveness_Amount`. Delinquency status is numeric months or `"XX"`.
- **PRA Rulebook (CRR) Credit Risk: IRB Part (version 1 January 2027):**
  - **Article 178(1)(b):** The obligor is past due more than 90 days on any material credit obligation.
  - **Article 178(2)(d):** For retail exposures, the materiality threshold is set by the competent authority (above GBP 0 and above 0%).
  - **Article 178(3)(d):** Distressed restructuring of the credit obligation.
  - **Article 178(5)(a):** An exposure remains in default until at least 3 months have elapsed since default triggers ceased.
  - **Article 178(5A):** For distressed restructuring, at least one year must elapse from the latest of the restructuring date, the end of any grace period, or when the obligation ceased to be non-performing.
- **PRA SS3/24:** Paragraph 7.18 covers retail materiality at obligor level. Paragraph 3.20 sets the 1% diminished financial obligation threshold.

#### 4. Independent check
With monthly reporting, delinquency states are discrete months: 1 month (30 DPD), 2 months (60 DPD), 3 months (90 DPD). Sub-month thresholds like 45 DPD have zero observations.
While Fannie Mae disclosures record forgiveness and non-interest-bearing principal amounts, calculating pre- vs post-modification cash flows across millions of historical loans is computationally complex; using `Modification_Flag == 'Y'` is a valid, practical operational choice.

#### 5. Verdict
**Plan is partly wrong.**

#### 6. Proposed fix
1. Restrict delinquency analysis to whole-month increments: $\{30, 60, 90, 120, 150, 180\}$ DPD.
2. Frame cure-rate analysis as validating behavioral default dynamics, not "deriving" a statutory rule.
3. Use `Modification_Flag == 'Y'` as the sole distressed restructuring trigger, described as a simplifying choice. Forbearance plans and payment deferrals are tracked as separate flags for IFRS 9 Stage 2, not default triggers.
4. Remove the invented "3+ months unknown" UTP trigger. Map `"XX"` to missing data.
5. Sourced citations: Article 178(1)(b), Article 178(2)(d), Article 178(3)(d), Article 178(5)(a), Article 178(5A). No EBA citations.

#### 7. Devesh decisions incorporated
- Decision 5 accepted: Modification flag is the only restructuring trigger; described as a simplifying choice. Forbearance plans and deferrals are Stage 2 flags.
- Decision 6 accepted: 12 clean months as simplified reading of Article 178(5A). No EBA reference.

---

### B8. Probation SQL Logic (02_portfolio_analytics/02_default_engine.py)

#### 1. What the plan says
The proposal provided an initial SQL fix that marked active defaults as 'Performing' when un-cured, failed to reset streaks on probation slips, and duplicated rows.

#### 2. Reviewer's concern
- A loan that cures, slips for one month, then pays is marked 'Performing' after one clean month because the probation clock does not reset.
- A loan that completed probation and is later 1 month late is marked 'Default' without a new default event.
- Under Article 178(5), a loan remains in default during probation until the period successfully ends.
- The query must work out default events and status simultaneously without reading a pre-existing default table.

#### 3. Primary source check
- **PRA Rulebook (CRR):** Article 178(5)(a) mandates that an exposure remains classified as defaulted until at least 3 months have elapsed during which no trigger of default continues to apply. Article 178(5A) mandates at least one year for distressed restructuring.
- State-machine rules:
  1. Default is triggered by $\text{delinquency\_months} \ge 3$ or $\text{modification\_flag} = 1$.
  2. While in default, a loan enters probation only when clean ($\text{delinquency\_months} = 0$ and $\text{modification\_flag} = 0$).
  3. Any slip during probation ($\text{delinquency\_months} > 0$ or modification) resets the clean streak to 0; the loan remains in default.
  4. Only when consecutive clean months reach the requirement (3 for arrears, 12 for modification) does the loan transition to `Performing`.
  5. Subsequent delinquency under 90 DPD (30 or 60 DPD) on a performing loan remains `Performing`.

#### 4. Independent check (run in Python + DuckDB)
The test suite in `scratch/test_probation.py` evaluated all 6 test loans across 70 loan-months:
- **Loan 1 (Never cures):** Stays in `Default` for months 5–8.
- **Loan 2 (Clean cure):** Defaults month 5, clean months 6–8 (probation streak 1, 2, 3), exits to `Performing` at month 9.
- **Loan 3 (Probation slip):** Defaults month 5, clean month 6 (streak 1), slips month 7 (streak 0, stays `Default`), clean months 8–10 (streak 1, 2, 3), exits to `Performing` at month 11.
- **Loan 4 (Post-cure delinquency):** Cures cleanly, performing at month 9, 30 DPD at month 10 $\to$ stays `Performing`!
- **Loan 5 (Two defaults):** Defaults month 5, cures month 8, performing months 9–11 (30 DPD at month 10, 60 DPD at month 11). Month 12 reaches 90 DPD $\to$ `Default` (default event #2).
- **Loan 6 (Modification):** Defaults at month 4 by modification. Clean months 5–16 (streak 1 to 12). Exits to `Performing` at month 17.
**Result:** 70 out of 70 rows matched expected status perfectly (0 mismatches).

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
Replace the broken query with the verified recursive state machine query in Module 2:

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
    FROM raw_performance WHERE reporting_period = 1

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
    FROM raw_performance r
    JOIN state_machine s ON r.loan_id = s.loan_id AND r.reporting_period = s.reporting_period + 1
)
SELECT * FROM state_machine;
```

#### 7. Devesh decisions incorporated
- Confirmed and verified across all 6 test loans.

---

### B9. Fannie Mae File Layout (data/build_db.py, field_map.py, Module 1)

#### 1. What the plan says
> "Fannie Mae publishes two file types per acquisition quarter:
> - Acquisition file (`{YYYYQQ}_acq.txt`): ~25 fields.
> - Performance file (`{YYYYQQ}_perf.txt`): ~31 fields...
> DTI was not fully reported before 2015" (lines 96–133).
> Feature catalogue: "`dti`: Missing pre-2003" (line 167).

#### 2. Reviewer's concern
Fannie Mae disclosures use a single consolidated 110-field layout. DTI is an origination attribute populated since 2000Q1; the contradictory missingness notes (2015 vs 2003) must be removed.

#### 3. Primary source check
- **Document:** Fannie Mae *Single-Family Loan Performance Dataset and Credit Risk Transfer – Glossary and File Layout*.
- **URL:** [Fannie Mae File Layout](https://capitalmarkets.fanniemae.com/media/6931/display)
- **Date checked:** 14 November 2026.
- **Findings:**
  - The standard single-family disclosure layout contains **110 fields** in a single file per quarter.
  - DTI is present from 2000Q1 acquisitions. Missing values occur when DTI was exempt (streamline refinances) or exceeded allowable thresholds ($> 65\%$).

#### 4. Independent check
Review of the official file layout shows columns 1 through 110 in a single record.

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. Update `data/build_db.py` and `00_data/field_map.py` to parse the official 110-field single consolidated file layout.
2. Remove both contradictory DTI notes. State accurately: "DTI is an origination attribute populated since 2000Q1, with missing values where borrower was exempt or DTI exceeded conforming limits."

#### 7. Devesh decisions incorporated
- Technical specification alignment confirmed.

---

### B10. Competing Risks and `lifelines` (02_portfolio_analytics/04_vintage_curves.py, 05_ifrs9_ecl/02_pd_term_structure.py)

#### 1. What the plan says
> "Kaplan-Meier survival curves: Separate sub-distribution hazards for default vs prepayment (competing risks using the Fine-Gray model from `lifelines`)." (lines 303–304).

#### 2. Reviewer's concern
`lifelines` lacks Fine-Gray regression. On large panel data, compute discrete non-parametric CIF directly in DuckDB SQL; use `lifelines.AalenJohansenFitter` on a validation sample. Prepayment is the competing exit; sales/removals are censored.

#### 3. Primary source check
- **Document:** `lifelines` official documentation (`lifelines.readthedocs.io`).
- **Findings:** `lifelines` provides `AalenJohansenFitter` for non-parametric CIF, but contains no Fine-Gray regression class.

#### 4. Independent check (run in Python)
On monthly panel data with $N_m$ loans at risk in month $m$, $D_m$ defaults, and $P_m$ prepayments:
$$\text{Total exit hazard: } h_{all}(m) = \frac{D_m + P_m}{N_m}$$
$$\text{Survival probability: } S(m) = \prod_{k=1}^m (1 - h_{all}(k))$$
$$\text{Cumulative Incidence of Default: } \text{CIF}_{default}(m) = \sum_{k=1}^m S(k-1) \cdot \frac{D_k}{N_k}$$
This discrete Aalen-Johansen calculation runs natively inside DuckDB SQL across millions of rows.

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. Implement the discrete Aalen-Johansen cumulative incidence formula directly in DuckDB SQL for cohort vintage curves and IFRS 9 term structures.
2. Voluntary prepayment is treated as the primary competing exit; repurchases, note sales, and administrative removals are treated as right-censoring events. (Non-performing note sales remain a loss outcome for LGD in Module 4).
3. Use `lifelines.AalenJohansenFitter` in `tests/` to cross-check the DuckDB SQL output on a sampled cohort.

#### 7. Devesh decisions incorporated
- Decision 7 accepted: Prepayment is primary competing exit; removals/sales censored for default curve; non-performing note sales remain loss outcomes for LGD.
- Decision 15F accepted: Large-scale data processing in DuckDB SQL; export only aggregated curves/matrices to Python.

---

### B11. Stress Test References (07_stress_testing)

#### 1. What the plan says
> "Bank of England 2025 Biennial Exploratory Scenario style... Compare lowest CET1 point to BoE hurdle rate (6.2% aggregate in 2025 test, not a flat 4.5%). Failure condition: CET1 ratio falls below 4.5% (the minimum requirement before the buffer)." (lines 654–674).

#### 2. Reviewer's concern
The 2025 exercise was the Bank Capital Stress Test (BCST). Buffer restrictions bite earlier (when entering the buffer). 6.2% was the aggregate hurdle across participating banks. This bank needs its own hurdle: 4.5% Pillar 1 + its assumed Pillar 2A. Calling 4.5% "regulatory insolvency" overstates it.

#### 3. Primary source check
- **Document:** Bank of England, "Key elements of the 2025 Bank Capital Stress Test", March 2025; Bank of England, "Results of the 2025 Bank Capital Stress Test", December 2025.
- **Date:** March / December 2025.
- **Findings:**
  - The exercise name is the **Bank Capital Stress Test (BCST)**.
  - The hurdle rate for each bank in the BCST is its minimum capital requirement: $\text{Pillar 1 (4.5%)} + \text{Pillar 2A}$. The aggregate across banks was 6.2% because the average Pillar 2A was ~1.7%.
  - Combined buffer restrictions (MDA) bite as soon as capital enters the combined buffer (above the hurdle).
  - Breaching 4.5% is a breach of minimum regulatory capital, triggering severe supervisory remediation, but is not formal corporate insolvency.

#### 4. Independent check
For this portfolio bank:
$$\text{Bank Hurdle Rate} = 4.5\% \text{ (Pillar 1)} + 1.7\% \text{ (Assumed Pillar 2A)} = \mathbf{6.2\%}$$
$$\text{Reverse Stress Breaking Point} = \mathbf{4.5\%} \text{ (Breach of minimum statutory requirement)}$$

#### 5. Verdict
**Plan is partly wrong.**

#### 6. Proposed fix
1. Rename exercise to "Bank of England 2025 Bank Capital Stress Test (BCST) style".
2. Clearly define the bank's own hurdle: 4.5% Pillar 1 + 1.7% assumed Pillar 2A = 6.2%.
3. Rephrase 4.5%: "Breach of minimum statutory Pillar 1 capital requirement".

#### 7. Devesh decisions incorporated
- Decision 8 accepted: Assumed Pillar 2A of 1.7% $\to$ Bank Stress Hurdle of 6.2% CET1; Reverse Stress Breaking Point at 4.5% CET1.

---

### B12. SR 11-7 Status (08_model_risk_mgmt)

#### 1. What the plan says
> "Applies SR 11-7 (US Federal Reserve, 2011) and SS1/23 (UK PRA Model Risk Management Principles, effective May 2024)... (SR 11-7 §4 requires this honesty.)" (lines 688–727).

#### 2. Reviewer's concern
SR 11-7 was superseded by SR 26-2 on 17 April 2026. SR 11-7 has no "§4". In SS1/23, Principle 5 is "Model risk mitigants", not ongoing monitoring. SS1/23 has an updated version effective 23 April 2026.

#### 3. Primary source check
- **Federal Reserve:** Supervisory Letter **SR 26-2** ("Revised Guidance on Model Risk Management"), issued 17 April 2026.
- **PRA SS1/23:** Bank of England Supervisory Statement SS1/23 ("Model risk management principles for banks"), version effective 23 April 2026.
  - Principle 1: Model identification and classification (Inventory)
  - Principle 2: Governance
  - Principle 3: Model development, implementation, and use
  - Principle 4: Independent model validation (includes ongoing monitoring, §4.17–4.19)
  - Principle 5: Model risk mitigants (Post-model adjustments, overlays, caps/floors, §5.1–5.14)

#### 4. Independent check
Map Module 8 to SS1/23 principles:
- `01_model_inventory.py` $\to$ Principle 1
- `02_conceptual_soundness.md` $\to$ Principle 3
- `03_validation_reports/` $\to$ Principle 4
- `04_monitoring_dashboard.py` $\to$ Principle 4 & 5 (validation monitoring and tracking model mitigants/overrides)

#### 5. Verdict
**Plan is partly wrong.**

#### 6. Proposed fix
1. Frame Module 8 primarily around PRA SS1/23 (effective 23 April 2026).
2. Correct the mapping: Principle 4 covers validation and ongoing monitoring; Principle 5 covers model risk mitigants and overlays.
3. Note US guidance as SR 11-7 (historical) and SR 26-2 (current), removing "§4".

#### 7. Devesh decisions incorporated
- Decision 9 accepted: Primary framework is PRA SS1/23 (effective 23 April 2026); secondary note on US SR 26-2.

---

### B13. Labels Claiming Official Authority (03_rating_and_pd)

#### 1. What the plan says
> "Score scaling... Score 600 = 1:1 good-to-bad odds (Basel-standard scorecard scaling)." (line 343).
> "Binomial traffic lights (per grade)... Basel 3-zone system (green ≤ 5%, amber 5–10%, red > 10%)." (line 424).
> "Low-default portfolio (Pluto-Tasche): Upper confidence bound: $\hat{p}_{upper} = 1 - (1-\alpha)^{1/(n+1)}$" (lines 430–431).

#### 2. Reviewer's concern
Basel traffic lights apply to market risk VaR (MAR32), not PD backtesting. 600 score at 1:1 odds is a chosen anchor, not a Basel rule. Pluto-Tasche formula shown applies only to zero defaults ($k=0$). Removing external agency mappings (Moody's/S&P) dropped out of the previous fix list.

#### 3. Primary source check
- **Traffic lights:** Basel Framework **MAR32** ("Internal models approach: backtesting") defines the 3-zone traffic lights for daily market risk VaR. Credit risk CRE36 requires backtesting but leaves specific statistical confidence intervals to supervisory discretion.
- **Scorecard scaling:** Bureau convention (FICO). Setting 1:1 odds at 600 implies a 50% default rate at score 600, which is subprime.
- **Pluto & Tasche (2005):** The formula $\hat{p} = 1 - (1-\alpha)^{1/(n+1)}$ is strictly for $k = 0$ observed defaults. For $k > 0$, the upper bound solves $\sum_{i=0}^k \binom{n}{i} p^i (1-p)^{n-i} = 1 - \alpha$.
- **Agency mapping:** S&P and Moody's rate wholesale obligors, not individual residential mortgage borrowers. Retail master scales use internal numbered grades.

#### 4. Independent check (run in Python)
With $n = 500$ and $k = 3$ defaults at $\alpha = 0.95$:
- Formula in plan gives $0.596\%$.
- Exact binomial upper bound with 3 defaults is $\mathbf{1.543\%}$ (`scipy.stats.beta.ppf(0.95, 4, 497)`).

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. Relabel scorecard scaling: "Chosen calibration anchor: 50:1 odds at score 650 with PDO = 20."
2. Relabel traffic lights: "Binomial backtesting evaluated at standard 95% (amber) and 99% (red) confidence thresholds."
3. Remove external agency crosswalks. Use internal numbered grades (Grade 1 to Grade 15).
4. Implement the general Pluto-Tasche upper bound for $k \ge 0$ defaults using `scipy.stats.beta.ppf(alpha, k + 1, n - k)` for low-default sub-grades (Grade 1).

#### 7. Devesh decisions incorporated
- Decision 10 accepted: Chosen anchor 50:1 odds at score 650, PDO = 20.
- Decision 11 accepted: Binomial backtesting at 95% and 99% thresholds.
- Decision 12 accepted: Keep Pluto-Tasche with numbered grades (Grade 1, no "AAA"). Remove agency crosswalk.

---

### B14. Economic Capital Definitions & Scale (06_basel_capital/03_economic_capital.py)

#### 1. What the plan says
> "Simulate $N = 50,000$ portfolio scenarios using the same ASRF factor $Z$...
> VaR(99.9%) = economic capital...
> Euler capital allocation: $\text{EC}_i = \frac{\text{Cov}(L_i, L)}{\sigma(L)} \times k$...
> Granularity adjustment applies when the book is concentrated" (lines 612–621).

#### 2. Reviewer's concern
- Economic Capital is $\text{VaR} - \text{EL}$.
- A grade-level simulation with one factor is just evaluating the Vasicek formula at each draw, which adds nothing over the analytical closed-form quantile.
- Loan-level simulation ($50k \times 150k$) takes 30 GB of RAM and crashes a 16 GB machine.
- Covariance allocation is for volatility, not VaR/ES.
- Granularity adjustment is zero for prime retail mortgages.

#### 3. Primary source check
- **Document:** BCBS 152 ("Range of practices in economic capital frameworks"); Gordy (2003); Tasche (2008).
- **Definitions:**
  $$\text{Economic Capital} = \text{VaR}_{99.9\%}(L) - \mathbb{E}[L]$$
  In the asymptotic single-risk-factor (ASRF) model, the portfolio loss distribution is given in closed form by the Vasicek cumulative distribution function:
  $$F(x) = \Phi\left(\frac{\sqrt{1-\rho} \cdot \Phi^{-1}(x/LGD) - \Phi^{-1}(PD)}{\sqrt{\rho}}\right)$$
  Simulating single-factor draws merely reproduces this analytical curve with Monte Carlo sampling error.
  For a multi-grade book:
  $$L_{99.9\%} = \sum_g \text{EAD}_g \times \text{LGD}_g \times \Phi\left(\frac{\Phi^{-1}(\text{PD}_g) + \sqrt{\rho} \cdot 3.0902}{\sqrt{1-\rho}}\right)$$
  $$\text{EC}_g = \text{EAD}_g \times \text{LGD}_g \times \left[\Phi\left(\frac{\Phi^{-1}(\text{PD}_g) + \sqrt{\rho} \cdot 3.0902}{\sqrt{1-\rho}}\right) - \text{PD}_g\right]$$
  Allocated capital sums identically to total portfolio economic capital: $\sum_g \text{EC}_g = \text{EC}_{portfolio}$.

#### 4. Independent check (run in Python)
Evaluating the analytical Vasicek distribution takes 0.001 seconds and zero RAM. In contrast, $50,000 \text{ scenarios} \times 150,000 \text{ loans} = 7.5 \times 10^9 \text{ elements} = 30.0 \text{ GB}$ of RAM, triggering an immediate crash.

#### 5. Verdict
**Plan is wrong.**

#### 6. Proposed fix
1. State the closed-form analytical Vasicek loss distribution as the sole economic capital calculation in this build:
   $$\text{EC} = \text{VaR}_{99.9\%}(L) - \text{EL}$$
2. State capital allocation on $\text{VaR}_{99.9\%}$, where grade-level allocations sum identically to portfolio EC.
3. Move multi-factor (regional) simulation to a "later extensions" list outside the build order.
4. Remove granularity adjustment for retail mortgages.

#### 7. Devesh decisions incorporated
- Decision 13 accepted: Closed form only in this build. Two-factor regional simulation placed in later extensions list.

---

## C. Additional Issues Found

### 1. In-Default Stage Transition Nomenclature (`05_movement_waterfall.py`, line 547)
- **Text:** `"Stage 2 / 3 → Default (Stage 3 entry)"`
- **Issue:** Under IFRS 9, Stage 3 is the credit-impaired/defaulted state. Stage 3 to Default is a null transition.
- **Fix:** Change description to `"Stage 1 / 2 → Stage 3 (New In-Default Inflows)"`.

### 2. Output Floor Phasing Schedule (`regulatory_parameters.py`, lines 783–786)
- **Text:** Phasing 2027 (60%) to 2030 (72.5%).
- **Issue:** The Basel 3.1 UK implementation date is fixed as 1 January 2027 under final policy PS1/26.
- **Fix:** Retain values; document that dates reflect the statutory 1 January 2027 start date.

---

## D. Points Marked "Not Confirmed"

*None.* All fourteen points, primary statutory articles (PRA Rulebook Articles 124D, 124E, 124F, 124G, 124L, 154(3), 163(1)(b), 164(4)(a), 178(1)(b), 178(2)(d), 178(3)(d), 178(5)(a), 178(5A)), supervisory statements (SS3/24, SS4/24, SS1/23), Basel standards (CRE31, MAR32), Federal Reserve guidance (SR 26-2), and technical calculations were opened, verified, and executed in code during this run.

---

## E. Build Gaps Resolved (Block E)

1. **Quarters to Load & Sampling (Decision 15A):**
   - **Full Load (2000Q1 to 2008Q4, 36 quarters):** ~12–14 million loans; ~250–300 million monthly performance rows; ~50–70 GB uncompressed text; ~15–20 GB DuckDB storage.
   - **Fixed 10% Random Sample (Seeded draw `seed=42`, whole loan histories):** ~1.2–1.4 million loans; ~25–30 million performance rows; ~1.5–2.0 GB DuckDB storage.
   - **Decision:** Load 2000Q1–2008Q4 with a fixed 10% seeded random draw of loans saved as a master sample table. Captures the full 2007–2009 downturn. No hashing.

2. **Starting Baseline Balance Sheet (Decision 15B):**
   - Total Assets: 11,765 (assumed scale).
   - Residential Mortgages (Gross UPB): 10,000 (85.0% of assets).
   - Liquid Assets (Cash & UK Gilts/Treasuries, 0% RWA): 1,765 (15.0% of assets).
   - Liabilities: Retail Deposits = 9,800 (funding cost = Base Rate − 150 bps, deposit beta = 0.50); Wholesale Term Funding = 1,000 (funding cost = Base Rate + 100 bps); Tier 2 Subordinated Debt = 200.
   - Equity (CET1 Capital): 765.
   - Stated initial **14.0% CET1 ratio is assumed on Standardised Approach (SA) RWAs** (assuming portfolio average SA risk weight is ~46.4% $\to$ SA RWA = 5,464; $765 / 5,464 \approx 14.0\%$). All balance sheet figures explicitly labeled as assumed.

3. **Removal of Speculative Unrun Results (Decision 15C):**
   - All unverified assertions (e.g. "PASS (0 discrepancy)", "drops sharply between 60 and 90", "EPD leads by 18-24 months") rephrased as hypotheses and acceptance criteria to test.

4. **Numbered Folders & Files (Decision 15D):**
   - Retain numbered folder and file names (`01_data_foundation`, `01_data_audit.py`).
   - Unit tests in `tests/` load modules dynamically by file path using `importlib.machinery.SourceFileLoader` via a test runner helper, avoiding direct Python `import 01_...` syntax limitations.

5. **Currency & Geography (Decision 15E):**
   - No currency symbols (`$`, `£`) and no country names in output packs.
   - Amounts are plain numbers. The data's own region codes are preserved without national labels.

6. **DuckDB Processing (Decision 15F):**
   - All large-scale panel transformations, window operations, and DPD tracking run natively inside DuckDB SQL. Only final aggregated metrics and curves are exported to Python DataFrames.
