"""Arrears roll rates, Markov absorption, and 30-day IFRS 9 backstop (Stage B, script 03).

Fixes all design review H2 defects:
- Builds monthly states using COVID-adjusted adj_dpd (so COVID-held >=3m rows
  map cleanly to their held bucket, not an undefined state).
- Requires contiguous monthly pairs (datediff('month', prev_rp, rp) = 1).
- Excludes transitions where EITHER from_state or to_state is Unknown ('XX'),
  reporting excluded counts and balances cleanly.
- Weights balance transitions by month-(t-1) UPB (substituting scheduled balance
  for early 0.00 masked rows) so transitions into exits carry real exposure weight.
- Computes 6/12/24/36-month Markov projections, BOTH 4x4 terminal absorption
  and 3x3 time-to-default via (I - Q)^{-1} -> roll_absorption_mart, and
  capped (t0 <= 2024-12-01) IFRS 9 30-day backstop conversion vs never-behind mob 6.

Run: python residential_mortgage/02_portfolio_analytics/03_roll_rates.py [--sample]
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

ALL_STATES = [
    "Current",
    "1m behind",
    "2m behind",
    "In default",
    "Paid off",
    "Credit exit",
    "Other exit",
]
EXIT_STATES = {"Paid off", "Credit exit", "Other exit"}


def covid_adjust_quarter_df(marts: object, quarter_parquet: Path) -> str:
    """Create TEMP TABLE _q_covid_adj (loan_id, reporting_period, adj_dpd) for relief loans in quarter."""
    fp = str(quarter_parquet).replace("\\", "/")
    plans_lit = c.sql_list(c.ACTIVE_RELIEF_PLANS)
    marts.execute("DROP TABLE IF EXISTS _q_covid_adj")
    relief_df = c.q(marts, f"""
        WITH rel_ids AS (
            SELECT DISTINCT loan_id
            FROM read_parquet('{fp}')
            WHERE borrower_assistance_plan IN {plans_lit}
              AND reporting_period BETWEEN DATE '2020-03-01' AND DATE '2021-07-01'
        )
        SELECT m.loan_id,
               m.reporting_period,
               strftime(m.reporting_period, '%Y-%m') AS ym,
               m.delinquency_months,
               m.borrower_assistance_plan
        FROM read_parquet('{fp}') m
        JOIN rel_ids r ON r.loan_id = m.loan_id
        ORDER BY m.loan_id, m.reporting_period
    """)
    if relief_df.empty:
        marts.execute("CREATE TEMP TABLE _q_covid_adj (loan_id VARCHAR, reporting_period DATE, adj_dpd INTEGER)")
        return "_q_covid_adj"

    rows: list[tuple] = []
    for lid, g in relief_df.groupby("loan_id", sort=False):
        mb = [None if pd.isna(v) else int(v) for v in g["delinquency_months"]]
        pls = ["" if pd.isna(v) else str(v) for v in g["borrower_assistance_plan"]]
        yms = g["ym"].tolist()
        adj, _ = c.covid_hold_months(mb, pls, yms)
        rps = g["reporting_period"].tolist()
        for rp, val in zip(rps, adj):
            rows.append((lid, rp, val))
    adj_df = pd.DataFrame(rows, columns=["loan_id", "reporting_period", "adj_dpd"])
    marts.register("_adj_tmp", adj_df)
    try:
        marts.execute("CREATE TEMP TABLE _q_covid_adj AS SELECT loan_id, CAST(reporting_period AS DATE) AS reporting_period, CAST(adj_dpd AS INTEGER) AS adj_dpd FROM _adj_tmp").fetchall()
    finally:
        marts.unregister("_adj_tmp")
    return "_q_covid_adj"


def run_roll_rates(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
) -> int:
    """Compute era transition matrices, projections, absorption times, and 30-day evidence."""
    t0 = time.time()
    check = c.Checker("03_roll_rates: arrears transitions, absorption and 30-day evidence")

    tx_parts: list[pd.DataFrame] = []
    xx_parts: list[pd.DataFrame] = []
    ev_acc = {
        ("1m_first", "12m"): [0, 0],
        ("1m_first", "lifetime"): [0, 0],
        ("2m_first", "12m"): [0, 0],
        ("2m_first", "lifetime"): [0, 0],
        ("never_behind_mob6", "12m"): [0, 0],
        ("never_behind_mob6", "lifetime"): [0, 0],
    }

    sched_sql = c.scheduled_upb_sql(
        "lt.orig_upb",
        "lt.note_rate",
        "lt.loan_term",
        "datediff('month', lt.first_payment_date, m.reporting_period)",
    )
    credit_lit = c.sql_list(c.CREDIT_EXIT_CODES)
    other_lit = c.sql_list(c.OTHER_EXIT_CODES)

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        adj_tbl = covid_adjust_quarter_df(marts, f)

        base_cte = f"""
            WITH states AS (
                SELECT
                    m.loan_id,
                    m.reporting_period,
                    {c.era_case('m.reporting_period')} AS era,
                    CASE
                        WHEN m.zero_balance_code = '01' THEN 'Paid off'
                        WHEN m.zero_balance_code IN {credit_lit} THEN 'Credit exit'
                        WHEN m.zero_balance_code IN {other_lit} THEN 'Other exit'
                        WHEN COALESCE(ds.in_default, FALSE) THEN 'In default'
                        WHEN m.is_dpd_unknown THEN 'Unknown'
                        WHEN COALESCE(ca.adj_dpd, m.delinquency_months) IS NULL THEN 'Unknown'
                        WHEN COALESCE(ca.adj_dpd, m.delinquency_months) = 0 THEN 'Current'
                        WHEN COALESCE(ca.adj_dpd, m.delinquency_months) = 1 THEN '1m behind'
                        WHEN COALESCE(ca.adj_dpd, m.delinquency_months) = 2 THEN '2m behind'
                        ELSE 'In default'
                    END AS state,
                    CASE
                        WHEN m.zero_balance_code IS NOT NULL THEN 0.0
                        WHEN COALESCE(CAST(m.current_upb AS DOUBLE), 0.0) = 0.0
                             AND COALESCE(m.loan_age, 0) <= 6 THEN {sched_sql}
                        ELSE CAST(m.current_upb AS DOUBLE)
                    END AS eff_upb,
                    COALESCE(ca.adj_dpd, m.delinquency_months) AS adj_dpd,
                    COALESCE(ds.in_default, FALSE) AS in_default,
                    datediff('month', lt.first_payment_date, m.reporting_period) AS mob
                FROM read_parquet('{fp}') m
                JOIN {src_prefix}loans_table lt
                  ON lt.loan_id = m.loan_id AND lt.acquisition_quarter = '{quarter}'
                LEFT JOIN default_status_monthly ds
                  ON ds.loan_id = m.loan_id AND ds.reporting_period = m.reporting_period
                 AND ds.acquisition_quarter = '{quarter}'
                LEFT JOIN {adj_tbl} ca
                  ON ca.loan_id = m.loan_id AND ca.reporting_period = m.reporting_period
            ),
            pairs AS (
                SELECT
                    era,
                    LAG(state) OVER (PARTITION BY loan_id ORDER BY reporting_period) AS from_state,
                    state AS to_state,
                    LAG(reporting_period) OVER (PARTITION BY loan_id ORDER BY reporting_period) AS prev_rp,
                    reporting_period,
                    LAG(eff_upb) OVER (PARTITION BY loan_id ORDER BY reporting_period) AS prev_upb
                FROM states
            )
        """
        all_q = c.q(marts, base_cte + """
            SELECT
                era,
                from_state,
                to_state,
                count(*)::BIGINT AS cnt,
                COALESCE(sum(prev_upb), 0.0) AS bal_prev_upb
            FROM pairs
            WHERE prev_rp IS NOT NULL
              AND datediff('month', prev_rp, reporting_period) = 1
            GROUP BY 1, 2, 3
        """)
        is_xx = (all_q["from_state"] == "Unknown") | (all_q["to_state"] == "Unknown")
        tx_parts.append(all_q[~is_xx])
        if is_xx.any():
            xx_q = (
                all_q[is_xx]
                .groupby("era", as_index=False)[["cnt", "bal_prev_upb"]]
                .sum()
                .rename(columns={"cnt": "xx_excluded_rows", "bal_prev_upb": "xx_excluded_upb"})
            )
            xx_parts.append(xx_q)

        # 30-day IFRS 9 backstop evidence per loan in quarter
        ev_q = c.q(marts, f"""
            WITH st AS (
                SELECT
                    m.loan_id,
                    m.reporting_period,
                    m.is_dpd_unknown,
                    COALESCE(ca.adj_dpd, m.delinquency_months) AS adj_dpd,
                    COALESCE(ds.in_default, FALSE) AS in_default,
                    datediff('month', lt.first_payment_date, m.reporting_period) AS mob,
                    max(CASE WHEN COALESCE(ca.adj_dpd, m.delinquency_months) >= 1 THEN 1 ELSE 0 END)
                      OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ever_behind,
                    max(CASE WHEN ds.in_default THEN 1 ELSE 0 END)
                      OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ever_def_so_far
                FROM read_parquet('{fp}') m
                JOIN {src_prefix}loans_table lt
                  ON lt.loan_id = m.loan_id AND lt.acquisition_quarter = '{quarter}'
                LEFT JOIN default_status_monthly ds
                  ON ds.loan_id = m.loan_id AND ds.reporting_period = m.reporting_period
                 AND ds.acquisition_quarter = '{quarter}'
                LEFT JOIN {adj_tbl} ca
                  ON ca.loan_id = m.loan_id AND ca.reporting_period = m.reporting_period
            ),
            anchors AS (
                SELECT
                    '1m_first'::VARCHAR AS band,
                    loan_id,
                    min(reporting_period) AS t0
                FROM st
                WHERE NOT is_dpd_unknown AND adj_dpd = 1 AND ever_def_so_far = 0
                GROUP BY loan_id
                UNION ALL
                SELECT
                    '2m_first'::VARCHAR AS band,
                    loan_id,
                    min(reporting_period) AS t0
                FROM st
                WHERE NOT is_dpd_unknown AND adj_dpd = 2 AND ever_def_so_far = 0
                GROUP BY loan_id
                UNION ALL
                SELECT
                    'never_behind_mob6'::VARCHAR AS band,
                    loan_id,
                    min(reporting_period) AS t0
                FROM st
                WHERE mob = {c.SEASONING_MIN_MOB} AND NOT is_dpd_unknown AND adj_dpd = 0 AND ever_behind = 0 AND ever_def_so_far = 0
                GROUP BY loan_id
            ),
            ev_q AS (
                SELECT loan_id, default_month
                FROM default_events_mart
                WHERE acquisition_quarter = '{quarter}'
            )
            SELECT
                a.band,
                count(*) FILTER (WHERE a.t0 <= DATE '2024-12-01')::BIGINT AS n_12m,
                count(*) FILTER (
                    WHERE a.t0 <= DATE '2024-12-01' AND EXISTS (
                        SELECT 1 FROM ev_q e
                        WHERE e.loan_id = a.loan_id
                          AND e.default_month > a.t0
                          AND e.default_month <= a.t0 + INTERVAL 12 MONTH
                    )
                )::BIGINT AS def_12m,
                count(*)::BIGINT AS n_life,
                count(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1 FROM ev_q e
                        WHERE e.loan_id = a.loan_id AND e.default_month > a.t0
                    )
                )::BIGINT AS def_life
            FROM anchors a
            GROUP BY 1
        """)
        for _, r in ev_q.iterrows():
            band = str(r["band"])
            ev_acc[(band, "12m")][0] += int(r["def_12m"])
            ev_acc[(band, "12m")][1] += int(r["n_12m"])
            ev_acc[(band, "lifetime")][0] += int(r["def_life"])
            ev_acc[(band, "lifetime")][1] += int(r["n_life"])

        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] scanned {quarter} ({time.time() - t0:.1f}s)", flush=True)

    marts.execute("DROP TABLE IF EXISTS _q_covid_adj")

    tx_df = (
        pd.concat(tx_parts, ignore_index=True)
        .groupby(["era", "from_state", "to_state"], as_index=False)
        .sum(numeric_only=True)
    )
    xx_df = (
        pd.concat(xx_parts, ignore_index=True)
        .groupby("era", as_index=False)
        .sum(numeric_only=True)
        if xx_parts
        else pd.DataFrame(columns=["era", "xx_excluded_rows", "xx_excluded_upb"])
    )
    xx_map = xx_df.set_index("era").to_dict(orient="index")

    # Build long roll_rates_mart for both count and balance weights
    rr_rows: list[dict] = []
    for era, g in tx_df.groupby("era"):
        xx_info = xx_map.get(era, {"xx_excluded_rows": 0, "xx_excluded_upb": 0.0})
        for wt_name, val_col in (("count", "cnt"), ("balance", "bal_prev_upb")):
            row_tot = g.groupby("from_state")[val_col].transform("sum")
            for idx_r, r in g.iterrows():
                denom = float(row_tot.loc[idx_r])
                val = float(r[val_col])
                rr_rows.append({
                    "era": era,
                    "weight_type": wt_name,
                    "from_state": r["from_state"],
                    "to_state": r["to_state"],
                    "transitions": val,
                    "transition_rate": (val / denom) if denom > 0 else 0.0,
                    "xx_excluded_rows": int(xx_info["xx_excluded_rows"]),
                    "xx_excluded_upb": float(xx_info["xx_excluded_upb"]),
                })
    rr_out = pd.DataFrame(rr_rows)
    c.write_df(marts, "roll_rates_mart", rr_out, ["era", "weight_type", "from_state", "to_state"])

    # Markov projections (6/12/24/36m) and expected months to absorption (4x4 terminal & 3x3 default)
    proj_rows: list[dict] = []
    abs_rows: list[dict] = []
    idx_map = {s: i for i, s in enumerate(ALL_STATES)}
    for era, g in tx_df.groupby("era"):
        piv = g.pivot_table(index="from_state", columns="to_state", values="cnt", aggfunc="sum", fill_value=0)
        piv = piv.reindex(index=ALL_STATES, columns=ALL_STATES, fill_value=0).astype(float)
        row_sums = piv.sum(axis=1)
        p_mat = piv.div(row_sums.replace(0.0, 1.0), axis=0).to_numpy(dtype=float, copy=True)
        for i, rs in enumerate(row_sums.tolist()):
            if rs <= 0.0:
                p_mat[i, i] = 1.0
        # Absorbing exit states
        for es in EXIT_STATES:
            ei = idx_map[es]
            p_mat[ei, :] = 0.0
            p_mat[ei, ei] = 1.0

        for horizon in c.windows.PROJECTION_HORIZONS_MONTHS:
            ph = np.linalg.matrix_power(p_mat, int(horizon))
            for i, fs in enumerate(ALL_STATES):
                for j, ts in enumerate(ALL_STATES):
                    proj_rows.append({
                        "era": era,
                        "from_state": fs,
                        "horizon_months": int(horizon),
                        "to_state": ts,
                        "prob": float(ph[i, j]),
                    })

        # 4x4 terminal exit absorption over transient [Current, 1m, 2m, In default]
        t4 = ["Current", "1m behind", "2m behind", "In default"]
        q4 = p_mat[np.ix_([idx_map[s] for s in t4], [idx_map[s] for s in t4])]
        try:
            n4 = np.linalg.solve(np.eye(4) - q4, np.ones(4))
        except np.linalg.LinAlgError:
            n4 = np.full(4, float("nan"))
        for fs, val in zip(t4, n4):
            abs_rows.append({"era": era, "target_scope": "terminal_exit_4x4", "from_state": fs, "expected_months": float(val)})

        # 3x3 time to first default (or exit before default) treating In default as absorbing
        t3 = ["Current", "1m behind", "2m behind"]
        q3 = p_mat[np.ix_([idx_map[s] for s in t3], [idx_map[s] for s in t3])]
        try:
            n3 = np.linalg.solve(np.eye(3) - q3, np.ones(3))
        except np.linalg.LinAlgError:
            n3 = np.full(3, float("nan"))
        for fs, val in zip(t3, n3):
            abs_rows.append({"era": era, "target_scope": "to_default_3x3", "from_state": fs, "expected_months": float(val)})

    proj_out = pd.DataFrame(proj_rows)
    abs_out = pd.DataFrame(abs_rows)
    c.write_df(marts, "roll_projection_mart", proj_out, ["era", "from_state", "horizon_months", "to_state"])
    c.write_df(marts, "roll_absorption_mart", abs_out, ["era", "target_scope", "from_state"])

    ev_rows: list[dict] = []
    for (band, hw), (defs, tot) in sorted(ev_acc.items()):
        pt, lo, hi = c.wilson_ci(defs, tot)
        ev_rows.append({
            "first_arrears_band": band,
            "horizon_window": hw,
            "loans": int(tot),
            "defaulted_loans": int(defs),
            "default_rate": float(pt),
            "ci95_low": float(lo),
            "ci95_high": float(hi),
        })
    ev_out = pd.DataFrame(ev_rows)
    c.write_df(marts, "roll_30day_evidence_mart", ev_out, ["first_arrears_band", "horizon_window"])

    # Chart (300 dpi): 30-day IFRS 9 backstop conversion
    sub12 = ev_out[ev_out["horizon_window"] == "12m"].copy()
    if not sub12.empty:
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        x = np.arange(len(sub12))
        rates_pct = sub12["default_rate"] * 100.0
        err_lo = (sub12["default_rate"] - sub12["ci95_low"]) * 100.0
        err_hi = (sub12["ci95_high"] - sub12["default_rate"]) * 100.0
        ax.bar(x, rates_pct, color="#2a78d6", width=0.55)
        ax.errorbar(x, rates_pct, yerr=[err_lo, err_hi], fmt="none", ecolor="black", capsize=4)
        ax.set_xticks(x)
        ax.set_xticklabels(sub12["first_arrears_band"])
        ax.set_title("IFRS 9 30-Day Backstop: 12-Month Default Rate by First Arrears State")
        ax.set_xlabel("Cohort Entry State (Performing Loans, t0 <= 2024-12)")
        ax.set_ylabel("12-Month Default Rate (%) with 95% Wilson CI")
        c.save_chart(fig, outputs_dir / "03_30day_backstop_conversion.png")

    bad_prob = int(((proj_out["prob"] < -1e-9) | (proj_out["prob"] > 1.0 + 1e-9)).sum())
    row_sum_err = float(
        proj_out.groupby(["era", "from_state", "horizon_months"])["prob"].sum().sub(1.0).abs().max()
    ) if not proj_out.empty else 0.0
    check.key(marts, "roll_rates_mart", ["era", "weight_type", "from_state", "to_state"])
    check.key(marts, "roll_projection_mart", ["era", "from_state", "horizon_months", "to_state"])
    check.key(marts, "roll_absorption_mart", ["era", "target_scope", "from_state"])
    check.key(marts, "roll_30day_evidence_mart", ["first_arrears_band", "horizon_window"])
    check.add("Markov projection probabilities bounded in [0, 1]", bad_prob == 0, f"violations={bad_prob}")
    check.add("Markov projection row sums equal 1.0", row_sum_err < 1e-6, f"max_err={row_sum_err:.2e}")

    print("  30-day IFRS 9 backstop evidence:")
    for _, r in ev_out.iterrows():
        print(
            f"    {r['first_arrears_band']:18s} {r['horizon_window']:8s}: "
            f"{r['default_rate']:.2%} [95% CI {r['ci95_low']:.2%}-{r['ci95_high']:.2%}] "
            f"({int(r['defaulted_loans']):,}/{int(r['loans']):,})",
            flush=True,
        )
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arrears roll rates, absorption and 30-day backstop.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_roll_rates(marts, sp, core_files, args.outputs_dir)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
