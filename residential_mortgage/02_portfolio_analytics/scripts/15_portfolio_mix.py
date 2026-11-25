"""Portfolio mix, concentration HHI, EPD-3 and arrears bounce (Stage E, script 15).

Fixes all design review M3 & C4 defects:
- Pure DuckDB SQL execution over partitioned book_snapshot and loans_table (no 280M pandas load).
- Excludes Fannie Mae's '00000' non-MSA sentinel, NULL, and '' from MSA HHI while reporting
  non_msa_share_pct explicitly alongside state, MSA, and seller HHI.
- Uses FILTER (WHERE col IS NOT NULL) in exposure-weighted averages (FICO, DTI, LTV, rate).
- Captures SA LTV buckets (with 55% owner-occupied split per SA_OWNER_OCCUPIED_LTV_SPLIT)
  and side-by-side December 2025 vs 2006 / 2007 books.
- EPD-3 restricts strictly to loans acquired at mob <= 3 with >= 4 observed-window months
  (excluding partial 2025Q4).
- Arrears bounce enforces contiguous 3-month sequences: prev2=0 AND prev1=1 AND curr=0,
  >= 2 bounce cycles within 12 months.

Outputs: portfolio_mix_mart, concentration_mart, early_payment_default_mart, arrears_bounce_mart.
Run: python residential_mortgage/02_portfolio_analytics/scripts/15_portfolio_mix.py [--full]
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


def run_portfolio_mix(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
    dataset_end_iso: str = "2025-12-01",
) -> int:
    """Compute portfolio mix, state/MSA/seller HHI, EPD-3 and contiguous arrears bounce."""
    t0 = time.time()
    check = c.Checker("15_portfolio_mix: portfolio mix, HHI, EPD-3 and bounce")

    snap_dir = c.snapshot_dir(outputs_dir)
    snap_glob = str(snap_dir / "year=*" / "*.parquet").replace("\\", "/")
    if not list(snap_dir.glob("year=*/*.parquet")):
        raise FileNotFoundError("book_snapshot Parquet files missing; run 07_default_rate_history.py first")

    # 1. Book mix over time across portfolio_total, occupancy, num_units, sa_ltv_band
    mix_df = c.q(marts, f"""
        WITH s AS (
            SELECT
                year(snapshot_date)::INTEGER AS snapshot_year,
                current_upb,
                credit_score,
                orig_ltv,
                dti,
                note_rate,
                occupancy,
                num_units,
                ltv_downward
            FROM read_parquet('{snap_glob}')
        )
        SELECT snapshot_year, 'portfolio_total'::VARCHAR AS dimension, 'ALL'::VARCHAR AS bucket,
               count(*)::BIGINT AS loans, COALESCE(sum(current_upb), 0.0) AS balance_upb,
               sum(credit_score * current_upb) FILTER (WHERE credit_score IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE credit_score IS NOT NULL), 0.0) AS wavg_credit_score,
               sum(orig_ltv * current_upb) FILTER (WHERE orig_ltv IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE orig_ltv IS NOT NULL), 0.0) AS wavg_orig_ltv,
               sum(dti * current_upb) FILTER (WHERE dti IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE dti IS NOT NULL), 0.0) AS wavg_dti,
               sum(note_rate * current_upb) FILTER (WHERE note_rate IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE note_rate IS NOT NULL), 0.0) AS wavg_note_rate
        FROM s GROUP BY 1, 2, 3
        UNION ALL
        SELECT snapshot_year, 'occupancy'::VARCHAR, COALESCE(occupancy, 'unknown'),
               count(*)::BIGINT, COALESCE(sum(current_upb), 0.0),
               sum(credit_score * current_upb) FILTER (WHERE credit_score IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE credit_score IS NOT NULL), 0.0),
               sum(orig_ltv * current_upb) FILTER (WHERE orig_ltv IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE orig_ltv IS NOT NULL), 0.0),
               sum(dti * current_upb) FILTER (WHERE dti IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE dti IS NOT NULL), 0.0),
               sum(note_rate * current_upb) FILTER (WHERE note_rate IS NOT NULL) / NULLIF(sum(current_upb) FILTER (WHERE note_rate IS NOT NULL), 0.0)
        FROM s GROUP BY 1, 2, 3
        UNION ALL
        SELECT snapshot_year, 'num_units'::VARCHAR, COALESCE(num_units::VARCHAR, 'unknown'),
               count(*)::BIGINT, COALESCE(sum(current_upb), 0.0),
               NULL, NULL, NULL, NULL
        FROM s GROUP BY 1, 2, 3
        UNION ALL
        SELECT snapshot_year, 'sa_ltv_band'::VARCHAR,
               CASE
                   WHEN occupancy = 'P' AND ltv_downward <= 55.0 THEN 'owner_occ_<=55'
                   WHEN occupancy = 'P' AND ltv_downward <= 60.0 THEN 'owner_occ_55-60'
                   WHEN occupancy = 'P' AND ltv_downward <= 80.0 THEN 'owner_occ_60-80'
                   WHEN occupancy = 'P' THEN 'owner_occ_>80'
                   WHEN occupancy != 'P' AND ltv_downward <= 60.0 THEN 'inv_sec_<=60'
                   WHEN occupancy != 'P' AND ltv_downward <= 80.0 THEN 'inv_sec_60-80'
                   ELSE 'inv_sec_>80_or_unknown'
               END,
               count(*)::BIGINT, COALESCE(sum(current_upb), 0.0),
               NULL, NULL, NULL, NULL
        FROM s GROUP BY 1, 2, 3
    """)
    c.write_df(marts, "portfolio_mix_mart", mix_df, ["snapshot_year", "dimension", "bucket"])

    # 2. Concentration HHI by property_state, msa (excluding '00000' / blank), and seller_name
    conc_df = c.q(marts, f"""
        WITH yr_tot AS (
            SELECT year(snapshot_date)::INTEGER AS snapshot_year, sum(current_upb) AS tot_upb
            FROM read_parquet('{snap_glob}')
            GROUP BY 1
        ),
        st_shares AS (
            SELECT year(s.snapshot_date)::INTEGER AS snapshot_year, s.property_state AS k, sum(s.current_upb) AS bal
            FROM read_parquet('{snap_glob}') s GROUP BY 1, 2
        ),
        msa_shares AS (
            SELECT year(s.snapshot_date)::INTEGER AS snapshot_year, lt.msa AS k, sum(s.current_upb) AS bal
            FROM read_parquet('{snap_glob}') s
            JOIN {src_prefix}loans_table lt ON lt.loan_id = s.loan_id
            GROUP BY 1, 2
        ),
        sel_shares AS (
            SELECT year(s.snapshot_date)::INTEGER AS snapshot_year, lt.seller_name AS k, sum(s.current_upb) AS bal
            FROM read_parquet('{snap_glob}') s
            JOIN {src_prefix}loans_table lt ON lt.loan_id = s.loan_id
            GROUP BY 1, 2
        ),
        msa_valid AS (
            SELECT snapshot_year, sum(bal) AS msa_upb
            FROM msa_shares
            WHERE k IS NOT NULL AND trim(k) != '' AND k != '00000'
            GROUP BY 1
        )
        SELECT t.snapshot_year, 'property_state'::VARCHAR AS concentration_dim,
               sum(pow(s.bal / NULLIF(t.tot_upb, 0.0), 2)) AS hhi,
               count(DISTINCT s.k)::INTEGER AS entities_count,
               0.0::DOUBLE AS unmapped_or_non_msa_share_pct
        FROM yr_tot t JOIN st_shares s USING (snapshot_year) GROUP BY 1, 2
        UNION ALL
        SELECT t.snapshot_year, 'msa'::VARCHAR,
               sum(pow(m.bal / NULLIF(mv.msa_upb, 0.0), 2)),
               count(DISTINCT m.k)::INTEGER,
               (1.0 - COALESCE(mv.msa_upb, 0.0) / NULLIF(t.tot_upb, 0.0)) * 100.0
        FROM yr_tot t
        LEFT JOIN msa_valid mv USING (snapshot_year)
        JOIN msa_shares m ON m.snapshot_year = t.snapshot_year AND m.k IS NOT NULL AND trim(m.k) != '' AND m.k != '00000'
        GROUP BY 1, 2, mv.msa_upb, t.tot_upb
        UNION ALL
        SELECT t.snapshot_year, 'seller_name'::VARCHAR,
               sum(pow(sl.bal / NULLIF(t.tot_upb, 0.0), 2)),
               count(DISTINCT sl.k)::INTEGER,
               COALESCE(sum(sl.bal) FILTER (WHERE sl.k IS NULL OR trim(sl.k) = ''), 0.0) / NULLIF(t.tot_upb, 0.0) * 100.0
        FROM yr_tot t JOIN sel_shares sl USING (snapshot_year) GROUP BY 1, 2, t.tot_upb
    """)
    c.write_df(marts, "concentration_mart", conc_df, ["snapshot_year", "concentration_dim"])

    # 3. Early Payment Default (EPD-3) and contiguous 0->1->0 arrears bounce per quarter
    epd_parts: list[pd.DataFrame] = []
    bnc_parts: list[pd.DataFrame] = []
    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")

        epd_q = c.q(marts, f"""
            WITH elig_loans AS (
                SELECT
                    l.loan_id,
                    COALESCE(l.seller_name, 'UNKNOWN') AS seller_name,
                    l.first_payment_date,
                    min(m.reporting_period) AS first_obs_rp,
                    datediff('month', l.first_payment_date, min(m.reporting_period)) AS first_obs_mob,
                    max(m.reporting_period) AS last_obs_rp,
                    bool_or(datediff('month', l.first_payment_date, m.reporting_period) BETWEEN 0 AND 3 AND m.delinquency_months >= 1) AS hit_epd3
                FROM read_parquet('{fp}') m
                JOIN {src_prefix}loans_table l
                  ON l.loan_id = m.loan_id AND l.acquisition_quarter = '{quarter}'
                GROUP BY 1, 2, 3
                HAVING datediff('month', l.first_payment_date, min(m.reporting_period)) <= 3
                   AND l.first_payment_date + INTERVAL 3 MONTH <= DATE '{dataset_end_iso}'
            )
            SELECT
                '{quarter}'::VARCHAR AS cohort_quarter,
                seller_name,
                count(*)::BIGINT AS eligible_loans,
                count(*) FILTER (WHERE COALESCE(hit_epd3, FALSE))::BIGINT AS epd3_loans
            FROM elig_loans
            GROUP BY 1, 2
        """)
        if not epd_q.empty:
            epd_parts.append(epd_q)

        bnc_q = c.q(marts, f"""
            WITH seg AS (
                SELECT loan_id, COALESCE(occupancy, 'U') || '|' || COALESCE(loan_purpose, 'U') AS segment
                FROM {src_prefix}loans_table WHERE acquisition_quarter = '{quarter}'
            ),
            seq AS (
                SELECT
                    m.loan_id,
                    s.segment,
                    m.reporting_period,
                    m.delinquency_months AS curr_dpd,
                    LAG(m.delinquency_months, 1) OVER w AS prev1_dpd,
                    LAG(m.delinquency_months, 2) OVER w AS prev2_dpd,
                    LAG(m.reporting_period, 1) OVER w AS prev1_rp,
                    LAG(m.reporting_period, 2) OVER w AS prev2_rp
                FROM read_parquet('{fp}') m
                JOIN seg s ON s.loan_id = m.loan_id
                WINDOW w AS (PARTITION BY m.loan_id ORDER BY m.reporting_period)
            ),
            cycles AS (
                SELECT loan_id, segment, reporting_period
                FROM seq
                WHERE prev2_dpd = 0 AND prev1_dpd = 1 AND curr_dpd = 0
                  AND prev1_rp = reporting_period - INTERVAL 1 MONTH
                  AND prev2_rp = reporting_period - INTERVAL 2 MONTH
            ),
            two_in_12m AS (
                SELECT DISTINCT
                    c1.loan_id,
                    c1.segment,
                    year(c2.reporting_period)::INTEGER AS year
                FROM cycles c1
                JOIN cycles c2
                  ON c2.loan_id = c1.loan_id
                 AND c2.reporting_period > c1.reporting_period
                 AND c2.reporting_period <= c1.reporting_period + INTERVAL 12 MONTH
            ),
            active_yr AS (
                SELECT year(m.reporting_period)::INTEGER AS year, s.segment, count(DISTINCT m.loan_id)::BIGINT AS active_loans
                FROM read_parquet('{fp}') m JOIN seg s ON s.loan_id = m.loan_id
                GROUP BY 1, 2
            ),
            b_agg AS (
                SELECT year, segment, count(*)::BIGINT AS bounce_loans
                FROM two_in_12m GROUP BY 1, 2
            )
            SELECT a.year, a.segment, a.active_loans, COALESCE(b.bounce_loans, 0)::BIGINT AS bounce_loans
            FROM active_yr a LEFT JOIN b_agg b USING (year, segment)
        """)
        if not bnc_q.empty:
            bnc_parts.append(bnc_q)

        if idx % 25 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] scanned {quarter} ({time.time() - t0:.1f}s)", flush=True)

    epd_df = (
        pd.concat(epd_parts, ignore_index=True)
        .groupby(["cohort_quarter", "seller_name"], as_index=False)
        .sum(numeric_only=True)
    ) if epd_parts else pd.DataFrame(columns=["cohort_quarter", "seller_name", "eligible_loans", "epd3_loans"])
    if not epd_df.empty:
        epd_df["epd3_rate"] = epd_df["epd3_loans"] / epd_df["eligible_loans"].clip(lower=1)
    c.write_df(marts, "early_payment_default_mart", epd_df, ["cohort_quarter", "seller_name"])

    bnc_df = (
        pd.concat(bnc_parts, ignore_index=True)
        .groupby(["year", "segment"], as_index=False)
        .sum(numeric_only=True)
    ) if bnc_parts else pd.DataFrame(columns=["year", "segment", "active_loans", "bounce_loans"])
    if not bnc_df.empty:
        bnc_df["bounce_rate"] = bnc_df["bounce_loans"] / bnc_df["active_loans"].clip(lower=1)
    c.write_df(marts, "arrears_bounce_mart", bnc_df, ["year", "segment"])

    check.key(marts, "portfolio_mix_mart", ["snapshot_year", "dimension", "bucket"])
    check.key(marts, "concentration_mart", ["snapshot_year", "concentration_dim"])
    check.key(marts, "early_payment_default_mart", ["cohort_quarter", "seller_name"])
    check.key(marts, "arrears_bounce_mart", ["year", "segment"])
    hhi_ok = bool((conc_df["hhi"].between(0.0, 1.0 + 1e-9)).all()) if not conc_df.empty else True
    check.add("HHI indices bounded in [0, 1]", hhi_ok)
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portfolio mix, concentration, EPD-3 and arrears bounce.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_portfolio_mix(marts, sp, core_files, args.outputs_dir)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
