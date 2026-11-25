"""Representativeness PSI, baseline Dec 2025 shares and Category A/B MoC limits (Stage F, script 16).

Fixes all design review M4 & C4 defects:
- Executes completely inside DuckDB SQL (never loads 280M book_snapshot rows into pandas).
- Stores frozen Dec 2025 per-band baseline shares inside representativeness_mart
  so Module 8 model monitoring compares future books cleanly.
- Reads origination_restatements_table, feature_catalogue_table, data_plausibility_mart,
  default_outcomes_mart, loans_table, and loan_origination_value_mart to size ALL
  Category A (data limits) and Category B (lending & servicing shifts) inputs for Margin of Conservatism.

Outputs: representativeness_mart, data_limits_mart.
Run: python residential_mortgage/02_portfolio_analytics/16_representativeness.py [--sample]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


DRIVER_BINS = {
    "credit_score": "CASE WHEN credit_score IS NULL THEN 'missing' WHEN credit_score < 620 THEN '<620' WHEN credit_score < 660 THEN '620-659' WHEN credit_score < 700 THEN '660-699' WHEN credit_score < 740 THEN '700-739' WHEN credit_score < 780 THEN '740-779' ELSE '780+' END",
    "orig_ltv": "CASE WHEN orig_ltv IS NULL THEN 'missing' WHEN orig_ltv <= 60 THEN '<=60' WHEN orig_ltv <= 70 THEN '61-70' WHEN orig_ltv <= 80 THEN '71-80' WHEN orig_ltv <= 90 THEN '81-90' ELSE '>90' END",
    "dti": "CASE WHEN dti IS NULL THEN 'missing' WHEN dti <= 20 THEN '<=20' WHEN dti <= 30 THEN '21-30' WHEN dti <= 40 THEN '31-40' WHEN dti <= 50 THEN '41-50' ELSE '>50' END",
    "occupancy": "COALESCE(occupancy, 'missing')",
    "loan_purpose": "COALESCE(loan_purpose, 'missing')",
    "note_rate": "CASE WHEN note_rate IS NULL THEN 'missing' WHEN note_rate < 3.5 THEN '<3.5%' WHEN note_rate < 4.5 THEN '3.5-4.49%' WHEN note_rate < 5.5 THEN '4.5-5.49%' WHEN note_rate < 6.5 THEN '5.5-6.49%' ELSE '6.5%+' END",
    "ltv_indexed": "CASE WHEN ltv_indexed IS NULL THEN 'missing' WHEN ltv_indexed <= 60 THEN '<=60' WHEN ltv_indexed <= 80 THEN '60-80' WHEN ltv_indexed <= 100 THEN '80-100' ELSE '>100' END",
    "property_state_tier": "CASE WHEN property_state IN ('CA','FL','TX','NY','IL','NJ') THEN property_state ELSE 'OTHER' END",
}


def run_representativeness(
    marts: object,
    src_prefix: str,
    outputs_dir: Path,
    sample_filter: bool = False,
) -> int:
    """Compute PSI vs history, freeze Dec 2025 baseline shares, and size MoC Categories A and B."""
    check = c.Checker("16_representativeness: PSI baseline and Category A/B MoC sizing")
    snap_glob = str(outputs_dir / "book_snapshot" / "year=*" / "*.parquet").replace("\\", "/")
    if not list((outputs_dir / "book_snapshot").glob("year=*/*.parquet")):
        raise FileNotFoundError("book_snapshot Parquet files missing; run 07_default_rate_history.py first")

    max_yr = int(c.scalar(marts, f"SELECT max(year(snapshot_date)) FROM read_parquet('{snap_glob}')") or 2025)

    union_queries = []
    for drv, case_sql in DRIVER_BINS.items():
        union_queries.append(f"""
            SELECT
                '{drv}'::VARCHAR AS driver_name,
                w.baseline_window,
                ({case_sql})::VARCHAR AS band,
                count(*)::BIGINT AS loans,
                COALESCE(sum(s.current_upb), 0.0) AS balance_upb
            FROM read_parquet('{snap_glob}') s
            CROSS JOIN (
                VALUES ('today_dec_{max_yr}'::VARCHAR), ('history_pre_2025'::VARCHAR), ('history_pre_2022'::VARCHAR)
            ) AS w(baseline_window)
            WHERE (
                (w.baseline_window = 'today_dec_{max_yr}' AND year(s.snapshot_date) = {max_yr})
                OR (w.baseline_window = 'history_pre_2025' AND year(s.snapshot_date) < {max_yr})
                OR (w.baseline_window = 'history_pre_2022' AND year(s.snapshot_date) <= 2021)
            )
            GROUP BY 1, 2, 3
        """)

    dist_df = c.q(marts, " UNION ALL ".join(union_queries))
    tot_by_win = dist_df.groupby(["driver_name", "baseline_window"])[["loans", "balance_upb"]].transform("sum")
    dist_df["loan_share"] = dist_df["loans"] / tot_by_win["loans"].clip(lower=1)
    dist_df["balance_share"] = dist_df["balance_upb"] / tot_by_win["balance_upb"].clip(lower=1e-9)

    today_key = f"today_dec_{max_yr}"
    today_shares = dist_df[dist_df["baseline_window"] == today_key].set_index(["driver_name", "band"])["loan_share"].to_dict()

    psi_map: dict[tuple[str, str], float] = {}
    for (drv, win), g in dist_df.groupby(["driver_name", "baseline_window"]):
        if win == today_key:
            psi_map[(drv, win)] = 0.0
            continue
        psi_val = 0.0
        for r in g.itertuples():
            e = max(float(r.loan_share), 1e-6)
            a = max(float(today_shares.get((drv, r.band), 0.0)), 1e-6)
            psi_val += (a - e) * float(np.log(a / e))
        psi_map[(drv, win)] = psi_val

    dist_df["psi_vs_today"] = [psi_map[(r.driver_name, r.baseline_window)] for r in dist_df.itertuples()]
    c.write_df(marts, "representativeness_mart", dist_df, ["driver_name", "baseline_window", "band"])

    # Category A (data gaps) & Category B (lending & servicing shifts) for Margin of Conservatism
    where_l = c.scope(sample_filter, prefix=src_prefix)
    limit_rows: list[dict] = []

    snap_lim = marts.execute(f"""
        SELECT
            count(*)::BIGINT AS total_snap_rows,
            COALESCE(sum(current_upb), 0.0) AS total_snap_upb,
            count(*) FILTER (WHERE is_dpd_unknown)::BIGINT AS xx_rows,
            COALESCE(sum(current_upb) FILTER (WHERE is_dpd_unknown), 0.0) AS xx_upb,
            count(*) FILTER (WHERE balance_masked_flag)::BIGINT AS masked_rows,
            COALESCE(sum(current_upb) FILTER (WHERE balance_masked_flag), 0.0) AS masked_upb,
            count(*) FILTER (WHERE dti IS NULL)::BIGINT AS null_dti_rows,
            COALESCE(sum(current_upb) FILTER (WHERE dti IS NULL), 0.0) AS null_dti_upb,
            count(*) FILTER (WHERE credit_score IS NULL)::BIGINT AS null_fico_rows,
            COALESCE(sum(current_upb) FILTER (WHERE credit_score IS NULL), 0.0) AS null_fico_upb,
            count(*) FILTER (WHERE era = '2007-2010 crisis')::BIGINT AS crisis_rows,
            COALESCE(sum(current_upb) FILTER (WHERE era = '2007-2010 crisis'), 0.0) AS crisis_upb,
            count(*) FILTER (WHERE era = '2020-2021 COVID')::BIGINT AS covid_rows,
            COALESCE(sum(current_upb) FILTER (WHERE era = '2020-2021 COVID'), 0.0) AS covid_upb
        FROM read_parquet('{snap_glob}')
    """).fetchall()[0]
    tot_snap_r = max(int(snap_lim[0] or 1), 1)
    tot_snap_u = max(float(snap_lim[1] or 1.0), 1.0)
    for idx_cat, (name, r_cnt, u_sum) in enumerate([
        ("cat_A_unknown_arrears_XX_in_snapshots", snap_lim[2], snap_lim[3]),
        ("cat_A_masked_early_balances_in_snapshots", snap_lim[4], snap_lim[5]),
        ("cat_A_missing_dti_in_snapshots", snap_lim[6], snap_lim[7]),
        ("cat_A_missing_credit_score_in_snapshots", snap_lim[8], snap_lim[9]),
    ]):
        limit_rows.append({"category": "Category A: Data Deficiencies", "limit_name": name, "records_or_loans": int(r_cnt), "balance_upb": float(u_sum), "share_pct": 100.0 * int(r_cnt) / tot_snap_r, "balance_share_pct": 100.0 * float(u_sum) / tot_snap_u})

    # Estimated accrued interest, HPI fallbacks, and loan-level policy flags
    lov_lim = marts.execute("""
        SELECT
            count(*)::BIGINT,
            count(*) FILTER (WHERE hpi_pre2000_fallback)::BIGINT,
            COALESCE(sum(orig_upb) FILTER (WHERE hpi_pre2000_fallback), 0.0),
            count(*) FILTER (WHERE hpi_territory_fallback)::BIGINT,
            COALESCE(sum(orig_upb) FILTER (WHERE hpi_territory_fallback), 0.0),
            count(*) FILTER (WHERE invalid_orig_ltv_flag)::BIGINT
        FROM loan_origination_value_mart
    """).fetchall()[0]
    n_loans = max(int(lov_lim[0] or 1), 1)
    limit_rows.append({"category": "Category A: Data Deficiencies", "limit_name": "cat_A_pre2000_hpi_clamped_to_2000Q1", "records_or_loans": int(lov_lim[1]), "balance_upb": float(lov_lim[2]), "share_pct": 100.0 * int(lov_lim[1]) / n_loans, "balance_share_pct": 0.0})
    limit_rows.append({"category": "Category A: Data Deficiencies", "limit_name": "cat_A_territory_hpi_national_fallback", "records_or_loans": int(lov_lim[3]), "balance_upb": float(lov_lim[4]), "share_pct": 100.0 * int(lov_lim[3]) / n_loans, "balance_share_pct": 0.0})
    limit_rows.append({"category": "Category A: Data Deficiencies", "limit_name": "cat_A_invalid_or_null_orig_ltv", "records_or_loans": int(lov_lim[5]), "balance_upb": 0.0, "share_pct": 100.0 * int(lov_lim[5]) / n_loans, "balance_share_pct": 0.0})

    est_int = marts.execute("""
        SELECT count(*) FILTER (WHERE end_reason = 'credit exit')::BIGINT,
               COALESCE(sum(CAST(estimated_accrued_interest AS DOUBLE)) FILTER (WHERE end_reason = 'credit exit'), 0.0)
        FROM default_outcomes_mart
    """).fetchall()[0]
    limit_rows.append({"category": "Category A: Data Deficiencies", "limit_name": "cat_A_estimated_delinquent_accrued_interest", "records_or_loans": int(est_int[0] or 0), "balance_upb": float(est_int[1] or 0.0), "share_pct": 100.0 * int(est_int[0] or 0) / n_loans, "balance_share_pct": 0.0})

    # Restatement count from origination_restatements_table + multi-servicer transfers from data_plausibility_mart
    restated_tot = int(c.scalar(marts, f"SELECT COALESCE(sum(loans_restated), 0) FROM {src_prefix}origination_restatements_table") or 0)
    limit_rows.append({"category": "Category A: Data Deficiencies", "limit_name": "cat_A_origination_field_restatement_events", "records_or_loans": restated_tot, "balance_upb": 0.0, "share_pct": 0.0, "balance_share_pct": 0.0})
    late_fields = int(c.scalar(marts, f"SELECT count(*) FROM {src_prefix}feature_catalogue_table WHERE field_name IN ('payment_history','total_principal','borrower_assistance_plan','alt_delinquency_resolution')") or 0)
    limit_rows.append({"category": "Category A: Data Deficiencies", "limit_name": "cat_A_late_populated_monthly_fields_count", "records_or_loans": late_fields, "balance_upb": 0.0, "share_pct": 0.0, "balance_share_pct": 0.0})

    # Category B lending & servicing shifts
    cat_b_loans = marts.execute(f"""
        SELECT
            count(*) FILTER (WHERE high_balance_loan = 'Y')::BIGINT,
            COALESCE(sum(CAST(orig_upb AS DOUBLE)) FILTER (WHERE high_balance_loan = 'Y'), 0.0),
            count(*) FILTER (WHERE hltv_refi_option = 'Y')::BIGINT,
            COALESCE(sum(CAST(orig_upb AS DOUBLE)) FILTER (WHERE hltv_refi_option = 'Y'), 0.0)
        FROM {src_prefix}loans_table
        WHERE {where_l}
    """).fetchall()[0]
    multi_serv = int(c.scalar(marts, "SELECT COALESCE(value, 0) FROM data_plausibility_mart WHERE metric_name='multi_servicer_loans' AND year='ALL'") or 0)
    limit_rows.append({"category": "Category B: Lending & Servicing Shifts", "limit_name": "cat_B_high_balance_loans", "records_or_loans": int(cat_b_loans[0] or 0), "balance_upb": float(cat_b_loans[1] or 0.0), "share_pct": 100.0 * int(cat_b_loans[0] or 0) / n_loans, "balance_share_pct": 0.0})
    limit_rows.append({"category": "Category B: Lending & Servicing Shifts", "limit_name": "cat_B_high_ltv_refi_program", "records_or_loans": int(cat_b_loans[2] or 0), "balance_upb": float(cat_b_loans[3] or 0.0), "share_pct": 100.0 * int(cat_b_loans[2] or 0) / n_loans, "balance_share_pct": 0.0})
    limit_rows.append({"category": "Category B: Lending & Servicing Shifts", "limit_name": "cat_B_servicer_transfers_multi_servicer", "records_or_loans": multi_serv, "balance_upb": 0.0, "share_pct": 100.0 * multi_serv / n_loans, "balance_share_pct": 0.0})
    limit_rows.append({"category": "Category B: Lending & Servicing Shifts", "limit_name": "cat_B_2007_2010_crisis_snapshots", "records_or_loans": int(snap_lim[10]), "balance_upb": float(snap_lim[11]), "share_pct": 100.0 * int(snap_lim[10]) / tot_snap_r, "balance_share_pct": 100.0 * float(snap_lim[11]) / tot_snap_u})
    limit_rows.append({"category": "Category B: Lending & Servicing Shifts", "limit_name": "cat_B_2020_2021_covid_snapshots", "records_or_loans": int(snap_lim[12]), "balance_upb": float(snap_lim[13]), "share_pct": 100.0 * int(snap_lim[12]) / tot_snap_r, "balance_share_pct": 100.0 * float(snap_lim[13]) / tot_snap_u})

    lim_df = pd.DataFrame(limit_rows)
    c.write_df(marts, "data_limits_mart", lim_df, ["category", "limit_name"])

    check.key(marts, "representativeness_mart", ["driver_name", "baseline_window", "band"])
    check.key(marts, "data_limits_mart", ["category", "limit_name"])
    check.add("Dec baseline shares sum to 1.0 per driver", bool((dist_df.groupby(["driver_name", "baseline_window"])["loan_share"].sum().sub(1.0).abs() < 1e-6).all()))
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Representativeness PSI, baseline shares and Category A/B MoC.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    rc = run_representativeness(marts, sp, args.outputs_dir, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
