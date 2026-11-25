"""Current LTV (indexed and downward-only) and peak-to-trough house prices (Stage B, script 06).

Fixes all design review C2 defects:
- Pure DuckDB SQL execution per acquisition quarter (never loads 57.6M rows in pandas).
- Handles 11 null/zero orig_ltv rows safely without division by zero.
- Handles 160,137 pre-2000 originations (clamp to 2000Q1 + hpi_pre2000_fallback=TRUE)
  and 144,134 PR/VI/GU territory loans (national SA HPI quarterly fallback + hpi_territory_fallback=TRUE).
- Peak-to-trough HPI uses running historical peak max_{u<=t} HPI_u and fall_pct = (1 - HPI/M)*100,
  capturing the 2006-2012 crash and >10% / >=25% / >=40% episodes cleanly (not global idxmax 2025).

Outputs: loan_origination_value_mart, state_hpi_peaktotrough_mart, current_ltv_mart, 06_hpi_drawdowns.png.
Run: python residential_mortgage/02_portfolio_analytics/scripts/06_current_ltv.py [--full]
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


def compute_drawdown_episodes(hpi_df: pd.DataFrame) -> pd.DataFrame:
    """Detect distinct peak-to-trough drawdown episodes per state using running historical max."""
    rows: list[dict] = []
    for state, g in hpi_df.groupby("state"):
        g = g.sort_values("quarter_date").reset_index(drop=True)
        vals = g["house_price_index_sa"].to_numpy(dtype=float)
        dates = g["quarter_date"].tolist()
        if len(vals) == 0:
            continue

        running_peak = vals[0]
        peak_date = dates[0]
        in_ep = False
        ep_peak = running_peak
        ep_peak_date = peak_date
        ep_trough = running_peak
        ep_trough_date = peak_date
        ep_id = 0

        # Track maximum overall historical drawdown even if episode is ongoing or <2%
        best_fall = 0.0
        best_peak_d = dates[0]
        best_trough_d = dates[0]

        for val, dt in zip(vals, dates):
            if val >= running_peak:
                if in_ep:
                    fall_pct = (1.0 - ep_trough / ep_peak) * 100.0
                    ep_id += 1
                    rows.append({
                        "state": state,
                        "episode_id": ep_id,
                        "peak_date": ep_peak_date,
                        "trough_date": ep_trough_date,
                        "recovery_date": dt,
                        "peak_hpi": float(ep_peak),
                        "trough_hpi": float(ep_trough),
                        "fall_pct": float(fall_pct),
                        "exceeds_10pct_art124d": bool(fall_pct > 10.0),
                        "exceeds_25pct_min": bool(fall_pct >= 25.0),
                        "exceeds_40pct_ref": bool(fall_pct >= 40.0),
                    })
                    in_ep = False
                running_peak = val
                peak_date = dt
            else:
                fall = (1.0 - val / running_peak) * 100.0
                if fall > best_fall:
                    best_fall = fall
                    best_peak_d = peak_date
                    best_trough_d = dt
                if not in_ep and fall >= 1.0:
                    in_ep = True
                    ep_peak = running_peak
                    ep_peak_date = peak_date
                    ep_trough = val
                    ep_trough_date = dt
                elif in_ep and val <= ep_trough:
                    ep_trough = val
                    ep_trough_date = dt

        if in_ep:
            fall_pct = (1.0 - ep_trough / ep_peak) * 100.0
            ep_id += 1
            rows.append({
                "state": state,
                "episode_id": ep_id,
                "peak_date": ep_peak_date,
                "trough_date": ep_trough_date,
                "recovery_date": pd.NaT,
                "peak_hpi": float(ep_peak),
                "trough_hpi": float(ep_trough),
                "fall_pct": float(fall_pct),
                "exceeds_10pct_art124d": bool(fall_pct > 10.0),
                "exceeds_25pct_min": bool(fall_pct >= 25.0),
                "exceeds_40pct_ref": bool(fall_pct >= 40.0),
            })
        elif ep_id == 0:
            rows.append({
                "state": state,
                "episode_id": 1,
                "peak_date": best_peak_d,
                "trough_date": best_trough_d,
                "recovery_date": pd.NaT,
                "peak_hpi": float(running_peak),
                "trough_hpi": float(running_peak * (1.0 - best_fall / 100.0)),
                "fall_pct": float(best_fall),
                "exceeds_10pct_art124d": bool(best_fall > 10.0),
                "exceeds_25pct_min": bool(best_fall >= 25.0),
                "exceeds_40pct_ref": bool(best_fall >= 40.0),
            })

    out = pd.DataFrame(rows)
    if not out.empty:
        for col in ("peak_date", "trough_date", "recovery_date"):
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.date
    return out


def build_hpi_lookup_sql(src_prefix: str) -> str:
    """Create state + territory HPI quarterly series starting 2000Q1 in marts DB."""
    return f"""
        CREATE OR REPLACE TEMP TABLE _hpi_q AS
        SELECT state, quarter_date, CAST(house_price_index_sa AS DOUBLE) AS hpi_sa, FALSE AS is_territory
        FROM {src_prefix}macro_state_hpi_table
        UNION ALL
        SELECT
            t.state,
            date_trunc('quarter', m.period)::DATE AS quarter_date,
            avg(CAST(m.national_house_price_index_sa AS DOUBLE)) AS hpi_sa,
            TRUE AS is_territory
        FROM (VALUES ('PR'), ('VI'), ('GU')) AS t(state)
        CROSS JOIN {src_prefix}macro_economic_mart m
        WHERE m.national_house_price_index_sa IS NOT NULL
          AND m.period >= DATE '2000-01-01'
        GROUP BY 1, 2
    """


def run_current_ltv(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
    sample_filter: bool = False,
) -> int:
    """Build origination property values, HPI downturn episodes, and quarterly current LTV bands."""
    t0 = time.time()
    check = c.Checker("06_current_ltv: indexed and downward-only LTV and HPI falls")

    # 1. Unified state + territory HPI lookup and max drawdown episodes
    marts.execute(build_hpi_lookup_sql(src_prefix))
    hpi_state_df = c.q(marts, f"SELECT state, quarter_date, CAST(house_price_index_sa AS DOUBLE) AS house_price_index_sa FROM {src_prefix}macro_state_hpi_table ORDER BY 1, 2")
    ep_df = compute_drawdown_episodes(hpi_state_df)
    c.write_df(marts, "state_hpi_peaktotrough_mart", ep_df, ["state", "episode_id", "peak_date", "trough_date"])

    # 2. Build loan_origination_value_mart completely inside DuckDB SQL
    where_l = c.scope(sample_filter, prefix=src_prefix)
    marts.execute(f"""
        CREATE OR REPLACE TABLE loan_origination_value_mart AS
        WITH min_q AS (SELECT min(quarter_date) AS min_qd, max(quarter_date) AS max_qd FROM _hpi_q WHERE NOT is_territory)
        SELECT
            lt.loan_id,
            lt.acquisition_quarter,
            lt.property_state,
            lt.orig_date,
            CAST(lt.orig_upb AS DOUBLE) AS orig_upb,
            CAST(lt.orig_ltv AS DOUBLE) AS orig_ltv,
            CASE
                WHEN lt.orig_ltv IS NOT NULL AND lt.orig_ltv > 0 AND lt.orig_upb IS NOT NULL
                THEN CAST(lt.orig_upb AS DOUBLE) / (CAST(lt.orig_ltv AS DOUBLE) / 100.0)
                ELSE NULL
            END AS value_at_origination,
            (lt.orig_ltv IS NULL OR lt.orig_ltv <= 0) AS invalid_orig_ltv_flag,
            (lt.orig_date < (SELECT min_qd FROM min_q)) AS hpi_pre2000_fallback,
            (lt.property_state IN ('PR', 'VI', 'GU') OR h_base.state IS NULL) AS hpi_territory_fallback,
            COALESCE(h_base.hpi_sa, h_terr.hpi_sa, h_nat.hpi_sa) AS hpi_orig,
            LEAST(GREATEST(date_trunc('quarter', lt.orig_date)::DATE, (SELECT min_qd FROM min_q)), (SELECT max_qd FROM min_q)) AS hpi_orig_quarter
        FROM {src_prefix}loans_table lt
        LEFT JOIN _hpi_q h_base
          ON h_base.state = lt.property_state
         AND NOT h_base.is_territory
         AND h_base.quarter_date = LEAST(GREATEST(date_trunc('quarter', lt.orig_date)::DATE, (SELECT min_qd FROM min_q)), (SELECT max_qd FROM min_q))
        LEFT JOIN _hpi_q h_terr
          ON h_terr.state = lt.property_state
         AND h_terr.is_territory
         AND h_terr.quarter_date = LEAST(GREATEST(date_trunc('quarter', lt.orig_date)::DATE, (SELECT min_qd FROM min_q)), (SELECT max_qd FROM min_q))
        LEFT JOIN (
            SELECT quarter_date, avg(hpi_sa) AS hpi_sa FROM _hpi_q WHERE is_territory GROUP BY 1
        ) h_nat
          ON h_nat.quarter_date = LEAST(GREATEST(date_trunc('quarter', lt.orig_date)::DATE, (SELECT min_qd FROM min_q)), (SELECT max_qd FROM min_q))
        WHERE {where_l}
    """)

    # 3. Aggregate quarterly portfolio current LTV (quarter-end reporting months: 3, 6, 9, 12)
    sched_sql = c.scheduled_upb_sql(
        "lt.orig_upb",
        "lt.note_rate",
        "lt.loan_term",
        "datediff('month', lt.first_payment_date, m.reporting_period)",
    )
    cltv_parts: list[pd.DataFrame] = []
    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        q_df = c.q(marts, f"""
            WITH max_hq AS (SELECT max(quarter_date) AS max_qd FROM _hpi_q),
            base AS (
                SELECT
                    date_trunc('quarter', m.reporting_period)::DATE AS quarter_date,
                    COALESCE(lt.occupancy, 'U') || '|' || COALESCE(lt.loan_purpose, 'U') AS segment,
                    CASE
                        WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0
                             AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                        ELSE CAST(m.current_upb AS DOUBLE)
                    END AS eff_upb,
                    lov.value_at_origination,
                    lov.value_at_origination * COALESCE(h_cur.hpi_sa, h_nat.hpi_sa) / NULLIF(lov.hpi_orig, 0.0) AS val_idx
                FROM read_parquet('{fp}') m
                JOIN {src_prefix}loans_table lt
                  ON lt.loan_id = m.loan_id AND lt.acquisition_quarter = '{quarter}'
                JOIN loan_origination_value_mart lov
                  ON lov.loan_id = m.loan_id
                LEFT JOIN _hpi_q h_cur
                  ON h_cur.state = lov.property_state
                 AND h_cur.quarter_date = LEAST(date_trunc('quarter', m.reporting_period)::DATE, (SELECT max_qd FROM max_hq))
                LEFT JOIN (SELECT quarter_date, avg(hpi_sa) AS hpi_sa FROM _hpi_q WHERE is_territory GROUP BY 1) h_nat
                  ON h_nat.quarter_date = LEAST(date_trunc('quarter', m.reporting_period)::DATE, (SELECT max_qd FROM max_hq))
                WHERE m.zero_balance_code IS NULL
                  AND month(m.reporting_period) IN (3, 6, 9, 12)
                  AND lov.value_at_origination IS NOT NULL
            ),
            both_bases AS (
                SELECT
                    quarter_date,
                    segment,
                    'indexed'::VARCHAR AS ltv_type,
                    eff_upb,
                    100.0 * eff_upb / NULLIF(val_idx, 0.0) AS cur_ltv
                FROM base
                WHERE val_idx > 0
                UNION ALL
                SELECT
                    quarter_date,
                    segment,
                    'downward_only'::VARCHAR AS ltv_type,
                    eff_upb,
                    100.0 * eff_upb / NULLIF(LEAST(value_at_origination, val_idx), 0.0) AS cur_ltv
                FROM base
                WHERE val_idx > 0
            )
            SELECT
                quarter_date,
                segment,
                ltv_type,
                CASE
                    WHEN cur_ltv <= 50.0 THEN '<=50'
                    WHEN cur_ltv <= 55.0 THEN '50-55'
                    WHEN cur_ltv <= 60.0 THEN '55-60'
                    WHEN cur_ltv <= 70.0 THEN '60-70'
                    WHEN cur_ltv <= 80.0 THEN '70-80'
                    WHEN cur_ltv <= 90.0 THEN '80-90'
                    WHEN cur_ltv <= 100.0 THEN '90-100'
                    ELSE '>100'
                END AS ltv_band,
                count(*)::BIGINT AS loans,
                COALESCE(sum(eff_upb), 0.0) AS balance,
                COALESCE(sum(cur_ltv * eff_upb), 0.0) AS weighted_ltv_num
            FROM both_bases
            GROUP BY 1, 2, 3, 4
        """)
        if not q_df.empty:
            cltv_parts.append(q_df)
        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] scanned {quarter} ({time.time() - t0:.1f}s)", flush=True)

    cltv_df = (
        pd.concat(cltv_parts, ignore_index=True)
        .groupby(["quarter_date", "segment", "ltv_type", "ltv_band"], as_index=False)
        .sum(numeric_only=True)
    )
    cltv_df["mean_ltv_upb_weighted"] = cltv_df["weighted_ltv_num"] / cltv_df["balance"].replace(0.0, np.nan)
    c.write_df(marts, "current_ltv_mart", cltv_df, ["quarter_date", "segment", "ltv_type", "ltv_band"])

    # Chart (300 dpi): Top 15 state peak-to-trough house price drawdowns
    if not ep_df.empty:
        max_state = (
            ep_df.groupby("state", as_index=False)["fall_pct"]
            .max()
            .sort_values("fall_pct", ascending=False)
            .head(15)
        )
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.barh(max_state["state"][::-1], max_state["fall_pct"][::-1], color="#0d366b")
        ax.axvline(10.0, color="#7fb0ec", linestyle="--", label="10% SA Reval Trigger (Art 124D)")
        ax.axvline(25.0, color="#eb6834", linestyle="--", label="25% LGD Fall Floor")
        ax.axvline(40.0, color="#a82a10", linestyle=":", label="40% Reference Downturn")
        ax.set_title("Top 15 US State Peak-to-Trough House Price Falls (FHFA SA Index)")
        ax.set_xlabel("Peak-to-Trough HPI Fall (%)")
        ax.set_ylabel("State Jurisdiction")
        ax.legend()
        c.save_chart(fig, c.script_out(outputs_dir, "06_current_ltv") / "06_hpi_drawdowns.png")

    marts.execute("DROP TABLE IF EXISTS _hpi_q")
    null_hpi_valid = int(
        c.scalar(
            marts,
            "SELECT count(*) FROM loan_origination_value_mart WHERE NOT invalid_orig_ltv_flag AND (value_at_origination IS NULL OR hpi_orig IS NULL)",
        )
        or 0
    )
    check.key(marts, "loan_origination_value_mart", ["loan_id"])
    check.key(marts, "state_hpi_peaktotrough_mart", ["state", "episode_id", "peak_date", "trough_date"])
    check.key(marts, "current_ltv_mart", ["quarter_date", "segment", "ltv_type", "ltv_band"])
    check.add("every valid-LTV loan mapped cleanly to HPI origination value", null_hpi_valid == 0, f"missing={null_hpi_valid}")
    worst_row = ep_df.loc[ep_df["fall_pct"].idxmax()] if not ep_df.empty else None
    if worst_row is not None:
        print(
            f"  Worst historical state HPI drawdown: {worst_row['state']} {worst_row['fall_pct']:.1f}% "
            f"({worst_row['peak_date']} to {worst_row['trough_date']})",
            flush=True,
        )
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Indexed & downward-only current LTV and state HPI falls.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_current_ltv(marts, sp, core_files, args.outputs_dir, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
