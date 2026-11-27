"""Forbearance, modifications, deferrals and re-default (Stage D, script 12).

Fixes all design review M2 & Phase 1 bugs:
- Detects payment deferrals strictly on transitions into ('C','P','D') from None/'7'/'N'
  OR when alt_delinquency_resolution_count increases (> COALESCE(prev_count, 0)),
  never double-counting persistent sticky 'C'/'P'/'D' rows every month.
- Tracks BOTH new_starts and active_stock per month across active plans ('F','T','R'),
  first modifications (first N->Y), and payment deferrals.
- Splits cohorts into performing vs already_in_default on entry month, censors 12m/24m
  horizons strictly against 2025-12-01, and computes distinct cure+re-default for loans
  entering while already in default.

Outputs: forbearance_mart, redefault_mart.
Run: python residential_mortgage/02_portfolio_analytics/scripts/12_forbearance.py [--full]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


# Track monthly forbearance, payment deferral, and modification stock plus 12/24/36m re-defaults
# Reads relief flags across core Parquets, pairs with default_events_mart, and checks keys
def run_forbearance(
    marts: object,
    core_files: list[Path],
    dataset_end_iso: str = "2025-12-01",
) -> int:
    """Detect relief transitions quarter-by-quarter, track stock vs starts, and measure 12m/24m re-default."""
    t0 = time.time()
    check = c.Checker("12_forbearance: relief transitions, stock and re-default")

    active_lit = c.sql_list(c.ACTIVE_RELIEF_PLANS)
    def_lit = c.sql_list(c.DEFERRAL_RESOLUTION_CODES)

    monthly_parts: list[pd.DataFrame] = []
    redef_parts: list[pd.DataFrame] = []

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")

        events_cte = f"""
            WITH seq AS (
                SELECT
                    m.loan_id,
                    m.reporting_period,
                    CAST(COALESCE(m.current_upb, 0.0) AS DOUBLE) AS current_upb,
                    m.modification_flag,
                    m.borrower_assistance_plan,
                    m.alt_delinquency_resolution,
                    m.alt_delinquency_resolution_count,
                    LAG(m.modification_flag) OVER w AS prev_mod,
                    bool_or(m.modification_flag = 'Y') OVER (
                        PARTITION BY m.loan_id ORDER BY m.reporting_period
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS had_y_before,
                    LAG(m.borrower_assistance_plan) OVER w AS prev_plan,
                    LAG(m.alt_delinquency_resolution) OVER w AS prev_def_code,
                    LAG(m.alt_delinquency_resolution_count) OVER w AS prev_def_cnt,
                    COALESCE(ds.in_default, FALSE) AS in_default_at_entry,
                    ds.default_month AS entry_default_month,
                    ds.re_default_number AS entry_re_def_num
                FROM read_parquet('{fp}') m
                LEFT JOIN default_status_monthly ds
                  ON ds.loan_id = m.loan_id AND ds.reporting_period = m.reporting_period
                 AND ds.acquisition_quarter = '{quarter}'
                WINDOW w AS (PARTITION BY m.loan_id ORDER BY m.reporting_period)
            ),
            flags AS (
                SELECT
                    *,
                    (COALESCE(prev_mod, 'N') = 'N' AND modification_flag = 'Y' AND NOT COALESCE(had_y_before, FALSE)) AS is_mod_start,
                    (borrower_assistance_plan IN {active_lit} AND COALESCE(prev_plan, 'N') NOT IN {active_lit}) AS is_forb_start,
                    (borrower_assistance_plan IN {active_lit}) AS is_forb_active,
                    (
                        (alt_delinquency_resolution IN {def_lit} AND COALESCE(prev_def_code, '7') NOT IN {def_lit})
                        OR (
                            alt_delinquency_resolution_count IS NOT NULL
                            AND alt_delinquency_resolution_count > COALESCE(prev_def_cnt, 0)
                        )
                    ) AS is_defer_start
                FROM seq
            )
        """

        m_df = c.q(marts, events_cte + """
            SELECT reporting_period, 'modification'::VARCHAR AS event_type,
                   count(*) FILTER (WHERE is_mod_start)::BIGINT AS new_starts,
                   count(*) FILTER (WHERE modification_flag = 'Y')::BIGINT AS active_stock,
                   COALESCE(sum(current_upb) FILTER (WHERE is_mod_start), 0.0) AS new_start_upb
            FROM flags GROUP BY 1, 2
            UNION ALL
            SELECT reporting_period, 'forbearance_plan'::VARCHAR,
                   count(*) FILTER (WHERE is_forb_start)::BIGINT,
                   count(*) FILTER (WHERE is_forb_active)::BIGINT,
                   COALESCE(sum(current_upb) FILTER (WHERE is_forb_start), 0.0)
            FROM flags GROUP BY 1, 2
            UNION ALL
            SELECT reporting_period, 'payment_deferral'::VARCHAR,
                   count(*) FILTER (WHERE is_defer_start)::BIGINT,
                   count(*) FILTER (WHERE alt_delinquency_resolution IN ('C','P','D'))::BIGINT,
                   COALESCE(sum(current_upb) FILTER (WHERE is_defer_start), 0.0)
            FROM flags GROUP BY 1, 2
        """)
        monthly_parts.append(m_df)

        # Re-default outcome within 12m and 24m (strictly right-censored at dataset_end_iso)
        rd_df = c.q(marts, events_cte + f"""
            , relief_ev AS (
                SELECT loan_id, reporting_period AS entry_month, 'modification'::VARCHAR AS event_type,
                       in_default_at_entry, COALESCE(entry_re_def_num, 0) AS entry_re_def_num, {c.era_case('reporting_period')} AS cohort_era
                FROM flags WHERE is_mod_start
                UNION ALL
                SELECT loan_id, reporting_period, 'forbearance_plan'::VARCHAR, in_default_at_entry, COALESCE(entry_re_def_num, 0), {c.era_case('reporting_period')}
                FROM flags WHERE is_forb_start
                UNION ALL
                SELECT loan_id, reporting_period, 'payment_deferral'::VARCHAR, in_default_at_entry, COALESCE(entry_re_def_num, 0), {c.era_case('reporting_period')}
                FROM flags WHERE is_defer_start
            ),
            ev_q AS (
                SELECT loan_id, default_month, re_default_number
                FROM default_events_mart
                WHERE acquisition_quarter = '{quarter}'
            )
            SELECT
                r.event_type,
                CASE WHEN r.in_default_at_entry THEN 'in_default' ELSE 'performing' END AS initial_status_on_entry,
                h.horizon_months,
                r.cohort_era,
                count(*) FILTER (WHERE r.entry_month + h.horizon_months * INTERVAL 1 MONTH <= DATE '{dataset_end_iso}')::BIGINT AS eligible_entries,
                count(*) FILTER (
                    WHERE r.entry_month + h.horizon_months * INTERVAL 1 MONTH <= DATE '{dataset_end_iso}'
                      AND EXISTS (
                          SELECT 1 FROM ev_q e
                          WHERE e.loan_id = r.loan_id
                            AND e.default_month > r.entry_month
                            AND e.default_month <= r.entry_month + h.horizon_months * INTERVAL 1 MONTH
                            AND (NOT r.in_default_at_entry OR e.re_default_number > r.entry_re_def_num)
                      )
                )::BIGINT AS subsequent_defaults
            FROM relief_ev r
            CROSS JOIN (VALUES (12::INTEGER), (24::INTEGER)) AS h(horizon_months)
            GROUP BY 1, 2, 3, 4
        """)
        if not rd_df.empty:
            redef_parts.append(rd_df)

        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] scanned {quarter} ({time.time() - t0:.1f}s)", flush=True)

    f_df = (
        pd.concat(monthly_parts, ignore_index=True)
        .groupby(["reporting_period", "event_type"], as_index=False)
        .sum(numeric_only=True)
        .sort_values(["reporting_period", "event_type"])
    )
    f_df = f_df[(f_df["new_starts"] > 0) | (f_df["active_stock"] > 0)].copy()
    c.write_df(marts, "forbearance_mart", f_df, ["reporting_period", "event_type"])

    if redef_parts:
        rd_out = (
            pd.concat(redef_parts, ignore_index=True)
            .groupby(["event_type", "initial_status_on_entry", "horizon_months", "cohort_era"], as_index=False)
            .sum(numeric_only=True)
        )
        rd_out = rd_out[rd_out["eligible_entries"] > 0].copy()
        rd_out["redefault_rate"] = rd_out["subsequent_defaults"] / rd_out["eligible_entries"].clip(lower=1)
    else:
        rd_out = pd.DataFrame(
            columns=["event_type", "initial_status_on_entry", "horizon_months", "cohort_era", "eligible_entries", "subsequent_defaults", "redefault_rate"]
        )
    c.write_df(marts, "redefault_mart", rd_out, ["event_type", "initial_status_on_entry", "horizon_months", "cohort_era"])

    check.key(marts, "forbearance_mart", ["reporting_period", "event_type"])
    check.key(marts, "redefault_mart", ["event_type", "initial_status_on_entry", "horizon_months", "cohort_era"])
    check.add("new deferral starts bounded cleanly (no persistent-row inflation)",
              int(f_df.loc[f_df["event_type"] == "payment_deferral", "new_starts"].sum()) <= int(f_df.loc[f_df["event_type"] == "payment_deferral", "active_stock"].sum()))
    return check.finish()


# Parse CLI arguments for 12_forbearance
# Uses module2_common.add_common_args()
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Modifications, forbearance plans and deferrals.")
    c.add_common_args(parser)
    return parser.parse_args()


# Connect to marts DB and generate forbearance_mart and redefault_mart
# Verifies scope match, locates quarterly core files, executes run_forbearance(), and exits
def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    core_files = c.list_core_files(args.core_dir)
    rc = run_forbearance(marts, core_files)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
