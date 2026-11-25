"""Origination and behavioral risk drivers and IV/PSI (Stage C, script 09).

Fixes all design review C4 & M4 defects:
- Zero full-table pandas loading; executes aggregations inside DuckDB SQL.
- Builds `book_snapshot_behavioural` partitioned Parquet (t-1 lagged behavioral
  predictors for every December snapshot) so Module 3 never re-scans monthly core.
- Uses normalized +0.5 frequency smoothing b_b = (B_b + 0.5)/(B_total + 0.5*K)
  so WOE/IV distributions sum cleanly to 1.0 even with zero-event cells.
- Computes IV, era-over-era PSI stability, and Spearman rank correlations.

Outputs: book_snapshot_behavioural Parquet, risk_drivers_mart, feature_iv_mart, driver_correlation_mart.
Run: python residential_mortgage/02_portfolio_analytics/09_risk_drivers.py [--sample]
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
ltv_mod = __import__("06_current_ltv")


ORIG_FEATURES = {
    "credit_score": "CASE WHEN credit_score IS NULL THEN 'missing' WHEN credit_score < 620 THEN '<620' WHEN credit_score < 660 THEN '620-659' WHEN credit_score < 700 THEN '660-699' WHEN credit_score < 740 THEN '700-739' WHEN credit_score < 780 THEN '740-779' ELSE '780+' END",
    "orig_ltv": "CASE WHEN orig_ltv IS NULL THEN 'missing' WHEN orig_ltv <= 60 THEN '<=60' WHEN orig_ltv <= 70 THEN '61-70' WHEN orig_ltv <= 80 THEN '71-80' WHEN orig_ltv <= 90 THEN '81-90' WHEN orig_ltv <= 95 THEN '91-95' ELSE '>95' END",
    "dti": "CASE WHEN dti IS NULL THEN 'missing' WHEN dti <= 20 THEN '<=20' WHEN dti <= 30 THEN '21-30' WHEN dti <= 40 THEN '31-40' WHEN dti <= 50 THEN '41-50' ELSE '>50' END",
    "occupancy": "COALESCE(occupancy, 'missing')",
    "loan_purpose": "COALESCE(loan_purpose, 'missing')",
    "first_time_buyer": "COALESCE(first_time_buyer, 'missing')",
    "channel": "COALESCE(channel, 'missing')",
    "property_state": "COALESCE(property_state, 'missing')",
}

BEH_FEATURES = {
    "worst_dpd_6m_t1": "CASE WHEN worst_dpd_6m_t1 IS NULL THEN 'missing' WHEN worst_dpd_6m_t1 = 0 THEN '0' WHEN worst_dpd_6m_t1 = 1 THEN '1' WHEN worst_dpd_6m_t1 = 2 THEN '2' ELSE '3+' END",
    "worst_dpd_12m_t1": "CASE WHEN worst_dpd_12m_t1 IS NULL THEN 'missing' WHEN worst_dpd_12m_t1 = 0 THEN '0' WHEN worst_dpd_12m_t1 = 1 THEN '1' WHEN worst_dpd_12m_t1 = 2 THEN '2' ELSE '3+' END",
    "months_since_last_arrears_t1": "CASE WHEN months_since_last_arrears_t1 IS NULL THEN 'never' WHEN months_since_last_arrears_t1 <= 3 THEN '1-3m' WHEN months_since_last_arrears_t1 <= 12 THEN '4-12m' ELSE '>12m' END",
    "ever_modified_t1": "CASE WHEN COALESCE(ever_modified_t1, FALSE) THEN 'Y' ELSE 'N' END",
    "ltv_indexed_t1": "CASE WHEN ltv_indexed_t1 IS NULL THEN 'missing' WHEN ltv_indexed_t1 <= 60 THEN '<=60' WHEN ltv_indexed_t1 <= 80 THEN '60-80' WHEN ltv_indexed_t1 <= 100 THEN '80-100' ELSE '>100' END",
    "balance_paid_down_pct_t1": "CASE WHEN balance_paid_down_pct_t1 IS NULL THEN 'missing' WHEN balance_paid_down_pct_t1 < 5 THEN '<5%' WHEN balance_paid_down_pct_t1 < 15 THEN '5-15%' WHEN balance_paid_down_pct_t1 < 30 THEN '15-30%' ELSE '30%+' END",
    "rate_incentive_t1": "CASE WHEN rate_incentive_t1 IS NULL THEN 'missing' WHEN rate_incentive_t1 < -0.5 THEN '<-50bps' WHEN rate_incentive_t1 < 0.5 THEN '-50_to_50bps' WHEN rate_incentive_t1 < 1.5 THEN '50_to_150bps' ELSE '150bps+' END",
}


def compute_woe_iv_table(counts_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute normalized +0.5 smoothed WOE, IV and era PSI across grouped counts."""
    rd_rows: list[dict] = []
    iv_rows: list[dict] = []
    if counts_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Baseline band shares over complete history per feature for PSI across eras
    all_dist = (
        counts_df.groupby(["feature_name", "band"], as_index=False)["loans"]
        .sum()
    )
    all_tot = all_dist.groupby("feature_name")["loans"].transform("sum")
    all_dist["base_share"] = all_dist["loans"] / all_tot.clip(lower=1)
    base_map = {(r.feature_name, r.band): float(r.base_share) for r in all_dist.itertuples()}

    for (era, feat), g in counts_df.groupby(["era", "feature_name"]):
        g = g.copy()
        k = max(len(g), 1)
        tot_bad = float(g["bads"].sum())
        tot_good = float((g["loans"] - g["bads"]).sum())
        tot_loans = float(g["loans"].sum())
        g["good"] = g["loans"] - g["bads"]
        g["default_rate"] = g["bads"] / g["loans"].clip(lower=1)
        g["dist_bad"] = (g["bads"] + 0.5) / (tot_bad + 0.5 * k)
        g["dist_good"] = (g["good"] + 0.5) / (tot_good + 0.5 * k)
        g["woe"] = np.log(g["dist_good"] / g["dist_bad"])
        g["iv_contrib"] = (g["dist_good"] - g["dist_bad"]) * g["woe"]
        era_share = g["loans"] / max(tot_loans, 1.0)
        base_s = g["band"].map(lambda b: max(base_map.get((feat, b), 1e-6), 1e-6))
        era_s = era_share.clip(lower=1e-6)
        psi_val = float(((era_s - base_s) * np.log(era_s / base_s)).sum())

        iv_sum = float(g["iv_contrib"].sum())
        iv_rows.append({"era": era, "feature_name": feat, "loans": int(tot_loans), "bads": int(tot_bad), "information_value": iv_sum, "psi_vs_all": psi_val})
        for r in g.itertuples():
            rd_rows.append({
                "era": era,
                "feature_name": feat,
                "band": str(r.band),
                "loans": int(r.loans),
                "bads": int(r.bads),
                "default_rate": float(r.default_rate),
                "dist_bad": float(r.dist_bad),
                "dist_good": float(r.dist_good),
                "woe": float(r.woe),
                "iv_contrib": float(r.iv_contrib),
            })
    return pd.DataFrame(rd_rows), pd.DataFrame(iv_rows)


def run_risk_drivers(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
    sample_filter: bool = False,
) -> int:
    """Build t-1 behavioural December snapshot and compute binned origination/behavioral IVs."""
    t0 = time.time()
    check = c.Checker("09_risk_drivers: behavioral features, IV and PSI")

    snap_dir = outputs_dir / "book_snapshot"
    if not list(snap_dir.glob("year=*/*.parquet")):
        raise FileNotFoundError(f"Missing book_snapshot Parquet partitions in {snap_dir}")

    marts.execute(ltv_mod.build_hpi_lookup_sql(src_prefix))
    where_l = c.scope(sample_filter, prefix=src_prefix)
    marts.execute("DROP TABLE IF EXISTS _mkt_rate_07")
    marts.execute(f"""
        CREATE TEMP TABLE _mkt_rate_07 AS
        SELECT date_trunc('month', orig_date)::DATE AS orig_month,
               sum(CAST(note_rate AS DOUBLE) * CAST(orig_upb AS DOUBLE)) / NULLIF(sum(CAST(orig_upb AS DOUBLE)), 0.0) AS market_rate
        FROM {src_prefix}loans_table
        WHERE {where_l} AND orig_date IS NOT NULL
        GROUP BY 1
    """)

    # Collect per-quarter t-1 behavioral rows for December snapshots in a partitioned stage table
    beh_stage_dir = outputs_dir / "_beh_stage"
    beh_stage_dir.mkdir(parents=True, exist_ok=True)
    for old_f in beh_stage_dir.glob("*.parquet"):
        old_f.unlink()

    sched_sql = c.scheduled_upb_sql(
        "lt.orig_upb",
        "lt.note_rate",
        "lt.loan_term",
        "datediff('month', lt.first_payment_date, m.reporting_period)",
    )

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        stage_p = str(beh_stage_dir / f"{quarter}.parquet").replace("\\", "/")
        marts.execute(f"""
            COPY (
                WITH max_hq AS (SELECT max(quarter_date) AS max_qd FROM _hpi_q),
                enriched AS (
                    SELECT
                        m.loan_id,
                        m.reporting_period,
                        month(m.reporting_period) AS mo,
                        year(m.reporting_period) AS yr,
                        datediff('month', lt.first_payment_date, m.reporting_period) AS mob,
                        CAST(m.current_rate AS DOUBLE) AS current_rate,
                        CASE
                            WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0
                                 AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                            ELSE CAST(m.current_upb AS DOUBLE)
                        END AS eff_upb,
                        CAST(lt.orig_upb AS DOUBLE) AS orig_upb,
                        m.delinquency_months,
                        m.modification_flag,
                        max(m.delinquency_months) OVER (
                            PARTITION BY m.loan_id ORDER BY m.reporting_period
                            RANGE BETWEEN INTERVAL 6 MONTH PRECEDING AND INTERVAL 1 MONTH PRECEDING
                        ) AS worst_dpd_6m_t1,
                        max(m.delinquency_months) OVER (
                            PARTITION BY m.loan_id ORDER BY m.reporting_period
                            RANGE BETWEEN INTERVAL 12 MONTH PRECEDING AND INTERVAL 1 MONTH PRECEDING
                        ) AS worst_dpd_12m_t1,
                        max(CASE WHEN m.delinquency_months >= 1 THEN m.reporting_period END) OVER (
                            PARTITION BY m.loan_id ORDER BY m.reporting_period
                            RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MONTH PRECEDING
                        ) AS last_arrears_rp,
                        bool_or(m.modification_flag = 'Y') OVER (
                            PARTITION BY m.loan_id ORDER BY m.reporting_period
                            RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MONTH PRECEDING
                        ) AS ever_modified_t1,
                        LAG(
                            CASE
                                WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0
                                     AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                                ELSE CAST(m.current_upb AS DOUBLE)
                            END
                        ) OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period) AS prev_eff_upb,
                        LAG(CAST(m.current_rate AS DOUBLE)) OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period) AS prev_rate,
                        LAG(m.reporting_period) OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period) AS prev_rp,
                        lov.value_at_origination,
                        lov.hpi_orig,
                        lov.property_state
                    FROM read_parquet('{fp}') m
                    JOIN {src_prefix}loans_table lt
                      ON lt.loan_id = m.loan_id AND lt.acquisition_quarter = '{quarter}'
                    LEFT JOIN loan_origination_value_mart lov ON lov.loan_id = m.loan_id
                )
                SELECT
                    e.reporting_period AS snapshot_date,
                    e.loan_id,
                    e.yr::INTEGER AS snap_year,
                    e.worst_dpd_6m_t1::INTEGER AS worst_dpd_6m_t1,
                    e.worst_dpd_12m_t1::INTEGER AS worst_dpd_12m_t1,
                    CASE WHEN e.last_arrears_rp IS NOT NULL THEN datediff('month', e.last_arrears_rp, e.reporting_period)::INTEGER ELSE NULL END AS months_since_last_arrears_t1,
                    COALESCE(e.ever_modified_t1, FALSE)::BOOLEAN AS ever_modified_t1,
                    CASE WHEN e.prev_rp = e.reporting_period - INTERVAL 1 MONTH THEN e.prev_eff_upb ELSE NULL END AS current_upb_t1,
                    CASE WHEN e.prev_rp = e.reporting_period - INTERVAL 1 MONTH AND e.orig_upb > 0
                         THEN (1.0 - e.prev_eff_upb / e.orig_upb) * 100.0 ELSE NULL END AS balance_paid_down_pct_t1,
                    CASE WHEN e.prev_rp = e.reporting_period - INTERVAL 1 MONTH AND e.value_at_origination > 0 AND e.hpi_orig > 0
                         THEN 100.0 * e.prev_eff_upb / NULLIF(e.value_at_origination * COALESCE(h_t1.hpi_sa, h_nat.hpi_sa) / e.hpi_orig, 0.0) ELSE NULL END AS ltv_indexed_t1,
                    CASE WHEN e.prev_rp = e.reporting_period - INTERVAL 1 MONTH AND mr.market_rate IS NOT NULL
                         THEN e.prev_rate - mr.market_rate ELSE NULL END AS rate_incentive_t1
                FROM enriched e
                LEFT JOIN _hpi_q h_t1
                  ON h_t1.state = e.property_state
                 AND h_t1.quarter_date = LEAST(date_trunc('quarter', e.reporting_period - INTERVAL 1 MONTH)::DATE, (SELECT max_qd FROM max_hq))
                LEFT JOIN (SELECT quarter_date, avg(hpi_sa) AS hpi_sa FROM _hpi_q WHERE is_territory GROUP BY 1) h_nat
                  ON h_nat.quarter_date = LEAST(date_trunc('quarter', e.reporting_period - INTERVAL 1 MONTH)::DATE, (SELECT max_qd FROM max_hq))
                LEFT JOIN _mkt_rate_07 mr
                  ON mr.orig_month = date_trunc('month', e.reporting_period - INTERVAL 1 MONTH)::DATE
                WHERE e.mo = 12
            ) TO '{stage_p}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] built t-1 features for {quarter} ({time.time() - t0:.1f}s)", flush=True)

    # Re-partition stage files by snap_year in ONE single streaming pass (avoiding 26x full re-scans)
    beh_dir = outputs_dir / "book_snapshot_behavioural"
    beh_dir.mkdir(parents=True, exist_ok=True)
    beh_by_yr = outputs_dir / "_beh_by_yr"
    import shutil
    if beh_by_yr.exists():
        shutil.rmtree(beh_by_yr)
    stage_glob = str(beh_stage_dir / "*.parquet").replace("\\", "/")
    beh_by_yr_lit = str(beh_by_yr).replace("\\", "/")
    marts.execute(f"""
        COPY (SELECT * FROM read_parquet('{stage_glob}'))
        TO '{beh_by_yr_lit}' (FORMAT PARQUET, PARTITION_BY (snap_year), COMPRESSION ZSTD)
    """)

    snap_years = [int(p.name.split("=")[1]) for p in sorted(snap_dir.glob("year=*"))]
    for yr in snap_years:
        ydir = beh_dir / f"year={yr}"
        ydir.mkdir(parents=True, exist_ok=True)
        out_p = ydir / "part.parquet"
        tmp_p = ydir / "part.parquet.tmp"
        if tmp_p.exists():
            tmp_p.unlink()
        snap_p = str(snap_dir / f"year={yr}" / "part.parquet").replace("\\", "/")
        yr_stage_dir = beh_by_yr / f"snap_year={yr}"
        tmp_lit = str(tmp_p).replace("\\", "/")
        if yr_stage_dir.exists() and list(yr_stage_dir.glob("*.parquet")):
            yr_glob = str(yr_stage_dir / "*.parquet").replace("\\", "/")
            marts.execute(f"""
                COPY (
                    SELECT s.snapshot_date, s.loan_id,
                           b.worst_dpd_6m_t1, b.worst_dpd_12m_t1, b.months_since_last_arrears_t1,
                           b.ever_modified_t1, b.current_upb_t1, b.balance_paid_down_pct_t1,
                           b.ltv_indexed_t1, b.rate_incentive_t1
                    FROM read_parquet('{snap_p}') s
                    LEFT JOIN read_parquet('{yr_glob}') b
                      ON b.loan_id = s.loan_id
                    ORDER BY s.loan_id
                ) TO '{tmp_lit}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
        else:
            marts.execute(f"""
                COPY (
                    SELECT snapshot_date, loan_id,
                           NULL::INTEGER AS worst_dpd_6m_t1, NULL::INTEGER AS worst_dpd_12m_t1,
                           NULL::INTEGER AS months_since_last_arrears_t1, FALSE AS ever_modified_t1,
                           NULL::DOUBLE AS current_upb_t1, NULL::DOUBLE AS balance_paid_down_pct_t1,
                           NULL::DOUBLE AS ltv_indexed_t1, NULL::DOUBLE AS rate_incentive_t1
                    FROM read_parquet('{snap_p}')
                    ORDER BY loan_id
                ) TO '{tmp_lit}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
        tmp_p.replace(out_p)

    shutil.rmtree(beh_stage_dir, ignore_errors=True)
    shutil.rmtree(beh_by_yr, ignore_errors=True)

    # Aggregate all origination and t-1 behavioral risk drivers in a single streaming pass via UNNEST
    snap_glob = str(snap_dir / "year=*" / "*.parquet").replace("\\", "/")
    beh_glob = str(beh_dir / "year=*" / "*.parquet").replace("\\", "/")
    all_specs = {**ORIG_FEATURES, **BEH_FEATURES}
    f_names_sql = "[" + ", ".join(f"'{fname}'::VARCHAR" for fname in all_specs) + "]"
    f_bands_sql = "[" + ", ".join(f"({case_expr})::VARCHAR" for case_expr in all_specs.values()) + "]"

    counts_sql = f"""
        WITH pd_base AS (
            SELECT s.era, s.bad_12m, s.credit_score, s.orig_ltv, s.dti,
                   s.occupancy, s.loan_purpose, s.first_time_buyer, s.channel, s.property_state,
                   b.worst_dpd_6m_t1, b.worst_dpd_12m_t1, b.months_since_last_arrears_t1,
                   b.ever_modified_t1, b.ltv_indexed_t1, b.balance_paid_down_pct_t1, b.rate_incentive_t1
            FROM read_parquet('{snap_glob}') s
            JOIN read_parquet('{beh_glob}') b
              ON b.snapshot_date = s.snapshot_date AND b.loan_id = s.loan_id
            WHERE s.bad_12m IN (0, 1) AND s.mob >= {c.SEASONING_MIN_MOB}
        ),
        unpivoted AS (
            SELECT
                era,
                bad_12m,
                UNNEST({f_names_sql}) AS feature_name,
                UNNEST({f_bands_sql}) AS band
            FROM pd_base
        )
        SELECT
            era,
            feature_name,
            band,
            count(*)::BIGINT AS loans,
            COALESCE(sum(bad_12m), 0)::BIGINT AS bads
        FROM unpivoted
        GROUP BY 1, 2, 3
    """
    counts_df = c.q(marts, counts_sql)
    rd_df, iv_df = compute_woe_iv_table(counts_df)
    c.write_df(marts, "risk_drivers_mart", rd_df, ["era", "feature_name", "band"])
    c.write_df(marts, "feature_iv_mart", iv_df, ["era", "feature_name"])

    # Deterministic reservoir sample (100k PD rows) for Spearman driver correlation matrix
    num_cols = [
        "credit_score", "orig_ltv", "dti", "note_rate",
        "worst_dpd_12m_t1", "ltv_indexed_t1", "balance_paid_down_pct_t1", "rate_incentive_t1",
    ]
    corr_sample = c.q(marts, f"""
        SELECT s.credit_score, s.orig_ltv, s.dti, s.note_rate,
               b.worst_dpd_12m_t1, b.ltv_indexed_t1, b.balance_paid_down_pct_t1, b.rate_incentive_t1
        FROM read_parquet('{snap_glob}') s
        JOIN read_parquet('{beh_glob}') b
          ON b.snapshot_date = s.snapshot_date AND b.loan_id = s.loan_id
        WHERE s.bad_12m IN (0, 1) AND s.mob >= {c.SEASONING_MIN_MOB}
        USING SAMPLE 100000 ROWS (reservoir, 42)
    """)
    sp_corr = corr_sample[num_cols].corr(method="spearman")
    corr_rows = []
    for a in num_cols:
        for b in num_cols:
            corr_rows.append({"feature_a": a, "feature_b": b, "spearman_rho": float(sp_corr.loc[a, b])})
    corr_df = pd.DataFrame(corr_rows)
    c.write_df(marts, "driver_correlation_mart", corr_df, ["feature_a", "feature_b"])

    marts.execute("DROP TABLE IF EXISTS _hpi_q")
    marts.execute("DROP TABLE IF EXISTS _mkt_rate_07")

    check.key(marts, "risk_drivers_mart", ["era", "feature_name", "band"])
    check.key(marts, "feature_iv_mart", ["era", "feature_name"])
    check.key(marts, "driver_correlation_mart", ["feature_a", "feature_b"])
    dist_ok = True
    if not rd_df.empty:
        sums = rd_df.groupby(["era", "feature_name"])[["dist_bad", "dist_good"]].sum()
        dist_ok = bool(((sums - 1.0).abs().max().max()) < 1e-6)
    check.add("smoothed dist_bad and dist_good sum cleanly to 1.0 per era x feature", dist_ok)
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Risk drivers, behavioral snapshots, IV and PSI.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_risk_drivers(marts, sp, core_files, args.outputs_dir, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
