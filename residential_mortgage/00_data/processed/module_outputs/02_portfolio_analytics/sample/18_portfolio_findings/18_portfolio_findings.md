# Module 2 Findings: Portfolio Analytics
Generated 2026-11-27 from Module 2 marts (`0.03% sample` run).
Every figure below is queried directly from Module 2 mart tables.

## 1. Foundations (`00_build_monthly_core`, `01_data_audit`, `02_default_engine`)
- **Balance roll-forward (`balance_rollforward_mart`):** latest month `2025-12-01`, `4,724` active loans, closing UPB `1,026,440,511` USD, count residual `0`, unexplained `-2,044` USD.
- **Continuity & plausibility (`01_data_audit.py` -> `data_plausibility_mart`):** `13` global checks stored.
  - `dup_loans`: `0` (`0.0000%`)
  - `early_noexit_loans`: `0` (`0.0000%`)
  - `gap_loans`: `5` (`0.0289%`)
  - `invalid_orig_ltv_loans`: `0` (`0.0000%`)
  - `invalid_orig_upb_loans`: `0` (`0.0000%`)
  - `invalid_rate_rows`: `0` (`0.0000%`)
  - `multi_servicer_loans`: `5,967` (`34.5412%`)
  - `negative_upb_rows`: `0` (`0.0000%`)
  - `null_dti_loans`: `234` (`1.3546%`)
  - `null_fico_loans`: `58` (`0.3357%`)
  - `null_first_payment_loans`: `0` (`0.0000%`)
  - `reaging_events_total`: `474` (`0.0477%`)
  - `total_loans`: `17,275` (`100.0000%`)
- **Default & probation (`default_events_mart`):** `793` events across `681` loans (`as_reported: 838, covid_adjusted: 793`).

## 2. Arrears Transitions, Vintages, LTV and 12m History (`03` to `08`)
- **IFRS 9 30-day backstop (`roll_30day_evidence_mart`, Wilson 95% CI):**
  - `1m_first` (`12m`): `17.58%` [95% CI `16.02%` to `19.25%`, Wilson score] (`374/2,128`)
  - `2m_first` (`12m`): `67.10%` [95% CI `63.69%` to `70.34%`, Wilson score] (`512/763`)
  - `never_behind_mob6` (`12m`): `0.50%` [95% CI `0.40%` to `0.62%`, Wilson score] (`78/15,620`)
  - `1m_first` (`lifetime`): `27.80%` [95% CI `25.97%` to `29.70%`, Wilson score] (`616/2,216`)
  - `2m_first` (`lifetime`): `75.70%` [95% CI `72.58%` to `78.57%`, Wilson score] (`595/786`)
  - `never_behind_mob6` (`lifetime`): `3.60%` [95% CI `3.32%` to `3.90%`, Wilson score] (`572/15,901`)
- **60/90/120-day sensitivity (`threshold_sensitivity_mart`):** 2m: 872, 3m: 675, 4m: 602.
- **Top 5 peak-to-trough state HPI falls (`state_hpi_peaktotrough_mart`):**
  - `NV`: `-59.4%` (`2006-01-01` to `2011-10-01`)
  - `AZ`: `-49.7%` (`2006-10-01` to `2011-04-01`)
  - `CA`: `-47.1%` (`2006-01-01` to `2011-07-01`)
  - `FL`: `-46.6%` (`2006-04-01` to `2011-01-01`)
  - `ID`: `-32.4%` (`2007-04-01` to `2011-04-01`)
- **Long-run 12m PD (`default_rate_history_mart`, complete windows <= 2024-12):** `0.9747%` count-weighted.
- **Implied Vasicek correlation (`implied_correlation_mart`):** `0.0553` vs IRB `0.1500`.
- **PD sample scope (`sample_population_mart`):** excluded: 16,959, included: 67,026.

## 3. Risk Drivers & Segmentation (`09`, `10`)
- **Top features by mean IV across eras (`feature_iv_mart`):** `months_since_last_arrears_t1` (1.958), `worst_dpd_6m_t1` (1.803), `worst_dpd_12m_t1` (1.771), `credit_score` (0.981), `property_state` (0.396), `rate_incentive_t1` (0.348).

## 4. After Default & Relief (`11`, `12`)
- Outcome `cured without loss`: `264` events, net loss sum `0` USD.
- Outcome `credit exit`: `231` events, net loss sum `10,020,696` USD (`28.21%` of `35,522,980` USD UPB).
- Outcome `cured with modification`: `147` events, net loss sum `0` USD (mod non-interest UPB `1,463,117` USD, principal forgiveness `0` USD).
- Outcome `cured - paid off`: `89` events, net loss sum `0` USD (mod non-interest UPB `136,963` USD, principal forgiveness `0` USD).
- Outcome `unresolved`: `40` events, net loss sum `0` USD (mod non-interest UPB `278,788` USD, principal forgiveness `0` USD).
- Outcome `other exit`: `22` events, net loss sum `0` USD (mod non-interest UPB `94,761` USD, principal forgiveness `0` USD).
- **Liquidation forced-sale discount (`default_outcomes_mart`):** `46.17%` mean across `210` property liquidations.
- Re-default `forbearance_plan` (in_default, `12m`): `0.83%`.
- Re-default `forbearance_plan` (in_default, `24m`): `3.33%`.
- Re-default `forbearance_plan` (performing, `12m`): `43.06%`.
- Re-default `forbearance_plan` (performing, `24m`): `45.32%`.
- Re-default `modification` (in_default, `12m`): `0.00%` (coincides with 12m Art. 178(5A) modification probation).
- Re-default `modification` (in_default, `24m`): `2.58%`.
- Re-default `payment_deferral` (in_default, `12m`): `1.96%`.
- Re-default `payment_deferral` (in_default, `24m`): `5.15%`.
- Re-default `payment_deferral` (performing, `12m`): `19.30%`.
- Re-default `payment_deferral` (performing, `24m`): `18.52%`.

## 5. Economy, Portfolio Mix & Data Fitness (`13` to `17`)
- **Macro default-rate correlations (`economy_correlations_mart`):** `unrate_pct` (lag `3m`: `r=+0.689`), `nat_hpi_chg_12m_pct` (lag `9m`: `r=-0.616`), `unrate_chg_12m` (lag `6m`: `r=+0.581`), `fed_funds_pct` (lag `0m`: `r=-0.417`).
- **Latest concentration HHI (`concentration_mart`):** `msa` (0.0201), `property_state` (0.0577), `seller_name` (0.2051).
- **Max historical PSI vs latest book (`representativeness_mart`):** `note_rate` (0.750), `ltv_indexed` (0.389), `dti` (0.254), `credit_score` (0.107), `loan_purpose` (0.060), `orig_ltv` (0.052), `property_state_tier` (0.003), `occupancy` (0.002).
- **Left-truncation / acquisition seasoning (`survivorship_mart`):** `1.22%` of loans acquired >3m after origination.
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
