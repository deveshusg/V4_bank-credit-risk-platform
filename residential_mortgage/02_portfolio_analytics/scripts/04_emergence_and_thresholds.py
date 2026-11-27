"""Emergence period and 60/90/120-day threshold sensitivity (Stage B, script 04).

Measures:
1. How many contiguous months pass from uninterrupted first missed payment
   (adj_dpd >= 1) to default recognition for arrears-triggered defaults, by era.
2. Portfolio incidence sensitivity across 2m (60+), 3m (90+ baseline), and 4m
   (120+) arrears cut-offs using loan_monthly_core.

Outputs: emergence_mart, threshold_sensitivity_mart.
Run: python residential_mortgage/02_portfolio_analytics/scripts/04_emergence_and_thresholds.py [--full]
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402
roll_mod = importlib.import_module("03_roll_rates")


# Measure loss emergence curves across 1-to-24 months and compare 30d/60d/90d/180d DPD thresholds
# Aggregates defaults and early-arrears conversion statistics in DuckDB across core Parquets
def run_emergence(marts: object, core_files: list[Path]) -> int:
    """Compute arrears emergence lags and 60/90/120-day sensitivity."""
    t0 = time.time()
    check = c.Checker("04_emergence_and_thresholds: emergence lag and 60/90/120-day thresholds")

    lag_parts: list[pd.DataFrame] = []
    sens_parts: list[pd.DataFrame] = []

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        adj_tbl = roll_mod.covid_adjust_quarter_df(marts, f)

        # Back-trace each arrears default event up to 24 months to contiguous spell start
        lags_q = c.q(marts, f"""
            WITH ev AS (
                SELECT loan_id, default_month, trigger_type, re_default_number,
                       {c.era_case('default_month')} AS era
                FROM default_events_mart
                WHERE acquisition_quarter = '{quarter}'
                  AND trigger_type LIKE '%arrears%'
            ),
            hist AS (
                SELECT
                    e.loan_id,
                    e.default_month,
                    e.re_default_number,
                    e.trigger_type,
                    e.era,
                    m.reporting_period,
                    COALESCE(ca.adj_dpd, m.delinquency_months) AS adj_dpd
                FROM ev e
                JOIN read_parquet('{fp}') m
                  ON m.loan_id = e.loan_id
                 AND m.reporting_period <= e.default_month
                 AND m.reporting_period >= e.default_month - INTERVAL 24 MONTH
                LEFT JOIN {adj_tbl} ca
                  ON ca.loan_id = m.loan_id AND ca.reporting_period = m.reporting_period
            ),
            clean_or_gap AS (
                SELECT
                    loan_id, default_month, re_default_number,
                    max(reporting_period) FILTER (WHERE adj_dpd = 0) AS last_clean_before_def
                FROM hist
                WHERE reporting_period < default_month
                GROUP BY 1, 2, 3
            ),
            spell AS (
                SELECT
                    h.loan_id,
                    h.default_month,
                    h.re_default_number,
                    h.trigger_type,
                    h.era,
                    min(h.reporting_period) FILTER (
                        WHERE h.adj_dpd >= 1
                          AND (cg.last_clean_before_def IS NULL OR h.reporting_period > cg.last_clean_before_def)
                    ) AS spell_start
                FROM hist h
                LEFT JOIN clean_or_gap cg
                  ON cg.loan_id = h.loan_id
                 AND cg.default_month = h.default_month
                 AND cg.re_default_number = h.re_default_number
                GROUP BY 1, 2, 3, 4, 5
            )
            SELECT
                era,
                trigger_type,
                LEAST(GREATEST(datediff('month', COALESCE(spell_start, default_month), default_month), 0), 24) AS lag_months,
                count(*)::BIGINT AS events
            FROM spell
            GROUP BY 1, 2, 3
        """)
        if not lags_q.empty:
            lag_parts.append(lags_q)

        # Threshold sensitivity per loan-era first crossing of 2, 3, 4 months behind (plus active base)
        sens_q = c.q(marts, f"""
            WITH m AS (
                SELECT
                    m.loan_id,
                    {c.era_case('m.reporting_period')} AS era,
                    COALESCE(ca.adj_dpd, m.delinquency_months) AS adj_dpd
                FROM read_parquet('{fp}') m
                LEFT JOIN {adj_tbl} ca
                  ON ca.loan_id = m.loan_id AND ca.reporting_period = m.reporting_period
                WHERE NOT m.is_dpd_unknown
            ),
            per_loan_era AS (
                SELECT
                    era,
                    loan_id,
                    max(COALESCE(adj_dpd, -1)) AS max_dpd
                FROM m
                GROUP BY 1, 2
            )
            SELECT era, 2::INTEGER AS dpd_threshold_months, count(*) FILTER (WHERE max_dpd >= 2)::BIGINT AS loans_reaching, count(*)::BIGINT AS total_loans FROM per_loan_era GROUP BY 1
            UNION ALL
            SELECT era, 3::INTEGER, count(*) FILTER (WHERE max_dpd >= 3)::BIGINT, count(*)::BIGINT FROM per_loan_era GROUP BY 1
            UNION ALL
            SELECT era, 4::INTEGER, count(*) FILTER (WHERE max_dpd >= 4)::BIGINT, count(*)::BIGINT FROM per_loan_era GROUP BY 1
        """)
        if not sens_q.empty:
            sens_parts.append(sens_q)

        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] scanned {quarter} ({time.time() - t0:.1f}s)", flush=True)

    marts.execute("DROP TABLE IF EXISTS _q_covid_adj")

    if lag_parts:
        em_agg = (
            pd.concat(lag_parts, ignore_index=True)
            .groupby(["era", "trigger_type", "lag_months"], as_index=False)
            .sum(numeric_only=True)
        )
        em_agg["metric_bucket"] = em_agg["lag_months"].map(lambda x: f"{int(x):02d}m")
        totals = em_agg.groupby(["era", "trigger_type"])["events"].transform("sum")
        em_agg["share"] = em_agg["events"] / totals.clip(lower=1)
        em_out = em_agg[["era", "trigger_type", "metric_bucket", "lag_months", "events", "share"]].copy()
    else:
        em_out = pd.DataFrame(columns=["era", "trigger_type", "metric_bucket", "lag_months", "events", "share"])

    c.write_df(marts, "emergence_mart", em_out, ["era", "trigger_type", "metric_bucket"])

    sens_agg = (
        pd.concat(sens_parts, ignore_index=True)
        .groupby(["era", "dpd_threshold_months"], as_index=False)
        .sum(numeric_only=True)
    )
    sens_agg["incidence_rate"] = sens_agg["loans_reaching"] / sens_agg["total_loans"].clip(lower=1)
    c.write_df(marts, "threshold_sensitivity_mart", sens_agg, ["era", "dpd_threshold_months"])

    # Verify monotonicity 2m >= 3m >= 4m per era
    mono_ok = True
    for _, g in sens_agg.groupby("era"):
        gs = g.sort_values("dpd_threshold_months")["loans_reaching"].tolist()
        if len(gs) == 3 and not (gs[0] >= gs[1] >= gs[2]):
            mono_ok = False

    check.key(marts, "emergence_mart", ["era", "trigger_type", "metric_bucket"])
    check.key(marts, "threshold_sensitivity_mart", ["era", "dpd_threshold_months"])
    check.add("emergence lags within [0, 24] months", bool((em_out["lag_months"].between(0, 24)).all()) if not em_out.empty else True)
    check.add("60 >= 90 >= 120-day loan counts monotonically ordered per era", mono_ok)

    if not em_out.empty:
        tot_ev = em_out["events"].sum()
        mean_lag = (em_out["lag_months"] * em_out["events"]).sum() / max(tot_ev, 1)
        print(f"  mean emergence lag across {int(tot_ev):,} arrears defaults: {mean_lag:.2f} months", flush=True)
    return check.finish()


# Parse CLI arguments for 04_emergence_and_thresholds
# Registers standard Module 2 database and sample/--full flags
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emergence period and 60/90/120-day threshold sensitivity.")
    c.add_common_args(parser)
    return parser.parse_args()


# Connect to marts DB and generate loss_emergence_mart and threshold_comparison_mart
# Verifies scope match, locates core Parquet partitions, and runs emergence assertions
def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    core_files = c.list_core_files(args.core_dir)
    rc = run_emergence(marts, core_files)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
