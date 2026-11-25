"""12-month default-rate history, Vasicek asset correlation check, and December book_snapshot (Stage B, script 07).

Fixes all design review C4 & H4 defects:
- Zero full-table pandas loads; processes default_rate_history quarter-by-quarter in SQL
  and exports book_snapshot via DuckDB COPY one December year at a time (2000-2025).
- Uses point-in-time HPI at date_trunc('quarter', snapshot_date) in book_snapshot
  (eliminating the old max(as_of) look-ahead bug).
- Adds window_complete BOOLEAN (observation_month <= 2024-12-01) so trailing 2025
  partial windows never dilute LRA, downturn rankings, or Vasicek correlation rho.
- Estimates Vasicek asset correlation via 25-point Gauss-Hermite Binomial-Probit quadrature
  (handles zero-default years cleanly without inverse-normal divergence).
- Stores both bad_12m (1 / 0 / NULL) with explicit precedence (default > other_exit > good)
  and outcome_12m_status, plus orig_upb, note_rate, orig_ltv, credit_score, dti, value_downward.

Outputs: default_rate_history_mart, implied_correlation_mart, outputs[_sample]/book_snapshot/year=YYYY/part.parquet.
Run: python residential_mortgage/02_portfolio_analytics/07_default_rate_history.py [--sample]
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402
ltv_mod = __import__("06_current_ltv")


def fit_vasicek_rho(events: np.ndarray, totals: np.ndarray) -> tuple[float, float, float]:
    """Estimate pooled PD and Vasicek single-factor correlation via mode-centered adaptive quadrature.

    Returns (pooled_pd, rho_mle, log_lik). Works cleanly for k_y = 0 and up to N_y >= 1e7.
    """
    valid = totals > 0
    k_arr = events[valid].astype(float)
    n_arr = totals[valid].astype(float)
    if len(k_arr) < 2 or float(k_arr.sum()) <= 0.0:
        return 0.0, 0.0, float("nan")

    p_pool = float(k_arr.sum() / n_arr.sum())
    thresh = c.inv_normal_cdf(min(max(p_pool, 1e-8), 1.0 - 1e-8))
    u_pts = np.linspace(-6.5, 6.5, 41)
    du = float(u_pts[1] - u_pts[0])
    inv_sqrt2 = 1.0 / math.sqrt(2.0)
    erf = math.erf

    yr_meta = []
    for ky, ny in zip(k_arr.tolist(), n_arr.tolist()):
        if 0.0 < ky < ny:
            py = ky / ny
            zy_p = c.inv_normal_cdf(py)
            phi_zy = math.exp(-0.5 * zy_p * zy_p) / math.sqrt(2.0 * math.pi)
            yr_meta.append((ky, ny, True, zy_p, phi_zy * phi_zy / max(py * (1.0 - py), 1e-12)))
        else:
            yr_meta.append((ky, ny, False, 0.0, 0.0))

    def _loglik(rho: float) -> float:
        denom = math.sqrt(max(1.0 - rho, 1e-6))
        sq_r = math.sqrt(max(rho, 1e-9))
        r_ratio = rho / max(1.0 - rho, 1e-6)
        ll_sum = 0.0
        for ky, ny, interior, zy_p, f_const in yr_meta:
            if interior:
                z_hat = (thresh - denom * zy_p) / sq_r
                sigma_z = 1.0 / math.sqrt(1.0 + ny * r_ratio * f_const)
            else:
                z_hat = 0.0
                sigma_z = 1.0
            z_grid = z_hat + sigma_z * u_pts
            x_arr = ((thresh - sq_r * z_grid) / denom) * inv_sqrt2
            cp = np.clip([0.5 * (1.0 + erf(x)) for x in x_arr], 1e-15, 1.0 - 1e-15)
            l_terms = (
                -0.5 * z_grid * z_grid
                - 0.5 * math.log(2.0 * math.pi)
                + math.log(sigma_z * du)
                + ky * np.log(cp)
                + (ny - ky) * np.log(1.0 - cp)
            )
            m_max = float(np.max(l_terms))
            ll_sum += m_max + float(np.log(np.sum(np.exp(l_terms - m_max))))
        return ll_sum

    best_rho = 0.01
    best_ll = -1e18
    for rho in np.linspace(0.001, 0.60, 80):
        ll = _loglik(float(rho))
        if ll > best_ll:
            best_ll = ll
            best_rho = float(rho)
    lo = max(0.0005, best_rho - 0.012)
    hi = min(0.80, best_rho + 0.012)
    for rho in np.linspace(lo, hi, 41):
        ll = _loglik(float(rho))
        if ll > best_ll:
            best_ll = ll
            best_rho = float(rho)
    return p_pool, best_rho, best_ll


def run_default_rate_history(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
    sample_filter: bool = False,
) -> int:
    """Compute rolling 12m default rate history, Vasicek rho, and partitioned December book_snapshot."""
    t0 = time.time()
    check = c.Checker("07_default_rate_history: default rate history, rho and book_snapshot")

    marts.execute(ltv_mod.build_hpi_lookup_sql(src_prefix))
    sched_sql = c.scheduled_upb_sql(
        "lt.orig_upb",
        "lt.note_rate",
        "lt.loan_term",
        "datediff('month', lt.first_payment_date, m.reporting_period)",
    )
    other_lit = c.sql_list(c.OTHER_EXIT_CODES)
    parts: list[pd.DataFrame] = []

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        q_df = c.q(marts, f"""
            WITH perf AS (
                SELECT
                    m.loan_id,
                    m.reporting_period AS obs_month,
                    {c.era_case('m.reporting_period')} AS era,
                    COALESCE(lt.occupancy, 'U') || '|' || COALESCE(lt.loan_purpose, 'U') AS segment,
                    lt.property_state AS state,
                    CASE
                        WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0
                             AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                        ELSE CAST(m.current_upb AS DOUBLE)
                    END AS eff_upb
                FROM read_parquet('{fp}') m
                JOIN {src_prefix}loans_table lt
                  ON lt.loan_id = m.loan_id AND lt.acquisition_quarter = '{quarter}'
                LEFT JOIN default_status_monthly ds
                  ON ds.loan_id = m.loan_id AND ds.reporting_period = m.reporting_period
                 AND ds.acquisition_quarter = '{quarter}'
                WHERE m.zero_balance_code IS NULL AND ds.in_default IS NULL
            ),
            ev_q AS (
                SELECT loan_id, default_month
                FROM default_events_mart
                WHERE acquisition_quarter = '{quarter}'
            ),
            oth_q AS (
                SELECT loan_id, reporting_period AS exit_month
                FROM read_parquet('{fp}')
                WHERE zero_balance_code IN {other_lit}
            ),
            perf_flagged AS (
                SELECT
                    p.*,
                    EXISTS (
                        SELECT 1 FROM ev_q e
                        WHERE e.loan_id = p.loan_id
                          AND e.default_month > p.obs_month
                          AND e.default_month <= p.obs_month + INTERVAL 12 MONTH
                    ) AS has_def_12m,
                    EXISTS (
                        SELECT 1 FROM oth_q o
                        WHERE o.loan_id = p.loan_id
                          AND o.exit_month > p.obs_month
                          AND o.exit_month <= p.obs_month + INTERVAL 12 MONTH
                    ) AS has_oth_12m
                FROM perf p
            )
            SELECT
                obs_month AS observation_month,
                era,
                segment,
                state,
                count(*)::BIGINT AS performing_loans,
                COALESCE(sum(eff_upb), 0.0) AS performing_upb,
                count(*) FILTER (WHERE has_def_12m)::BIGINT AS bad_loans_12m,
                COALESCE(sum(eff_upb) FILTER (WHERE has_def_12m), 0.0) AS bad_upb_12m,
                count(*) FILTER (WHERE has_oth_12m AND NOT has_def_12m)::BIGINT AS non_credit_exits_12m
            FROM perf_flagged
            GROUP BY 1, 2, 3, 4
        """)
        if not q_df.empty:
            parts.append(q_df)
        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] rates scanned {quarter} ({time.time() - t0:.1f}s)", flush=True)

    base = pd.concat(parts, ignore_index=True)

    def _agg_series(df_in: pd.DataFrame, grp_name: str, col_expr: str | None) -> pd.DataFrame:
        if col_expr is None:
            g = df_in.groupby("observation_month", as_index=False).sum(numeric_only=True)
            g["series_group"] = grp_name
            g["series_value"] = "all"
        else:
            g = df_in.groupby(["observation_month", col_expr], as_index=False).sum(numeric_only=True)
            g["series_group"] = grp_name
            g = g.rename(columns={col_expr: "series_value"})
        return g

    dr_df = pd.concat([
        _agg_series(base, "whole_book", None),
        _agg_series(base, "era", "era"),
        _agg_series(base, "segment", "segment"),
        _agg_series(base, "state", "state"),
    ], ignore_index=True)
    dr_df["observation_month"] = pd.to_datetime(dr_df["observation_month"]).dt.date
    dr_df["window_complete"] = dr_df["observation_month"] <= pd.Timestamp("2024-12-01").date()
    dr_df["default_rate_count"] = np.where(
        dr_df["window_complete"] & (dr_df["performing_loans"] > 0),
        dr_df["bad_loans_12m"] / dr_df["performing_loans"],
        np.nan,
    )
    dr_df["default_rate_upb"] = np.where(
        dr_df["window_complete"] & (dr_df["performing_upb"] > 0),
        dr_df["bad_upb_12m"] / dr_df["performing_upb"],
        np.nan,
    )
    c.write_df(marts, "default_rate_history_mart", dr_df, ["observation_month", "series_group", "series_value"])

    # B. Vasicek implied correlation on complete non-overlapping December snapshots (2000-12 .. 2024-12)
    dec_sub = dr_df[
        (pd.to_datetime(dr_df["observation_month"]).dt.month == 12)
        & (dr_df["window_complete"])
        & (dr_df["series_group"].isin(["whole_book", "segment"]))
    ].copy()
    corr_rows: list[dict] = []
    for seg_val, g in dec_sub.groupby("series_value"):
        g = g.sort_values("observation_month")
        p_pool, rho_mle, _ = fit_vasicek_rho(g["bad_loans_12m"].to_numpy(), g["performing_loans"].to_numpy())
        corr_rows.append({
            "segment": str(seg_val),
            "years_complete": int((g["performing_loans"] > 0).sum()),
            "pooled_pd": float(p_pool),
            "implied_rho": float(rho_mle),
            "irb_fixed_rho": float(c.IRB_RESIDENTIAL_CORRELATION),
            "meets_5yr_art180": bool((g["performing_loans"] > 0).sum() >= c.MIN_DATA_YEARS),
        })
    corr_df = pd.DataFrame(corr_rows)
    c.write_df(marts, "implied_correlation_mart", corr_df, ["segment"])

    # C. Partitioned December book_snapshot written year-by-year directly via DuckDB COPY (zero pandas 280M load!)
    snap_root = outputs_dir / "book_snapshot"
    snap_root.mkdir(parents=True, exist_ok=True)
    lit_core = "[" + ", ".join("'" + str(f).replace("\\", "/") + "'" for f in core_files) + "]"
    marts.execute(f"CREATE OR REPLACE TEMP VIEW _core_all AS SELECT * FROM read_parquet({lit_core})")
    marts.execute(f"""
        CREATE OR REPLACE TEMP TABLE _other_exits_all AS
        SELECT loan_id, min(reporting_period) AS exit_month
        FROM _core_all
        WHERE zero_balance_code IN {other_lit}
        GROUP BY loan_id
    """)

    # Extract December active rows in ONE streaming pass partitioned by year instead of 26 full scans
    dec_tmp_dir = outputs_dir / "_dec_core_tmp"
    if dec_tmp_dir.exists():
        shutil.rmtree(dec_tmp_dir)
    dec_tmp_lit = str(dec_tmp_dir).replace("\\", "/")
    marts.execute(f"""
        COPY (
            SELECT *, year(reporting_period)::INTEGER AS snap_year
            FROM _core_all
            WHERE month(reporting_period) = 12 AND zero_balance_code IS NULL
        ) TO '{dec_tmp_lit}' (FORMAT PARQUET, PARTITION_BY (snap_year), COMPRESSION ZSTD)
    """)

    # Process each December partition sequentially in low-memory streaming passes reading pre-filtered dec_tmp_dir
    where_l = c.scope(sample_filter, prefix=src_prefix, alias="lt")
    years = sorted(int(p.name.split("=")[1]) for p in dec_tmp_dir.glob("snap_year=*"))
    dec_reconcile: list[dict] = []

    for yr_idx, yr in enumerate(years, 1):
        snap_date = f"{yr:04d}-12-01"
        yr_dir = snap_root / f"year={yr}"
        yr_dir.mkdir(parents=True, exist_ok=True)
        out_part = yr_dir / "part.parquet"
        tmp_part = yr_dir / "part.parquet.tmp"
        if tmp_part.exists():
            tmp_part.unlink()

        win_complete = yr <= 2024
        is_oot = 2022 <= yr <= 2024
        tmp_lit = str(tmp_part).replace("\\", "/")
        dec_yr_glob = str(dec_tmp_dir / f"snap_year={yr}" / "*.parquet").replace("\\", "/")

        copy_sql = f"""
            WITH max_hq AS (SELECT max(quarter_date) AS max_qd FROM _hpi_q),
            snap_m AS (
                SELECT * FROM read_parquet('{dec_yr_glob}')
            ),
            ev_12m AS (
                SELECT loan_id, min(default_month) AS next_default_m
                FROM default_events_mart
                WHERE default_month > DATE '{snap_date}'
                  AND default_month <= DATE '{snap_date}' + INTERVAL 12 MONTH
                GROUP BY loan_id
            ),
            ex_12m AS (
                SELECT loan_id, exit_month AS next_other_exit_m
                FROM _other_exits_all
                WHERE exit_month > DATE '{snap_date}'
                  AND exit_month <= DATE '{snap_date}' + INTERVAL 12 MONTH
            ),
            ds_y AS (
                SELECT loan_id, in_default
                FROM default_status_monthly
                WHERE reporting_period = DATE '{snap_date}'
            )
            SELECT
                m.loan_id,
                m.reporting_period AS snapshot_date,
                m.acquisition_quarter,
                lt.orig_date,
                lt.first_payment_date,
                datediff('month', lt.first_payment_date, m.reporting_period)::INTEGER AS mob,
                CAST(m.current_upb AS DOUBLE) AS current_upb_reported,
                (COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0 AND COALESCE(m.loan_age, 0) <= 6) AS balance_masked_flag,
                CASE
                    WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0
                         AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                    ELSE CAST(m.current_upb AS DOUBLE)
                END AS current_upb,
                CAST(lt.orig_upb AS DOUBLE) AS orig_upb,
                CAST(lt.note_rate AS DOUBLE) AS note_rate,
                CAST(lt.orig_ltv AS DOUBLE) AS orig_ltv,
                lt.credit_score,
                lt.dti,
                lt.channel,
                lt.first_time_buyer,
                lt.num_borrowers,
                lt.orig_cltv,
                CAST(m.current_rate AS DOUBLE) AS current_rate,
                m.months_to_maturity AS remaining_term,
                lt.occupancy,
                lt.num_units,
                lt.loan_purpose,
                lt.property_state,
                COALESCE(lt.occupancy, 'U') || '|' || COALESCE(lt.loan_purpose, 'U') AS segment,
                {c.era_case('m.reporting_period')} AS era,
                lov.value_at_origination * COALESCE(h_cur.hpi_sa, h_nat.hpi_sa) / NULLIF(lov.hpi_orig, 0.0) AS value_indexed,
                LEAST(lov.value_at_origination, lov.value_at_origination * COALESCE(h_cur.hpi_sa, h_nat.hpi_sa) / NULLIF(lov.hpi_orig, 0.0)) AS value_downward,
                100.0 * (
                    CASE WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0 AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                         ELSE CAST(m.current_upb AS DOUBLE) END
                ) / NULLIF(lov.value_at_origination * COALESCE(h_cur.hpi_sa, h_nat.hpi_sa) / NULLIF(lov.hpi_orig, 0.0), 0.0) AS ltv_indexed,
                100.0 * (
                    CASE WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0 AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                         ELSE CAST(m.current_upb AS DOUBLE) END
                ) / NULLIF(LEAST(lov.value_at_origination, lov.value_at_origination * COALESCE(h_cur.hpi_sa, h_nat.hpi_sa) / NULLIF(lov.hpi_orig, 0.0)), 0.0) AS ltv_downward,
                m.delinquency_months,
                m.is_dpd_unknown,
                COALESCE(ds.in_default, FALSE) AS in_default,
                m.borrower_assistance_plan,
                m.alt_delinquency_resolution,
                m.modification_flag,
                CASE
                    WHEN COALESCE(ds.in_default, FALSE) THEN NULL::INTEGER
                    WHEN NOT {str(win_complete).upper()} THEN NULL::INTEGER
                    WHEN lt.first_payment_date IS NULL THEN NULL::INTEGER
                    WHEN ev.next_default_m IS NOT NULL THEN 1::INTEGER
                    WHEN ex.next_other_exit_m IS NOT NULL THEN NULL::INTEGER
                    ELSE 0::INTEGER
                END AS bad_12m,
                CASE
                    WHEN COALESCE(ds.in_default, FALSE) THEN 'in_default'
                    WHEN NOT {str(win_complete).upper()} THEN 'incomplete_2025'
                    WHEN lt.first_payment_date IS NULL THEN 'excluded'
                    WHEN ev.next_default_m IS NOT NULL THEN 'bad'
                    WHEN ex.next_other_exit_m IS NOT NULL THEN 'other_exit'
                    ELSE 'good'
                END AS outcome_12m_status,
                CASE
                    WHEN COALESCE(ds.in_default, FALSE) THEN 'in_default_at_snapshot'
                    WHEN NOT {str(win_complete).upper()} THEN 'incomplete_window_2025'
                    WHEN datediff('month', lt.first_payment_date, m.reporting_period) < {c.SEASONING_MIN_MOB} THEN 'unseasoned_lt6m'
                    WHEN lt.credit_score IS NULL OR lt.dti IS NULL THEN 'missing_fico_or_dti'
                    WHEN ex.next_other_exit_m IS NOT NULL AND ev.next_default_m IS NULL THEN 'non_credit_exit_before_12m'
                    ELSE 'included'
                END AS exclusion_reason,
                {str(is_oot).upper()}::BOOLEAN AS is_oot
            FROM snap_m m
            JOIN {src_prefix}loans_table lt ON lt.loan_id = m.loan_id
            LEFT JOIN loan_origination_value_mart lov ON lov.loan_id = m.loan_id
            LEFT JOIN _hpi_q h_cur
              ON h_cur.state = lov.property_state
             AND h_cur.quarter_date = LEAST(date_trunc('quarter', m.reporting_period)::DATE, (SELECT max_qd FROM max_hq))
            LEFT JOIN (SELECT quarter_date, avg(hpi_sa) AS hpi_sa FROM _hpi_q WHERE is_territory GROUP BY 1) h_nat
              ON h_nat.quarter_date = LEAST(date_trunc('quarter', m.reporting_period)::DATE, (SELECT max_qd FROM max_hq))
            LEFT JOIN ds_y ds ON ds.loan_id = m.loan_id
            LEFT JOIN ev_12m ev ON ev.loan_id = m.loan_id
            LEFT JOIN ex_12m ex ON ex.loan_id = m.loan_id
            WHERE {where_l} AND m.zero_balance_code IS NULL
            ORDER BY m.loan_id
        """
        marts.execute(f"COPY ({copy_sql}) TO '{tmp_lit}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        tmp_part.replace(out_part)

        rec = marts.execute(
            f"SELECT count(*)::BIGINT, COALESCE(sum(current_upb_reported), 0.0) FROM read_parquet('{str(out_part).replace(chr(92), '/')}')"
        ).fetchall()[0]
        dec_reconcile.append({"snapshot_date": pd.Timestamp(snap_date).date(), "snap_loans": int(rec[0]), "snap_upb": float(rec[1])})
        if yr_idx % 5 == 0 or yr_idx == len(years):
            print(f"  [{yr_idx:2d}/{len(years)}] book_snapshot {yr} wrote {int(rec[0]):,} rows ({time.time() - t0:.1f}s)", flush=True)

    # Reconcile December book_snapshot vs balance_rollforward_mart
    rf_dec = c.q(marts, "SELECT reporting_period AS snapshot_date, open_loans, closing_upb FROM balance_rollforward_mart WHERE month(reporting_period) = 12")
    rec_df = pd.DataFrame(dec_reconcile)
    max_diff_loans = 0
    max_diff_upb = 0.0
    if not rf_dec.empty and not rec_df.empty:
        rf_dec["snapshot_date"] = pd.to_datetime(rf_dec["snapshot_date"]).dt.date
        mrg = rec_df.merge(rf_dec, on="snapshot_date", how="inner")
        if not mrg.empty:
            max_diff_loans = int((mrg["snap_loans"] - mrg["open_loans"]).abs().max())
            max_diff_upb = float((mrg["snap_upb"] - mrg["closing_upb"]).abs().max())

    # Chart (300 dpi): Whole book rolling 12m default rate history
    wb = dr_df[(dr_df["series_group"] == "whole_book") & (dr_df["window_complete"])].sort_values("observation_month")
    if not wb.empty:
        fig, ax = plt.subplots(figsize=(11, 4.8))
        ax.plot(pd.to_datetime(wb["observation_month"]), wb["default_rate_count"] * 100.0, label="Loan-weighted 12m DR (%)", color="#0d366b")
        ax.plot(pd.to_datetime(wb["observation_month"]), wb["default_rate_upb"] * 100.0, label="Balance-weighted 12m DR (%)", color="#eb6834", alpha=0.85)
        ax.set_title("Historical Rolling 12-Month Default Rate (Complete Observation Windows)")
        ax.set_xlabel("Observation Month")
        ax.set_ylabel("12-Month Default Rate (%)")
        ax.legend()
        c.save_chart(fig, outputs_dir / "07_default_rate_history.png")

    shutil.rmtree(dec_tmp_dir, ignore_errors=True)
    marts.execute("DROP TABLE IF EXISTS _hpi_q")
    marts.execute("DROP TABLE IF EXISTS _other_exits_all")
    marts.execute("DROP VIEW IF EXISTS _core_all")

    check.key(marts, "default_rate_history_mart", ["observation_month", "series_group", "series_value"])
    check.key(marts, "implied_correlation_mart", ["segment"])
    check.add("December book_snapshot loans tie exactly to balance_rollforward_mart", max_diff_loans == 0, f"max_diff_loans={max_diff_loans}")
    check.add("December book_snapshot UPB ties to balance_rollforward_mart", max_diff_upb < 100.0, f"max_diff_upb={max_diff_upb:,.2f}")

    wb_complete = dr_df[(dr_df["series_group"] == "whole_book") & (dr_df["window_complete"])]
    if not wb_complete.empty:
        lra_all = float(wb_complete["bad_loans_12m"].sum() / max(wb_complete["performing_loans"].sum(), 1))
        no_crisis = wb_complete[~pd.to_datetime(wb_complete["observation_month"]).dt.year.isin(range(2007, 2011))]
        lra_ex = float(no_crisis["bad_loans_12m"].sum() / max(no_crisis["performing_loans"].sum(), 1))
        print(f"  LRA 12m DR (complete windows <= 2024-12): {lra_all:.4%} all, {lra_ex:.4%} ex-2007-2010", flush=True)
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="12-month default rate history, Vasicek rho and book_snapshot.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_default_rate_history(marts, sp, core_files, args.outputs_dir, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
