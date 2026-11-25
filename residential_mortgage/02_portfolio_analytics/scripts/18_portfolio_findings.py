"""Portfolio findings generator (Stage G, script 18).

- Writes strictly into module_outputs/02_portfolio_analytics/{sample|full}/18_portfolio_findings/18_portfolio_findings.md,
  protecting production runs from sample overwrites.
- Reads ONLY finished Module 2 marts (01..17); references absorbed plausibility checks under 01_data_audit.py.
- Uses plain numbers (no raw $ signs breaking markdown/LaTeX), prints Wilson 95% confidence
  intervals where relevant, and populates the Module 3-8 mart handover summary.

Run: python residential_mortgage/02_portfolio_analytics/scripts/18_portfolio_findings.py [--full]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


def generate_findings(marts: object, out_md: Path, scope_label: str) -> int:
    """Assemble markdown findings document strictly from queried mart tables."""
    check = c.Checker("18_portfolio_findings: findings markdown generation")
    out: list[str] = []
    add = out.append

    add("# Module 2 Findings: Portfolio Analytics\n")
    add(f"Generated {date.today().isoformat()} from Module 2 marts (`{scope_label}` run).\n")
    add("Every figure below is queried directly from Module 2 mart tables.\n")

    # 1. Stage A
    bf = c.q(marts, "SELECT * FROM balance_rollforward_mart ORDER BY reporting_period DESC LIMIT 1").iloc[0]
    add("\n## 1. Foundations (`00_build_monthly_core`, `01_data_audit`, `02_default_engine`)\n")
    add(f"- **Balance roll-forward (`balance_rollforward_mart`):** latest month `{str(bf['reporting_period'])[:10]}`, "
        f"`{int(bf['open_loans']):,}` active loans, closing UPB `{bf['closing_upb']:,.0f}` USD, "
        f"count residual `{int(bf['count_residual']):,}`, unexplained `{bf['unexplained_upb']:,.0f}` USD.\n")

    pl = c.q(marts, "SELECT metric_name, value, share_pct FROM data_plausibility_mart WHERE year = 'ALL' ORDER BY metric_name")
    add(f"- **Continuity & plausibility (`01_data_audit.py` -> `data_plausibility_mart`):** `{len(pl)}` global checks stored.\n")
    for r in pl.itertuples():
        add(f"  - `{r.metric_name}`: `{r.value:,.0f}` (`{r.share_pct:.4f}%`)\n")

    ev = c.q(marts, "SELECT count(*) AS ev_n, count(DISTINCT loan_id) AS loans_n FROM default_events_mart").iloc[0]
    sens = c.q(marts, "SELECT treatment, sum(events) AS ev_n FROM default_sensitivity_mart GROUP BY 1 ORDER BY 1")
    sens_txt = ", ".join(f"{r.treatment}: {int(r.ev_n):,}" for r in sens.itertuples())
    add(f"- **Default & probation (`default_events_mart`):** `{int(ev['ev_n']):,}` events across `{int(ev['loans_n']):,}` loans (`{sens_txt}`).\n")

    # 2. Stage B
    add("\n## 2. Arrears Transitions, Vintages, LTV and 12m History (`03` to `08`)\n")
    ev30 = c.q(marts, "SELECT * FROM roll_30day_evidence_mart ORDER BY horizon_window, first_arrears_band")
    add("- **IFRS 9 30-day backstop (`roll_30day_evidence_mart`, Wilson 95% CI):**\n")
    for r in ev30.itertuples():
        add(f"  - `{r.first_arrears_band}` (`{r.horizon_window}`): `{r.default_rate:.2%}` "
            f"[95% CI `{r.ci95_low:.2%}` to `{r.ci95_high:.2%}`, Wilson score] (`{int(r.defaulted_loans):,}/{int(r.loans):,}`)\n")

    tsens = c.q(marts, "SELECT dpd_threshold_months, sum(loans_reaching) AS r_n, sum(total_loans) AS t_n FROM threshold_sensitivity_mart GROUP BY 1 ORDER BY 1")
    add("- **60/90/120-day sensitivity (`threshold_sensitivity_mart`):** " +
        ", ".join(f"{int(r.dpd_threshold_months)}m: {int(r.r_n):,}" for r in tsens.itertuples()) + ".\n")

    pt = c.q(marts, "SELECT state, fall_pct, peak_date, trough_date FROM state_hpi_peaktotrough_mart ORDER BY fall_pct DESC LIMIT 5")
    add("- **Top 5 peak-to-trough state HPI falls (`state_hpi_peaktotrough_mart`):**\n")
    for r in pt.itertuples():
        add(f"  - `{r.state}`: `-{r.fall_pct:.1f}%` (`{str(r.peak_date)[:10]}` to `{str(r.trough_date)[:10]}`)\n")

    wb = c.q(marts, "SELECT * FROM default_rate_history_mart WHERE series_group='whole_book' AND window_complete")
    lra = float(wb["bad_loans_12m"].sum() / max(wb["performing_loans"].sum(), 1))
    corr_all = c.q(marts, "SELECT * FROM implied_correlation_mart WHERE segment='all'").iloc[0]
    add(f"- **Long-run 12m PD (`default_rate_history_mart`, complete windows <= 2024-12):** `{lra:.4%}` count-weighted.\n")
    add(f"- **Implied Vasicek correlation (`implied_correlation_mart`):** `{corr_all['implied_rho']:.4f}` vs IRB `0.1500`.\n")

    sp_tot = c.q(marts, "SELECT population_group, sum(loans) AS n FROM sample_population_mart GROUP BY 1 ORDER BY 1")
    add("- **PD sample scope (`sample_population_mart`):** " +
        ", ".join(f"{r.population_group}: {int(r.n):,}" for r in sp_tot.itertuples()) + ".\n")

    # 3. Stage C
    add("\n## 3. Risk Drivers & Segmentation (`09`, `10`)\n")
    top_iv = c.q(marts, "SELECT feature_name, avg(information_value) AS mean_iv FROM feature_iv_mart GROUP BY 1 ORDER BY 2 DESC LIMIT 6")
    add("- **Top features by mean IV across eras (`feature_iv_mart`):** " +
        ", ".join(f"`{r.feature_name}` ({r.mean_iv:.3f})" for r in top_iv.itertuples()) + ".\n")

    # 4. Stage D
    add("\n## 4. After Default & Relief (`11`, `12`)\n")
    do_sum = c.q(marts, """
        SELECT
            outcome_category,
            count(*) AS n,
            COALESCE(sum(CAST(balance_at_default AS DOUBLE)), 0.0) AS def_upb,
            COALESCE(sum(CAST(net_loss AS DOUBLE)), 0.0) AS nl,
            COALESCE(sum(CAST(mod_non_interest_upb_max AS DOUBLE)), 0.0) AS mniu,
            COALESCE(sum(CAST(principal_forgiveness_sum AS DOUBLE)), 0.0) AS pf
        FROM default_outcomes_mart
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    for r in do_sum.itertuples():
        extra = ""
        if r.outcome_category == "credit exit" and r.def_upb > 0:
            extra = f" (`{r.nl / r.def_upb:.2%}` of `{r.def_upb:,.0f}` USD UPB)"
        elif r.mniu > 0 or r.pf > 0:
            extra = f" (mod non-interest UPB `{r.mniu:,.0f}` USD, principal forgiveness `{r.pf:,.0f}` USD)"
        add(f"- Outcome `{r.outcome_category}`: `{int(r.n):,}` events, net loss sum `{r.nl:,.0f}` USD{extra}.\n")
    rec_agg = c.q(marts, """
        SELECT count(*) FILTER (WHERE forced_sale_discount IS NOT NULL) AS liq_n,
               avg(forced_sale_discount) FILTER (WHERE forced_sale_discount IS NOT NULL) AS mean_fsd
        FROM default_outcomes_mart
    """).iloc[0]
    if rec_agg["mean_fsd"] is not None:
        add(f"- **Liquidation forced-sale discount (`default_outcomes_mart`):** `{float(rec_agg['mean_fsd']):.2%}` mean across `{int(rec_agg['liq_n']):,}` property liquidations.\n")
    rd = c.q(marts, "SELECT event_type, initial_status_on_entry, horizon_months, sum(subsequent_defaults)*1.0/GREATEST(sum(eligible_entries),1) AS rate FROM redefault_mart GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")
    for r in rd.itertuples():
        note = " (coincides with 12m Art. 178(5A) modification probation)" if r.event_type == "modification" and r.initial_status_on_entry == "in_default" and int(r.horizon_months) == 12 else ""
        add(f"- Re-default `{r.event_type}` ({r.initial_status_on_entry}, `{int(r.horizon_months)}m`): `{r.rate:.2%}`{note}.\n")

    # 5. Stage E & F
    add("\n## 5. Economy, Portfolio Mix & Data Fitness (`13` to `17`)\n")
    eco_top = c.q(marts, """
        SELECT series_name, rate_name, lag_months, pearson_corr
        FROM economy_correlations_mart
        WHERE rate_name = 'default_rate_ann' AND geography = 'US_NATIONAL'
        QUALIFY row_number() OVER (PARTITION BY series_name ORDER BY abs(pearson_corr) DESC) = 1
        ORDER BY abs(pearson_corr) DESC
    """)
    if not eco_top.empty:
        add("- **Macro default-rate correlations (`economy_correlations_mart`):** " +
            ", ".join(f"`{r.series_name}` (lag `{int(r.lag_months)}m`: `r={r.pearson_corr:+.3f}`)" for r in eco_top.itertuples()) + ".\n")
    hhi_lat = c.q(marts, """
        SELECT concentration_dim, hhi
        FROM concentration_mart
        WHERE snapshot_year = (SELECT max(snapshot_year) FROM concentration_mart)
        ORDER BY concentration_dim
    """)
    if not hhi_lat.empty:
        add("- **Latest concentration HHI (`concentration_mart`):** " +
            ", ".join(f"`{r.concentration_dim}` ({r.hhi:.4f})" for r in hhi_lat.itertuples()) + ".\n")
    psi_sum = c.q(marts, "SELECT driver_name, max(psi_vs_today) AS max_psi FROM representativeness_mart GROUP BY 1 ORDER BY 2 DESC")
    add("- **Max historical PSI vs latest book (`representativeness_mart`):** " +
        ", ".join(f"`{r.driver_name}` ({r.max_psi:.3f})" for r in psi_sum.itertuples()) + ".\n")
    surv_pct = c.scalar(marts, "SELECT sum(seasoned_gt3m_loans)*100.0/GREATEST(sum(loans),1) FROM survivorship_mart WHERE cohort_metric='acquisition_seasoning'")
    if surv_pct is not None:
        add(f"- **Left-truncation / acquisition seasoning (`survivorship_mart`):** `{float(surv_pct):.2f}%` of loans acquired >3m after origination.\n")
    lim_cnt = int(c.scalar(marts, "SELECT count(*) FROM data_limits_mart") or 0)
    add(f"- **Category A/B MoC limits (`data_limits_mart`):** `{lim_cnt}` limits quantified.\n")

    # 6. Handover table summary
    add("\n## 6. Modules 3 to 8 Mart Handover Register\n")
    add("| Module | Key marts / datasets consumed |\n|---|---|\n")
    add("| Module 3 (PD) | `default_events_mart`, `default_rate_history_mart`, `book_snapshot`, `book_snapshot_behavioural`, `risk_drivers_mart`, `segmentation_mart`, `representativeness_mart`, `data_limits_mart` |\n")
    add("| Module 4 (LGD & EAD) | `default_outcomes_mart`, `loss_development_mart`, `recovery_summary_mart`, `workout_exit_cashflows_mart`, `state_hpi_peaktotrough_mart` |\n")
    add("| Module 5 (IFRS 9) | `roll_30day_evidence_mart`, `vintage_curves_mart`, `default_outcomes_mart`, `forbearance_mart`, `redefault_mart`, `cycle_mart` |\n")
    add("| Module 6 (Capital) | `book_snapshot`, `current_ltv_mart`, `portfolio_mix_mart`, `concentration_mart`, `implied_correlation_mart`, `loan_origination_value_mart` |\n")
    add("| Module 7 (Stress Testing) | `portfolio_rates_quarterly_mart`, `economy_correlations_mart`, `macro_downturn_mart`, `cycle_mart`, `book_snapshot` |\n")
    add("| Module 8 (Model Risk) | `balance_rollforward_mart`, `data_plausibility_mart`, `representativeness_mart`, `data_limits_mart`, `survivorship_mart` |\n")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("".join(out), encoding="utf-8")
    check.add("findings report written cleanly", out_md.exists() and out_md.stat().st_size > 200, str(out_md))
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Module 2 findings report strictly from finished marts.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    out_md = c.script_out(args.outputs_dir, "18_portfolio_findings") / "18_portfolio_findings.md"
    scope_desc = f"{c.SAMPLE_RATE * 100:.4g}% sample" if args.sample else "full data"
    rc = generate_findings(marts, out_md, scope_desc)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
