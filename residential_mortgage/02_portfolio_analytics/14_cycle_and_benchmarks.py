"""Cycle duration, recovery speed, 1m seasonality and APC breakdown (Stage E, script 14).

Fixes all design review H5 & D2-B requirements:
- Measures downturn duration and recovery half-life from quarterly portfolio default rates.
- Measures 1-month hazard seasonality by calendar month directly from loan_monthly_core
  (default starts, voluntary prepayments '01', and cures) — never blurred by 12m rolling rates.
- Produces descriptive Age-Period-Cohort (APC) summary from vintage_curves_mart.
- Compares observed rates only against historical cohorts and loaded FRED/FHFA cycles
  (no unbuilt external MBA survey).

Outputs: cycle_mart, seasonality_mart, apc_mart.
Run: python residential_mortgage/02_portfolio_analytics/14_cycle_and_benchmarks.py [--sample]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


def run_cycle_and_benchmarks(marts: object, core_files: list[Path]) -> int:
    """Compute cycle duration, recovery half-life, 1m seasonality, and descriptive APC."""
    t0 = time.time()
    check = c.Checker("14_cycle_and_benchmarks: cycles, 1m seasonality and APC")

    q_rates = c.q(marts, """
        SELECT quarter_date, default_rate_ann, cure_rate_qtr, cpr_qtr, loss_severity,
               unrate_pct, nat_hpi_chg_12m_pct
        FROM portfolio_rates_quarterly_mart
        WHERE segment = 'ALL'
        ORDER BY quarter_date
    """)
    if not q_rates.empty:
        q_rates["quarter_date"] = pd.to_datetime(q_rates["quarter_date"])
        lra_mean = float(q_rates["default_rate_ann"].mean())
        lra_std = float(q_rates["default_rate_ann"].std(ddof=1)) if len(q_rates) > 1 else 0.0
        thresh = lra_mean + lra_std
        above = q_rates["default_rate_ann"] > thresh
        q_rates["ep_id"] = (above != above.shift()).cumsum()

        cycle_rows: list[dict] = []
        ep_num = 0
        last_q = q_rates["quarter_date"].max()
        for _, g in q_rates[above].groupby("ep_id"):
            ep_num += 1
            start_q = g["quarter_date"].min()
            end_q = g["quarter_date"].max()
            peak_idx = g["default_rate_ann"].idxmax()
            peak_q = q_rates.loc[peak_idx, "quarter_date"]
            peak_val = float(q_rates.loc[peak_idx, "default_rate_ann"])
            half_target = 0.5 * (peak_val + lra_mean)
            after_peak = q_rates[q_rates["quarter_date"] > peak_q]
            rec = after_peak[after_peak["default_rate_ann"] <= half_target]
            half_life_q = (
                ((rec["quarter_date"].iloc[0].year - peak_q.year) * 4 + (rec["quarter_date"].iloc[0].quarter - peak_q.quarter))
                if not rec.empty else None
            )
            cycle_rows.append({
                "cycle_name": f"ep_{ep_num}_{start_q.year}Q{start_q.quarter}",
                "metric_name": "default_rate_above_mean_plus_1sd",
                "start_quarter": f"{start_q.year}Q{start_q.quarter}",
                "peak_quarter": f"{peak_q.year}Q{peak_q.quarter}",
                "end_quarter": f"{end_q.year}Q{end_q.quarter}",
                "duration_quarters": int(len(g)),
                "peak_rate": peak_val,
                "recovery_halflife_quarters": float(half_life_q) if half_life_q is not None else np.nan,
                "ongoing_at_end": bool(end_q == last_q),
                "benchmark_lra_mean": lra_mean,
            })
        if not cycle_rows:
            cycle_rows.append({
                "cycle_name": "none_above_1sd",
                "metric_name": "default_rate_above_mean_plus_1sd",
                "start_quarter": "NA",
                "peak_quarter": "NA",
                "end_quarter": "NA",
                "duration_quarters": 0,
                "peak_rate": float(q_rates["default_rate_ann"].max()),
                "recovery_halflife_quarters": np.nan,
                "ongoing_at_end": False,
                "benchmark_lra_mean": lra_mean,
            })
        cycle_df = pd.DataFrame(cycle_rows)
    else:
        cycle_df = pd.DataFrame(columns=["cycle_name", "metric_name", "start_quarter", "peak_quarter", "end_quarter", "duration_quarters", "peak_rate", "recovery_halflife_quarters", "ongoing_at_end", "benchmark_lra_mean"])
    c.write_df(marts, "cycle_mart", cycle_df, ["cycle_name", "metric_name"])

    # 1-month calendar-month hazard seasonality (NOT 12m smoothed rates!)
    m_parts: list[pd.DataFrame] = []
    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        m_q = c.q(marts, f"""
            SELECT
                month(m.reporting_period)::INTEGER AS calendar_month,
                count(*) FILTER (WHERE m.zero_balance_code IS NULL AND ds.in_default IS NULL)::BIGINT AS perf_loan_months,
                count(*) FILTER (WHERE ds.in_default IS NOT NULL)::BIGINT AS default_loan_months,
                count(*) FILTER (WHERE m.zero_balance_code = '01' AND ds.in_default IS NULL)::BIGINT AS payoffs_1m
            FROM read_parquet('{fp}') m
            LEFT JOIN default_status_monthly ds
              ON ds.loan_id = m.loan_id AND ds.reporting_period = m.reporting_period
             AND ds.acquisition_quarter = '{quarter}'
            GROUP BY 1
        """)
        m_parts.append(m_q)

    seas_base = pd.concat(m_parts, ignore_index=True).groupby("calendar_month", as_index=False).sum(numeric_only=True)
    def_mo = c.q(marts, "SELECT month(default_month)::INTEGER AS calendar_month, count(*)::BIGINT AS def_starts FROM default_events_mart GROUP BY 1")
    cure_mo = c.q(marts, "SELECT month(cure_month)::INTEGER AS calendar_month, count(*)::BIGINT AS cures FROM default_events_mart WHERE cure_month IS NOT NULL GROUP BY 1")
    seas_base = seas_base.merge(def_mo, on="calendar_month", how="left").merge(cure_mo, on="calendar_month", how="left").fillna(0)

    seas_rows: list[dict] = []
    for metric, num_c, den_c in [
        ("monthly_default_hazard", "def_starts", "perf_loan_months"),
        ("monthly_prepay_hazard", "payoffs_1m", "perf_loan_months"),
        ("monthly_cure_hazard", "cures", "default_loan_months"),
    ]:
        rates_m = seas_base[num_c] / seas_base[den_c].clip(lower=1)
        overall_m = float(seas_base[num_c].sum() / max(seas_base[den_c].sum(), 1))
        for cm, r_val, num_v, den_v in zip(seas_base["calendar_month"], rates_m, seas_base[num_c], seas_base[den_c]):
            seas_rows.append({
                "calendar_month": int(cm),
                "metric_name": metric,
                "numerator": int(num_v),
                "denominator": int(den_v),
                "monthly_rate": float(r_val),
                "seasonal_factor": float(r_val / overall_m) if overall_m > 0 else 1.0,
            })
    seas_df = pd.DataFrame(seas_rows)
    c.write_df(marts, "seasonality_mart", seas_df, ["calendar_month", "metric_name"])

    # Descriptive Age-Period-Cohort table from origination_quarter vintage_curves_mart
    apc_df = c.q(marts, """
        WITH vc AS (
            SELECT
                CAST(substr(cohort_quarter, 1, 4) AS INTEGER) AS cohort_year,
                CASE
                    WHEN mob < 12 THEN '00_11m'
                    WHEN mob < 24 THEN '12_23m'
                    WHEN mob < 36 THEN '24_35m'
                    WHEN mob < 60 THEN '36_59m'
                    ELSE '60m+'
                END AS age_bucket,
                (CAST(substr(cohort_quarter, 1, 4) AS INTEGER) + CAST(FLOOR(mob / 12.0) AS INTEGER))::INTEGER AS period_year,
                sum(at_risk)::BIGINT AS loan_months_at_risk,
                sum(defaults)::BIGINT AS defaults,
                sum(payoffs)::BIGINT AS payoffs
            FROM vintage_curves_mart
            WHERE cohort_type = 'origination_quarter' AND mob >= 0
            GROUP BY 1, 2, 3
        )
        SELECT
            cohort_year,
            age_bucket,
            period_year,
            loan_months_at_risk,
            defaults,
            payoffs,
            CAST(defaults AS DOUBLE) / GREATEST(loan_months_at_risk, 1) * 12.0 AS annualized_default_hazard,
            CAST(payoffs AS DOUBLE) / GREATEST(loan_months_at_risk, 1) * 12.0 AS annualized_prepay_hazard
        FROM vc
        ORDER BY 1, 2, 3
    """)
    c.write_df(marts, "apc_mart", apc_df, ["cohort_year", "age_bucket", "period_year"])

    check.key(marts, "cycle_mart", ["cycle_name", "metric_name"])
    check.key(marts, "seasonality_mart", ["calendar_month", "metric_name"])
    check.key(marts, "apc_mart", ["cohort_year", "age_bucket", "period_year"])
    check.add("12 calendar months measured cleanly for seasonality", int(seas_df["calendar_month"].nunique()) == 12 if not seas_df.empty else False)
    print(f"  14 cycle & 1m seasonality finished in {time.time() - t0:.1f}s", flush=True)
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Downturn cycles, 1m seasonality and APC table.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    core_files = c.list_core_files(args.core_dir)
    rc = run_cycle_and_benchmarks(marts, core_files)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
