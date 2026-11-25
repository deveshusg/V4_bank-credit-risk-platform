# Module 2: Portfolio analytics

Watches the loan book, validates monthly stock-and-flow tie-outs, applies UK CRR/PRA default
and probation rules (with documented US data departures), measures roll rates and competing-risk
vintage curves, indexes property values, tracks recoveries and relief performance, and hands
reconciled marts to Modules 3 to 8.

**Status:** Rebuilt to `02_portfolio_analytics/docs/module-2-design.md` (`D-030`, `D-031`, restructured per `restructure_plan.md`).
All scripts live in `scripts/`, tests in `tests/test_module2.py`, and configuration in `residential_mortgage/settings/*.toml`.

By default every run uses the **0.03% stratified sample DB** (`mortgages_sample.duckdb`) and writes into:
`residential_mortgage\00_data\processed\module_outputs\02_portfolio_analytics\sample\` (`module2_sample.duckdb`, `<script_stem>\` charts/snapshots/findings).

Opt-in full production runs (`--full`) read `mortgages.duckdb` and write into `...\module_outputs\02_portfolio_analytics\full\` (`module2.duckdb`).
Run the pipeline from repo root: `.venv\Scripts\python.exe residential_mortgage\02_portfolio_analytics\run_module2.py` (add `--full` for production, `--from-step NN` to resume, or `--dry-run` to preview).

| # | Script | What it builds | Reads first |
|---|---|---|---|
| 00 | `00_build_monthly_core.py` | 23-column typed monthly Parquet (`loan_monthly_core`) + `workout_exit_cashflows_mart` | Module 1 |
| 01 | `01_data_audit.py` | Count/balance roll-forward, continuity, plausibility & re-aging -> `balance_rollforward_mart`, `data_plausibility_mart` | `00` |
| 02 | `02_default_engine.py` | Default triggers, 3m/12m probation, Art 178(5A) upgrade, M2-4 COVID cap -> `default_events_mart`, `default_status_monthly`, `default_sensitivity_mart` | `00` |
| 03 | `03_roll_rates.py` | Transition matrices, projections, 4x4 & 3x3 absorption, 30-day evidence -> `roll_rates_mart`, `roll_projection_mart`, `roll_absorption_mart`, `roll_30day_evidence_mart` | `02` |
| 04 | `04_emergence_and_thresholds.py` | Arrears emergence lag & 60/90/120-day sensitivity -> `emergence_mart`, `threshold_sensitivity_mart` | `02` |
| 05 | `05_vintage_curves.py` | Aalen-Johansen CIF & voluntary SMM/CPR -> `vintage_curves_mart`, `loan_lifetime_mart` | `02` |
| 06 | `06_current_ltv.py` | Indexed & downward-only LTV + running-peak HPI drawdowns -> `loan_origination_value_mart`, `state_hpi_peaktotrough_mart`, `current_ltv_mart` | `00`, Module 1 macro |
| 07 | `07_default_rate_history.py` | Rolling 12m DR, Vasicek rho & December `book_snapshot` Parquet -> `default_rate_history_mart`, `implied_correlation_mart` | `02`, `06` |
| 08 | `08_sample_population.py` | Excluded vs included PD sample profile -> `sample_population_mart` | `07` |
| 09 | `09_risk_drivers.py` | Partitioned `book_snapshot_behavioural`, WOE/IV, PSI & correlations -> `risk_drivers_mart`, `feature_iv_mart`, `driver_correlation_mart` | `07` |
| 10 | `10_segmentation.py` | KS, Chi-square, KL tests, depth-4 pockets & 5y grid -> `segmentation_mart`, `interaction_pockets_mart`, `segment_sufficiency_mart` | `07` |
| 11 | `11_default_outcomes.py` | Economic net loss, FSD, cured-mod losses & observable triangle -> `default_outcomes_mart`, `loss_development_mart`, `recovery_summary_mart` | `00`, `02`, `06` |
| 12 | `12_forbearance.py` | Relief transitions (start vs stock) & 12m/24m re-default -> `forbearance_mart`, `redefault_mart` | `00`, `02` |
| 13 | `13_economy_links.py` | Quarterly rates, lagged macro joins & 0-24m correlations -> `portfolio_rates_quarterly_mart`, `economy_correlations_mart`, `macro_downturn_mart` | `02`, `05`, `11` |
| 14 | `14_cycle_and_benchmarks.py` | Downturn duration/half-life, 1m seasonality & APC -> `cycle_mart`, `seasonality_mart`, `apc_mart` | `07`, `13` |
| 15 | `15_portfolio_mix.py` | Book mix, SA LTV bands, state/MSA/seller HHI, EPD-3 & bounce -> `portfolio_mix_mart`, `concentration_mart`, `early_payment_default_mart`, `arrears_bounce_mart` | `06`, `07` |
| 16 | `16_representativeness.py` | Dec baseline PSI & Category A/B MoC limits -> `representativeness_mart`, `data_limits_mart` | `01`, `07`, `11`, `15` |
| 17 | `17_survivorship.py` | Late-acquisition seasoning & conditional survival -> `survivorship_mart` | `05`, Module 1 loans |
| 18 | `18_portfolio_findings.py` | Writes findings document purely from marts | `01`–`17` |
