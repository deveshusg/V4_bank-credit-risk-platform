"""Quarterly portfolio rates and macro links without look-ahead (Stage E, script 13).

Fixes all design review H5 defects:
- Uses explicit denominators: default_rate = new default starts / performing loan-quarters,
  cure_rate = cures / in_default loan-quarters, prepayment = quarterly CPR, severity = realised
  credit-exit net loss / balance_at_default by default quarter.
- Shifts macro series strictly for publication delay without look-ahead:
  FEDFUNDS +1m, UNRATE +1m (preserving October 2025 missing gap cleanly), national HPI +2m,
  state HPI +1 quarter (2 months after quarter end).
- Aligns correlations strictly on rate[t] against lagged macro[t - lag] for lag in 0..8 quarters (0..24m).

Outputs: portfolio_rates_quarterly_mart, economy_correlations_mart, macro_downturn_mart, 13_economy_links.png.
Run: python residential_mortgage/02_portfolio_analytics/scripts/13_economy_links.py [--full]
"""

from __future__ import annotations

import argparse
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


# Build quarterly portfolio performance rates aligned strictly with publication-lagged macro series
# Computes 0..24m lagged Pearson correlations, downturn magnitudes, and macro overlay chart
def run_economy_links(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
) -> int:
    """Compute quarterly portfolio rates, lagged macro joins, and lead/lag correlations (0..24m)."""
    t0 = time.time()
    check = c.Checker("13_economy_links: quarterly rates and publication-lagged macro links")

    # 1. Quarterly performing vs in-default loan-quarters & voluntary payoffs from core_files
    q_parts: list[pd.DataFrame] = []
    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        q_df = c.q(marts, f"""
            WITH seg AS (
                SELECT loan_id, COALESCE(occupancy, 'U') || '|' || COALESCE(loan_purpose, 'U') AS segment
                FROM {src_prefix}loans_table
                WHERE acquisition_quarter = '{quarter}'
            )
            SELECT
                date_trunc('quarter', m.reporting_period)::DATE AS quarter_date,
                s.segment,
                count(*) FILTER (WHERE m.zero_balance_code IS NULL AND ds.in_default IS NULL)::BIGINT AS perf_loan_months,
                count(*) FILTER (WHERE ds.in_default IS NOT NULL)::BIGINT AS default_loan_months,
                count(*) FILTER (WHERE m.zero_balance_code = '01' AND ds.in_default IS NULL)::BIGINT AS perf_payoffs
            FROM read_parquet('{fp}') m
            JOIN seg s ON s.loan_id = m.loan_id
            LEFT JOIN default_status_monthly ds
              ON ds.loan_id = m.loan_id AND ds.reporting_period = m.reporting_period
             AND ds.acquisition_quarter = '{quarter}'
            GROUP BY 1, 2
        """)
        if not q_df.empty:
            q_parts.append(q_df)
        if idx % 25 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] quarter exposures {quarter} ({time.time() - t0:.1f}s)", flush=True)

    exp_df = pd.concat(q_parts, ignore_index=True).groupby(["quarter_date", "segment"], as_index=False).sum(numeric_only=True)

    ev_q = c.q(marts, f"""
        WITH seg AS (
            SELECT loan_id, COALESCE(occupancy, 'U') || '|' || COALESCE(loan_purpose, 'U') AS segment
            FROM {src_prefix}loans_table
        )
        SELECT
            date_trunc('quarter', d.default_month)::DATE AS quarter_date,
            s.segment,
            count(*)::BIGINT AS default_starts,
            count(*) FILTER (WHERE d.end_reason = 'credit exit')::BIGINT AS closed_credit_exits,
            COALESCE(sum(CAST(d.balance_at_default AS DOUBLE)) FILTER (WHERE d.end_reason = 'credit exit'), 0.0) AS closed_def_upb,
            COALESCE(sum(CAST(d.net_loss AS DOUBLE)) FILTER (WHERE d.end_reason = 'credit exit'), 0.0) AS closed_net_loss
        FROM default_outcomes_mart d
        JOIN seg s ON s.loan_id = d.loan_id
        GROUP BY 1, 2
    """)
    cure_q = c.q(marts, f"""
        WITH seg AS (
            SELECT loan_id, COALESCE(occupancy, 'U') || '|' || COALESCE(loan_purpose, 'U') AS segment
            FROM {src_prefix}loans_table
        )
        SELECT
            date_trunc('quarter', d.cure_month)::DATE AS quarter_date,
            s.segment,
            count(*)::BIGINT AS cures
        FROM default_events_mart d
        JOIN seg s ON s.loan_id = d.loan_id
        WHERE d.cure_month IS NOT NULL
        GROUP BY 1, 2
    """)

    rates = exp_df.merge(ev_q, on=["quarter_date", "segment"], how="left").merge(cure_q, on=["quarter_date", "segment"], how="left")
    for col in ["default_starts", "closed_credit_exits", "closed_def_upb", "closed_net_loss", "cures"]:
        rates[col] = rates[col].fillna(0)

    # Union whole-portfolio quarterly counts alongside occupancy x purpose segment rows
    # Computes annualized default rates, cure rates, CPR, and closed credit-exit severity
    wb = rates.groupby("quarter_date", as_index=False).sum(numeric_only=True)
    wb["segment"] = "ALL"
    rates = pd.concat([wb, rates], ignore_index=True)

    # Align each portfolio quarter with contemporaneous and 0-to-24m lagged FRED/FHFA macro series
    # Shifts macro lookup dates backward cleanly so future macro releases never leak into features
    macro_q = c.q(marts, f"""
        WITH unrate_lag AS (
            SELECT
                date_trunc('quarter', (period + INTERVAL 1 MONTH))::DATE AS eff_qd,
                avg(CAST(unemployment_rate_pct AS DOUBLE)) AS unrate_pct,
                avg(CAST(unemployment_change_12m AS DOUBLE)) AS unrate_chg_12m,
                bool_or(unemployment_missing) AS has_unrate_gap
            FROM {src_prefix}macro_economic_mart
            GROUP BY 1
        ),
        fed_lag AS (
            SELECT
                date_trunc('quarter', (period + INTERVAL 1 MONTH))::DATE AS eff_qd,
                avg(CAST(federal_funds_rate_pct AS DOUBLE)) AS fed_funds_pct
            FROM {src_prefix}macro_economic_mart
            GROUP BY 1
        ),
        hpi_nat_lag AS (
            SELECT
                date_trunc('quarter', (period + INTERVAL 2 MONTH))::DATE AS eff_qd,
                avg(CAST(house_price_change_12m_pct AS DOUBLE)) AS nat_hpi_chg_12m_pct
            FROM {src_prefix}macro_economic_mart
            GROUP BY 1
        ),
        hpi_st_lag AS (
            SELECT
                date_trunc('quarter', quarter_date + INTERVAL 3 MONTH - INTERVAL 1 DAY + INTERVAL 2 MONTH)::DATE AS eff_qd,
                avg(CAST(house_price_change_12m_pct AS DOUBLE)) AS mean_state_hpi_chg_12m_pct
            FROM {src_prefix}macro_state_hpi_table
            GROUP BY 1
        )
        SELECT
            COALESCE(u.eff_qd, f.eff_qd, h.eff_qd) AS quarter_date,
            u.unrate_pct,
            u.unrate_chg_12m,
            u.has_unrate_gap,
            f.fed_funds_pct,
            h.nat_hpi_chg_12m_pct,
            s.mean_state_hpi_chg_12m_pct
        FROM unrate_lag u
        FULL OUTER JOIN fed_lag f ON f.eff_qd = u.eff_qd
        FULL OUTER JOIN hpi_nat_lag h ON h.eff_qd = COALESCE(u.eff_qd, f.eff_qd)
        LEFT JOIN hpi_st_lag s ON s.eff_qd = COALESCE(u.eff_qd, f.eff_qd, h.eff_qd)
        ORDER BY 1
    """)

    rates["quarter_date"] = pd.to_datetime(rates["quarter_date"]).dt.date
    macro_q["quarter_date"] = pd.to_datetime(macro_q["quarter_date"]).dt.date
    rates = rates.merge(macro_q, on="quarter_date", how="left")

    # Annualized default rate (~3 months in a quarter -> monthly hazard * 3 quarterly or * 12 annualized), quarterly cure rate, CPR, and loss severity
    m_def_haz = (rates["default_starts"] / rates["perf_loan_months"].clip(lower=1)).clip(upper=1.0)
    rates["default_rate_ann"] = 1.0 - (1.0 - m_def_haz) ** 12
    m_cure_haz = (rates["cures"] / rates["default_loan_months"].clip(lower=1)).clip(upper=1.0)
    rates["cure_rate_qtr"] = 1.0 - (1.0 - m_cure_haz) ** 3
    m_pay_haz = (rates["perf_payoffs"] / rates["perf_loan_months"].clip(lower=1)).clip(upper=1.0)
    rates["cpr_qtr"] = 1.0 - (1.0 - m_pay_haz) ** 12
    rates["loss_severity"] = np.where(rates["closed_def_upb"] > 0, rates["closed_net_loss"] / rates["closed_def_upb"], np.nan)

    c.write_df(marts, "portfolio_rates_quarterly_mart", rates, ["quarter_date", "segment"])

    # Lead/lag correlations on ALL segment strictly with positive macro lag: rate[t] vs macro[t - k]
    all_r = rates[rates["segment"] == "ALL"].sort_values("quarter_date").reset_index(drop=True)
    corr_rows: list[dict] = []
    macro_cols = ["unrate_pct", "unrate_chg_12m", "nat_hpi_chg_12m_pct", "fed_funds_pct"]
    rate_cols = ["default_rate_ann", "cure_rate_qtr", "cpr_qtr", "loss_severity"]

    for q_lag in range(0, 9):  # 0 to 8 quarters = 0 to 24 months
        for m_col in macro_cols:
            lagged_m = all_r[m_col].shift(q_lag)  # macro at [t - q_lag]
            for r_col in rate_cols:
                valid = all_r[r_col].notna() & lagged_m.notna()
                n_obs = int(valid.sum())
                val = float(all_r.loc[valid, r_col].corr(lagged_m.loc[valid])) if n_obs >= 4 else float("nan")
                corr_rows.append({
                    "series_name": m_col,
                    "rate_name": r_col,
                    "lag_months": int(q_lag * 3),
                    "geography": "US_NATIONAL",
                    "n_quarters": n_obs,
                    "pearson_corr": val,
                })
    corr_df = pd.DataFrame(corr_rows)
    c.write_df(marts, "economy_correlations_mart", corr_df, ["series_name", "rate_name", "lag_months", "geography"])

    # Past downturn macro severity nationally + state HPI peak-to-trough summary
    nat_macro = c.q(marts, f"SELECT period, CAST(unemployment_rate_pct AS DOUBLE) AS u, CAST(national_house_price_index_sa AS DOUBLE) AS h FROM {src_prefix}macro_economic_mart ORDER BY period")
    downturn_rows: list[dict] = []
    if not nat_macro.empty:
        u_df = nat_macro.dropna(subset=["u"])
        # Max trough-to-peak unemployment rise
        run_min_u = u_df["u"].cummin()
        u_rise = u_df["u"] - run_min_u
        pk_idx = u_rise.idxmax()
        tr_idx = u_df.loc[:pk_idx, "u"].idxmin()
        downturn_rows.append({
            "geography": "US_NATIONAL",
            "indicator": "unemployment_rate_rise_pp",
            "peak_date": u_df.loc[tr_idx, "period"],
            "trough_date": u_df.loc[pk_idx, "period"],
            "move_magnitude": float(u_rise.loc[pk_idx]),
        })
        h_df = nat_macro.dropna(subset=["h"]).rename(columns={"period": "quarter_date", "h": "house_price_index_sa"})
        h_df["state"] = "US_NATIONAL"
        h_ep = ltv_mod.compute_drawdown_episodes(h_df)
        for _, r in h_ep.iterrows():
            downturn_rows.append({
                "geography": "US_NATIONAL",
                "indicator": "national_hpi_fall_pct",
                "peak_date": r["peak_date"],
                "trough_date": r["trough_date"],
                "move_magnitude": float(r["fall_pct"]),
            })
    md_df = pd.DataFrame(downturn_rows)
    md_df["peak_date"] = pd.to_datetime(md_df["peak_date"]).dt.date
    md_df["trough_date"] = pd.to_datetime(md_df["trough_date"]).dt.date
    c.write_df(marts, "macro_downturn_mart", md_df, ["geography", "indicator", "peak_date", "trough_date"])

    # Render dual-axis macro stress comparison between annualized defaults and unemployment rate
    # Saves publication-ready 300 dpi chart to 13_economy_links output folder
    if not all_r.empty:
        fig, ax1 = plt.subplots(figsize=(11, 4.8))
        xdates = pd.to_datetime(all_r["quarter_date"])
        ax1.plot(xdates, all_r["default_rate_ann"] * 100.0, color="#0d366b", label="Annualized Default Rate (%)")
        ax1.set_xlabel("Calendar Quarter")
        ax1.set_ylabel("Annualized Default Rate (%)", color="#0d366b")
        ax2 = ax1.twinx()
        ax2.plot(xdates, all_r["unrate_pct"], color="#eb6834", linestyle="--", label="Lagged US Unemployment (%)")
        ax2.set_ylabel("US Unemployment Rate (%, lagged +1m)", color="#eb6834")
        ax1.set_title("Quarterly Portfolio Default Rate vs Publication-Lagged Unemployment")
        c.save_chart(fig, c.script_out(outputs_dir, "13_economy_links") / "13_economy_links.png")

    check.key(marts, "portfolio_rates_quarterly_mart", ["quarter_date", "segment"])
    check.key(marts, "economy_correlations_mart", ["series_name", "rate_name", "lag_months", "geography"])
    check.key(marts, "macro_downturn_mart", ["geography", "indicator", "peak_date", "trough_date"])
    check.add("lagged correlations strictly span [0, 24] months", set(corr_df["lag_months"]) == {0, 3, 6, 9, 12, 15, 18, 21, 24})
    return check.finish()


# Parse CLI arguments for 13_economy_links
# Uses module2_common.add_common_args()
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Quarterly portfolio rates and publication-lagged macro links.")
    c.add_common_args(parser)
    return parser.parse_args()


# Connect to marts and source DBs and build lagged macro-to-portfolio linkage tables
# Verifies scope match, reads core Parquet partitions, and invokes run_economy_links()
def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_economy_links(marts, sp, core_files, args.outputs_dir)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
