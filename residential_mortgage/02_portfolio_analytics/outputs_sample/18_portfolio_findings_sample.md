# Module 2 Findings: Portfolio Analytics
Generated 2026-11-25 from Module 2 marts (`10% sample` run).
Every figure below is queried directly from `module2_marts` outputs.

## 1. Foundations (`00_build_monthly_core`, `01_data_audit`, `02_default_engine`)
- **Balance roll-forward (`balance_rollforward_mart`):** latest month `2025-12-01`, `1,542,385` active loans, closing UPB `340,766,250,565` USD, count residual `0`, unexplained `-9,553,224` USD.
- **Continuity & plausibility (`01_data_audit.py` -> `data_plausibility_mart`):** `13` global checks stored.
  - `dup_loans`: `0` (`0.0000%`)
  - `early_noexit_loans`: `1` (`0.0000%`)
  - `gap_loans`: `1,237` (`0.0215%`)
  - `invalid_orig_ltv_loans`: `1` (`0.0000%`)
  - `invalid_orig_upb_loans`: `0` (`0.0000%`)
  - `invalid_rate_rows`: `35` (`0.0000%`)
  - `multi_servicer_loans`: `1,965,000` (`34.1160%`)
  - `negative_upb_rows`: `0` (`0.0000%`)
  - `null_dti_loans`: `76,473` (`1.3277%`)
  - `null_fico_loans`: `17,425` (`0.3025%`)
  - `null_first_payment_loans`: `0` (`0.0000%`)
  - `reaging_events_total`: `178,747` (`0.0539%`)
  - `total_loans`: `5,759,759` (`100.0000%`)
- **Default & probation (`default_events_mart`):** `277,792` events across `235,355` loans (`as_reported: 294,392, covid_adjusted: 277,792`).

## 2. Arrears Transitions, Vintages, LTV and 12m History (`03` to `08`)
- **IFRS 9 30-day backstop (`roll_30day_evidence_mart`, Wilson 95% CI):**
  - `1m_first` (`12m`): `17.29%` [95% CI `17.20%` to `17.38%`, Wilson score] (`125,917/728,247`)
  - `2m_first` (`12m`): `67.74%` [95% CI `67.55%` to `67.92%`, Wilson score] (`172,125/254,114`)
  - `never_behind_mob6` (`12m`): `0.48%` [95% CI `0.48%` to `0.49%`, Wilson score] (`25,163/5,199,324`)
  - `1m_first` (`lifetime`): `27.51%` [95% CI `27.41%` to `27.61%`, Wilson score] (`207,736/755,192`)
  - `2m_first` (`lifetime`): `75.39%` [95% CI `75.22%` to `75.55%`, Wilson score] (`199,928/265,195`)
  - `never_behind_mob6` (`lifetime`): `3.73%` [95% CI `3.71%` to `3.75%`, Wilson score] (`197,343/5,292,138`)
- **60/90/120-day sensitivity (`threshold_sensitivity_mart`):** 2m: 406,234, 3m: 307,879, 4m: 265,045.
- **Top 5 peak-to-trough state HPI falls (`state_hpi_peaktotrough_mart`):**
  - `NV`: `-59.4%` (`2006-01-01` to `2011-10-01`)
  - `AZ`: `-49.7%` (`2006-10-01` to `2011-04-01`)
  - `CA`: `-47.1%` (`2006-01-01` to `2011-07-01`)
  - `FL`: `-46.6%` (`2006-04-01` to `2011-01-01`)
  - `ID`: `-32.4%` (`2007-04-01` to `2011-04-01`)
- **Long-run 12m PD (`default_rate_history_mart`, complete windows <= 2024-12):** `1.0147%` count-weighted.
- **Implied Vasicek correlation (`implied_correlation_mart`):** `0.0365` vs IRB `0.1500`.
- **PD sample scope (`sample_population_mart`):** excluded: 5,613,494, included: 22,364,347.

## 3. Risk Drivers & Segmentation (`09`, `10`)
- **Top features by mean IV across eras (`feature_iv_mart`):** `months_since_last_arrears_t1` (1.956), `worst_dpd_12m_t1` (1.772), `worst_dpd_6m_t1` (1.747), `credit_score` (0.891), `ltv_indexed_t1` (0.303), `rate_incentive_t1` (0.291).

## 4. After Default & Relief (`11`, `12`)
- Outcome `cured without loss`: `97,160` events, net loss sum `0` USD.
- Outcome `credit exit`: `68,017` events, net loss sum `2,990,848,280` USD (`29.07%` of `10,286,836,699` USD UPB).
- Outcome `cured with modification`: `53,415` events, net loss sum `0` USD (mod non-interest UPB `466,920,617` USD, principal forgiveness `0` USD).
- Outcome `cured - paid off`: `36,001` events, net loss sum `0` USD (mod non-interest UPB `19,729,106` USD, principal forgiveness `0` USD).
- Outcome `unresolved`: `16,087` events, net loss sum `0` USD (mod non-interest UPB `165,889,497` USD, principal forgiveness `0` USD).
- Outcome `other exit`: `7,112` events, net loss sum `0` USD (mod non-interest UPB `41,170,096` USD, principal forgiveness `0` USD).
- **Liquidation forced-sale discount (`default_outcomes_mart`):** `45.38%` mean across `60,652` property liquidations.
- Re-default `forbearance_plan` (in_default, `12m`): `1.60%`.
- Re-default `forbearance_plan` (in_default, `24m`): `4.95%`.
- Re-default `forbearance_plan` (performing, `12m`): `45.87%`.
- Re-default `forbearance_plan` (performing, `24m`): `46.73%`.
- Re-default `modification` (in_default, `12m`): `0.00%` (coincides with 12m Art. 178(5A) modification probation).
- Re-default `modification` (in_default, `24m`): `2.76%`.
- Re-default `payment_deferral` (in_default, `12m`): `6.27%`.
- Re-default `payment_deferral` (in_default, `24m`): `10.27%`.
- Re-default `payment_deferral` (performing, `12m`): `12.36%`.
- Re-default `payment_deferral` (performing, `24m`): `14.59%`.

## 5. Economy, Portfolio Mix & Data Fitness (`13` to `17`)
- **Macro default-rate correlations (`economy_correlations_mart`):** `unrate_pct` (lag `3m`: `r=+0.676`), `unrate_chg_12m` (lag `6m`: `r=+0.641`), `nat_hpi_chg_12m_pct` (lag `12m`: `r=-0.542`), `fed_funds_pct` (lag `0m`: `r=-0.360`).
- **Latest concentration HHI (`concentration_mart`):** `msa` (0.0186), `property_state` (0.0595), `seller_name` (0.2101).
- **Max historical PSI vs latest book (`representativeness_mart`):** `note_rate` (0.749), `ltv_indexed` (0.318), `dti` (0.257), `credit_score` (0.104), `loan_purpose` (0.066), `orig_ltv` (0.047), `property_state_tier` (0.004), `occupancy` (0.002).
- **Left-truncation / acquisition seasoning (`survivorship_mart`):** `1.28%` of loans acquired >3m after origination.
- **Category A/B MoC limits (`data_limits_mart`):** `15` limits quantified.

## 6. Modules 3 to 8 Mart Handover Register
| Module | Key marts / datasets consumed |
|---|---|
| Module 3 (PD) | `default_events_mart`, `default_rate_history_mart`, `book_snapshot`, `book_snapshot_behavioural`, `risk_drivers_mart`, `segmentation_mart`, `representativeness_mart`, `data_limits_mart` |
| Module 4 (LGD & EAD) | `default_outcomes_mart`, `loss_development_mart`, `recovery_summary_mart`, `workout_exit_cashflows_mart`, `state_hpi_peaktotrough_mart` |
| Module 5 (IFRS 9) | `roll_30day_evidence_mart`, `vintage_curves_mart`, `default_outcomes_mart`, `forbearance_mart`, `redefault_mart`, `cycle_mart` |
| Module 6 (Capital) | `book_snapshot`, `current_ltv_mart`, `portfolio_mix_mart`, `concentration_mart`, `implied_correlation_mart`, `loan_origination_value_mart` |
| Module 7 (Stress Testing) | `portfolio_rates_quarterly_mart`, `economy_correlations_mart`, `macro_downturn_mart`, `cycle_mart`, `book_snapshot` |
| Module 8 (Model Risk) | `balance_rollforward_mart`, `data_plausibility_mart`, `representativeness_mart`, `data_limits_mart`, `survivorship_mart` |
