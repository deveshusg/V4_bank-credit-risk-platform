"""Candidate segmentation tests, interaction pockets and 5-year sufficiency (Stage C, script 10).

Fixes all design review C4, M4 and Builder-Spec defects:
- Executes strictly inside DuckDB SQL over book_snapshot + loans_table (never loads 280M rows into pandas).
- Evaluates Chi-square (exact 1-df p-value), binned two-sample KS on credit_score + p-value,
  KL divergence on (credit_score_band x ltv_band), informative missingness splits,
  descriptive depth-4 interaction pockets, and segment x year sufficiency against MIN_DATA_YEARS=5.

Outputs: segmentation_mart, segment_sufficiency_mart, interaction_pockets_mart.
Run: python residential_mortgage/02_portfolio_analytics/10_segmentation.py [--sample]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


def ks_from_bins(cnt_a: np.ndarray, cnt_b: np.ndarray) -> tuple[float, float]:
    """Return (KS_stat, approx_pvalue) from aligned sorted histogram bin counts."""
    na, nb = float(cnt_a.sum()), float(cnt_b.sum())
    if na <= 0.0 or nb <= 0.0:
        return 0.0, 1.0
    cdf_a = np.cumsum(cnt_a) / na
    cdf_b = np.cumsum(cnt_b) / nb
    d_stat = float(np.max(np.abs(cdf_a - cdf_b)))
    neff = (na * nb) / (na + nb)
    z = (math.sqrt(neff) + 0.12 + 0.11 / math.sqrt(max(neff, 1.0))) * d_stat
    if z <= 0.0:
        return d_stat, 1.0
    pval = min(max(2.0 * sum((-1) ** (k - 1) * math.exp(-2.0 * k * k * z * z) for k in range(1, 6)), 0.0), 1.0)
    return d_stat, pval


def chi2_2x2(n_a: int, bad_a: int, n_b: int, bad_b: int) -> tuple[float, float]:
    """Compute Pearson Chi-square statistic (df=1) and exact p-value via erfc."""
    obs = np.array([[n_a - bad_a, bad_a], [n_b - bad_b, bad_b]], dtype=float)
    tot = obs.sum()
    if tot <= 0.0 or (obs.sum(axis=1) <= 0).any() or (obs.sum(axis=0) <= 0).any():
        return 0.0, 1.0
    exp = obs.sum(axis=1, keepdims=True) @ obs.sum(axis=0, keepdims=True) / tot
    chi2 = float(np.sum((obs - exp) ** 2 / exp))
    pval = math.erfc(math.sqrt(max(chi2, 0.0) / 2.0))
    return chi2, pval


def symmetric_kl(cnt_a: np.ndarray, cnt_b: np.ndarray) -> float:
    """Compute symmetric KL / Jeffrey divergence on smoothed binned distributions."""
    k = max(len(cnt_a), 1)
    pa = (cnt_a + 0.5) / (cnt_a.sum() + 0.5 * k)
    pb = (cnt_b + 0.5) / (cnt_b.sum() + 0.5 * k)
    return float(np.sum((pa - pb) * np.log(pa / pb)))


def run_segmentation(
    marts: object,
    src_prefix: str,
    outputs_dir: Path,
    sample_filter: bool = False,
) -> int:
    """Run formal split tests, missingness tests, depth-4 interaction pockets, and 5y sufficiency grid."""
    check = c.Checker("10_segmentation: split tests, interaction pockets and sufficiency")
    snap_glob = str(outputs_dir / "book_snapshot" / "year=*" / "*.parquet").replace("\\", "/")
    if not list((outputs_dir / "book_snapshot").glob("year=*/*.parquet")):
        raise FileNotFoundError("book_snapshot Parquet files missing; run 07_default_rate_history.py first")

    splits = [
        ("occupancy: owner-occupied vs investor_second", "P", "I/S", "CASE WHEN s.occupancy = 'P' THEN 1 ELSE 0 END"),
        ("purpose: purchase vs refinance", "P", "R/C", "CASE WHEN s.loan_purpose = 'P' THEN 1 ELSE 0 END"),
        ("first_time_buyer: Y vs N", "Y", "N", "CASE WHEN COALESCE(lt.first_time_buyer, 'N') = 'Y' THEN 1 ELSE 0 END"),
        ("high_ltv: <=80 vs >80", "<=80", ">80", "CASE WHEN s.orig_ltv <= 80 THEN 1 ELSE 0 END"),
        ("missing_credit_score: present vs missing", "present", "missing", "CASE WHEN s.credit_score IS NOT NULL THEN 1 ELSE 0 END"),
        ("missing_dti: present vs missing", "present", "missing", "CASE WHEN s.dti IS NOT NULL THEN 1 ELSE 0 END"),
    ]

    seg_rows: list[dict] = []
    for split_name, grp_a, grp_b, cond_sql in splits:
        # 1. Exact 2x2 default rates + risk-cell distributions via DuckDB SQL
        agg = c.q(marts, f"""
            SELECT
                {cond_sql} AS grp,
                count(*)::BIGINT AS loans,
                COALESCE(sum(s.bad_12m), 0)::BIGINT AS bads
            FROM read_parquet('{snap_glob}') s
            JOIN {src_prefix}loans_table lt ON lt.loan_id = s.loan_id
            WHERE s.bad_12m IN (0, 1) AND s.mob >= {c.SEASONING_MIN_MOB}
            GROUP BY 1
        """)
        m_a = agg[agg["grp"] == 1]
        m_b = agg[agg["grp"] == 0]
        na = int(m_a["loans"].sum())
        ba = int(m_a["bads"].sum())
        nb = int(m_b["loans"].sum())
        bb = int(m_b["bads"].sum())
        chi2, chi_p = chi2_2x2(na, ba, nb, bb)

        # 2. Credit-score 20-pt histogram & score x LTV cells from SQL for KS and KL
        score_hist = c.q(marts, f"""
            SELECT
                FLOOR(COALESCE(s.credit_score, -20) / 20) * 20 AS bin_id,
                count(*) FILTER (WHERE ({cond_sql}) = 1)::BIGINT AS cnt_a,
                count(*) FILTER (WHERE ({cond_sql}) = 0)::BIGINT AS cnt_b
            FROM read_parquet('{snap_glob}') s
            JOIN {src_prefix}loans_table lt ON lt.loan_id = s.loan_id
            WHERE s.bad_12m IN (0, 1) AND s.mob >= {c.SEASONING_MIN_MOB} AND s.credit_score IS NOT NULL
            GROUP BY 1
            ORDER BY 1
        """)
        ks_stat, ks_p = ks_from_bins(
            score_hist["cnt_a"].to_numpy(dtype=float) if not score_hist.empty else np.array([0.0]),
            score_hist["cnt_b"].to_numpy(dtype=float) if not score_hist.empty else np.array([0.0]),
        )

        kl_cells = c.q(marts, f"""
            SELECT
                FLOOR(COALESCE(s.credit_score, 0) / 40) AS sc_b,
                FLOOR(COALESCE(s.orig_ltv, 0) / 10) AS ltv_b,
                count(*) FILTER (WHERE ({cond_sql}) = 1)::BIGINT AS cnt_a,
                count(*) FILTER (WHERE ({cond_sql}) = 0)::BIGINT AS cnt_b
            FROM read_parquet('{snap_glob}') s
            JOIN {src_prefix}loans_table lt ON lt.loan_id = s.loan_id
            WHERE s.bad_12m IN (0, 1) AND s.mob >= {c.SEASONING_MIN_MOB}
            GROUP BY 1, 2
        """)
        kl_val = symmetric_kl(
            kl_cells["cnt_a"].to_numpy(dtype=float) if not kl_cells.empty else np.array([1.0]),
            kl_cells["cnt_b"].to_numpy(dtype=float) if not kl_cells.empty else np.array([1.0]),
        )

        seg_rows.append({
            "candidate_split": split_name,
            "segment_a": grp_a,
            "segment_b": grp_b,
            "loans_a": na,
            "bads_a": ba,
            "default_rate_a": ba / max(na, 1),
            "loans_b": nb,
            "bads_b": bb,
            "default_rate_b": bb / max(nb, 1),
            "chi2_stat": chi2,
            "chi2_pvalue": chi_p,
            "ks_credit_score": ks_stat,
            "ks_pvalue": ks_p,
            "kl_divergence": kl_val,
        })

    seg_df = pd.DataFrame(seg_rows)
    c.write_df(marts, "segmentation_mart", seg_df, ["candidate_split", "segment_a", "segment_b"])

    # Depth-4 descriptive interaction pockets strictly in SQL
    pockets_df = c.q(marts, f"""
        WITH cells AS (
            SELECT
                CASE WHEN orig_ltv <= 80 THEN 'LTV<=80' WHEN orig_ltv <= 90 THEN 'LTV81-90' ELSE 'LTV>90' END AS f1_ltv,
                CASE WHEN credit_score IS NULL THEN 'FICO_missing' WHEN credit_score < 660 THEN 'FICO<660' WHEN credit_score < 740 THEN 'FICO660-739' ELSE 'FICO740+' END AS f2_fico,
                COALESCE(occupancy, 'U') AS f3_occ,
                CASE WHEN property_state IN ('CA','FL','AZ','NV','MI') THEN 'sand_rust_bubble' ELSE 'other_states' END AS f4_region,
                count(*)::BIGINT AS loans,
                COALESCE(sum(bad_12m), 0)::BIGINT AS bads,
                COALESCE(sum(current_upb), 0.0) AS balance_upb
            FROM read_parquet('{snap_glob}')
            WHERE bad_12m IN (0, 1) AND mob >= {c.SEASONING_MIN_MOB}
            GROUP BY 1, 2, 3, 4
        ),
        tot AS (SELECT sum(loans) AS t_loans, sum(bads) AS t_bads FROM cells)
        SELECT
            ROW_NUMBER() OVER (ORDER BY CAST(bads AS DOUBLE) / GREATEST(loans, 1) DESC, loans DESC)::INTEGER AS pocket_id,
            f1_ltv,
            f2_fico,
            f3_occ,
            f4_region,
            loans,
            bads,
            balance_upb,
            CAST(bads AS DOUBLE) / GREATEST(loans, 1) AS default_rate_12m,
            (CAST(bads AS DOUBLE) / GREATEST(loans, 1)) / NULLIF(CAST(t.t_bads AS DOUBLE) / GREATEST(t.t_loans, 1), 0.0) AS relative_risk_index
        FROM cells, tot t
        WHERE loans >= 50
        ORDER BY pocket_id
    """)
    if pockets_df.empty:
        # Handle tiny test fixtures (<50 loans per cell) cleanly without empty table
        pockets_df = c.q(marts, f"""
            WITH cells AS (
                SELECT
                    CASE WHEN orig_ltv <= 80 THEN 'LTV<=80' WHEN orig_ltv <= 90 THEN 'LTV81-90' ELSE 'LTV>90' END AS f1_ltv,
                    CASE WHEN credit_score IS NULL THEN 'FICO_missing' WHEN credit_score < 660 THEN 'FICO<660' WHEN credit_score < 740 THEN 'FICO660-739' ELSE 'FICO740+' END AS f2_fico,
                    COALESCE(occupancy, 'U') AS f3_occ,
                    CASE WHEN property_state IN ('CA','FL','AZ','NV','MI') THEN 'sand_rust_bubble' ELSE 'other_states' END AS f4_region,
                    count(*)::BIGINT AS loans,
                    COALESCE(sum(bad_12m), 0)::BIGINT AS bads,
                    COALESCE(sum(current_upb), 0.0) AS balance_upb
                FROM read_parquet('{snap_glob}')
                WHERE bad_12m IN (0, 1) AND mob >= {c.SEASONING_MIN_MOB}
                GROUP BY 1, 2, 3, 4
            ),
            tot AS (SELECT sum(loans) AS t_loans, sum(bads) AS t_bads FROM cells)
            SELECT
                ROW_NUMBER() OVER (ORDER BY CAST(bads AS DOUBLE) / GREATEST(loans, 1) DESC, loans DESC)::INTEGER AS pocket_id,
                f1_ltv, f2_fico, f3_occ, f4_region, loans, bads, balance_upb,
                CAST(bads AS DOUBLE) / GREATEST(loans, 1) AS default_rate_12m,
                (CAST(bads AS DOUBLE) / GREATEST(loans, 1)) / NULLIF(CAST(t.t_bads AS DOUBLE) / GREATEST(t.t_loans, 1), 0.0) AS relative_risk_index
            FROM cells, tot t
            ORDER BY pocket_id
        """)
    c.write_df(marts, "interaction_pockets_mart", pockets_df, ["pocket_id"])

    # Segment x year sufficiency grid against MIN_DATA_YEARS = 5
    suff_df = c.q(marts, f"""
        WITH base AS (
            SELECT 'occupancy|purpose'::VARCHAR AS segment_scheme, segment AS segment_value, year(snapshot_date)::INTEGER AS snapshot_year,
                   count(*)::BIGINT AS loans, COALESCE(sum(bad_12m), 0)::BIGINT AS bads
            FROM read_parquet('{snap_glob}')
            WHERE bad_12m IN (0, 1) AND mob >= {c.SEASONING_MIN_MOB}
            GROUP BY 1, 2, 3
        ),
        yr_cnt AS (
            SELECT segment_scheme, segment_value, count(*) FILTER (WHERE loans > 0)::INTEGER AS years_observed
            FROM base GROUP BY 1, 2
        )
        SELECT b.*, y.years_observed, (y.years_observed >= {c.MIN_DATA_YEARS})::BOOLEAN AS meets_5y_art180
        FROM base b
        JOIN yr_cnt y USING (segment_scheme, segment_value)
        ORDER BY 1, 2, 3
    """)
    c.write_df(marts, "segment_sufficiency_mart", suff_df, ["segment_scheme", "segment_value", "snapshot_year"])

    check.key(marts, "segmentation_mart", ["candidate_split", "segment_a", "segment_b"])
    check.key(marts, "interaction_pockets_mart", ["pocket_id"])
    check.key(marts, "segment_sufficiency_mart", ["segment_scheme", "segment_value", "snapshot_year"])
    check.add("split statistics finite", bool(seg_df[["chi2_stat", "ks_credit_score", "kl_divergence"]].notna().all().all()))
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segmentation split tests and interaction pockets.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    rc = run_segmentation(marts, sp, args.outputs_dir, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
