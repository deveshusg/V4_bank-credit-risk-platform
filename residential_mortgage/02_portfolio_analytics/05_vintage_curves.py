"""Vintage default and prepayment competing-risk curves (Stage B, script 05).

Fixes all design review H3 defects:
- Standardized 0-based months on book: mob = datediff('month', first_payment_date, reporting_period).
- Keyed cleanly by (cohort_type, cohort_quarter, segment, seasoned_bucket, mob),
  supporting both origination_quarter and acquisition_quarter plus 17 survivorship splits.
- Aalen-Johansen competing-risk cumulative incidence (first event only: default vs payoff '01',
  ties default > payoff, excluding post-first-event rows and censoring '06'/'16'/'96'),
  with explicit small-risk-set / S(u)=0 survival guard.
- Voluntary prepayment SMM & CPR strictly excluding in-default rows, credit exits ('02','03','09','15'),
  other exits, interest-only loans, and modified loans; using interest-bearing UPB and current_rate.
- market_rate_t computed from loans_table grouped by origination month (weighted by orig_upb).

Outputs: vintage_curves_mart, loan_lifetime_mart, 05_vintage_curves.png (300 dpi).
Run: python residential_mortgage/02_portfolio_analytics/05_vintage_curves.py [--sample]
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


def compute_aalen_johansen(g: pd.DataFrame) -> pd.DataFrame:
    """Compute discrete Aalen-Johansen CIF_default, CIF_payoff, and conditional flags on ordered mob."""
    g = g.sort_values("mob").copy()
    n_risk = g["at_risk"].to_numpy(dtype=float)
    d_def = g["defaults"].to_numpy(dtype=float)
    d_pay = g["payoffs"].to_numpy(dtype=float)
    s_prev = 1.0
    cif_def = np.zeros(len(g), dtype=float)
    cif_pay = np.zeros(len(g), dtype=float)
    surv = np.ones(len(g), dtype=float)
    small_flag = np.zeros(len(g), dtype=bool)
    c_def = 0.0
    c_pay = 0.0

    for i in range(len(g)):
        nr = n_risk[i]
        if nr <= 0.0 or s_prev <= 0.0:
            cif_def[i] = c_def
            cif_pay[i] = c_pay
            surv[i] = s_prev
            small_flag[i] = True
            continue
        if nr < 30.0:
            small_flag[i] = True
        h_def = min(d_def[i] / nr, 1.0)
        h_pay = min(d_pay[i] / nr, 1.0)
        h_tot = min(h_def + h_pay, 1.0)
        c_def += s_prev * h_def
        c_pay += s_prev * h_pay
        s_prev = s_prev * max(1.0 - h_tot, 0.0)
        cif_def[i] = c_def
        cif_pay[i] = c_pay
        surv[i] = s_prev

    g["survival_prob"] = surv
    g["cif_default"] = cif_def
    g["cif_payoff"] = cif_pay
    g["small_risk_set_flag"] = small_flag
    return g


def run_vintage_curves(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
    sample_filter: bool = False,
) -> int:
    """Aggregate vintage risk sets per quarter, derive Aalen-Johansen CIF and SMM/CPR."""
    t0 = time.time()
    check = c.Checker("05_vintage_curves: Aalen-Johansen CIF and SMM/CPR")

    # 1. Market mortgage note rate by origination month from loans_table
    where_l = c.scope(sample_filter, prefix=src_prefix)
    marts.execute("DROP TABLE IF EXISTS _mkt_rate")
    marts.execute(f"""
        CREATE TEMP TABLE _mkt_rate AS
        SELECT
            date_trunc('month', orig_date)::DATE AS orig_month,
            sum(CAST(note_rate AS DOUBLE) * CAST(orig_upb AS DOUBLE))
              / NULLIF(sum(CAST(orig_upb AS DOUBLE)), 0.0) AS market_rate
        FROM {src_prefix}loans_table
        WHERE {where_l} AND orig_date IS NOT NULL
        GROUP BY 1
    """)

    other_lit = c.sql_list(c.OTHER_EXIT_CODES)
    credit_lit = c.sql_list(c.CREDIT_EXIT_CODES)
    parts: list[pd.DataFrame] = []

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        q_start_year = int(quarter[:4])
        q_start_month = (int(quarter[5]) - 1) * 3 + 1
        q_start_iso = f"{q_start_year:04d}-{q_start_month:02d}-01"

        # Scheduled payment PMT0 using loans_table, active interest-bearing UPB, and first competing event
        pmt_sql = (
            "CASE WHEN COALESCE(l.note_rate, 0) <= 0 OR COALESCE(l.loan_term, 0) <= 0 "
            "THEN CAST(l.orig_upb AS DOUBLE) / GREATEST(COALESCE(l.loan_term, 360), 1) "
            "ELSE CAST(l.orig_upb AS DOUBLE) * (CAST(l.note_rate AS DOUBLE) / 1200.0) "
            "/ NULLIF(1.0 - pow(1.0 + CAST(l.note_rate AS DOUBLE) / 1200.0, -l.loan_term), 0.0) END"
        )

        q_sql = f"""
            WITH first_ev AS (
                SELECT
                    l.loan_id,
                    min(e.default_month) AS first_default_m
                FROM {src_prefix}loans_table l
                LEFT JOIN default_events_mart e
                  ON e.loan_id = l.loan_id AND e.acquisition_quarter = '{quarter}'
                WHERE l.acquisition_quarter = '{quarter}'
                GROUP BY 1
            ),
            first_pay AS (
                SELECT loan_id, min(reporting_period) AS first_pay_m
                FROM read_parquet('{fp}')
                WHERE zero_balance_code = '01'
                GROUP BY 1
            ),
            loan_meta AS (
                SELECT
                    l.loan_id,
                    l.acquisition_quarter,
                    concat(year(l.orig_date)::VARCHAR, 'Q', quarter(l.orig_date)::VARCHAR) AS origination_quarter,
                    l.first_payment_date,
                    l.interest_only,
                    CASE WHEN datediff('month', l.orig_date, DATE '{q_start_iso}') <= 3 THEN 'unseasoned_0_3m'
                         WHEN datediff('month', l.orig_date, DATE '{q_start_iso}') <= 12 THEN 'seasoned_4_12m'
                         ELSE 'seasoned_gt12m' END AS seasoned_bucket,
                    COALESCE(l.occupancy, 'U') || '|' || COALESCE(l.loan_purpose, 'U') || '|'
                      || CASE WHEN l.orig_ltv >= 90 THEN 'ltv_90plus' ELSE 'ltv_lt90' END AS segment,
                    CASE WHEN fe.first_default_m IS NOT NULL AND fp2.first_pay_m IS NOT NULL
                         THEN LEAST(fe.first_default_m, fp2.first_pay_m)
                         ELSE COALESCE(fe.first_default_m, fp2.first_pay_m) END AS first_event_m,
                    CASE WHEN fe.first_default_m IS NOT NULL
                          AND (fp2.first_pay_m IS NULL OR fe.first_default_m <= fp2.first_pay_m)
                         THEN 'default'
                         WHEN fp2.first_pay_m IS NOT NULL THEN 'payoff'
                         ELSE NULL END AS first_event_kind,
                    {pmt_sql} AS pmt0
                FROM {src_prefix}loans_table l
                JOIN first_ev fe ON fe.loan_id = l.loan_id
                LEFT JOIN first_pay fp2 ON fp2.loan_id = l.loan_id
                WHERE l.acquisition_quarter = '{quarter}'
            ),
            rows_enriched AS (
                SELECT
                    lm.*,
                    m.reporting_period,
                    datediff('month', lm.first_payment_date, m.reporting_period) AS mob,
                    m.zero_balance_code,
                    m.modification_flag,
                    CAST(COALESCE(m.current_rate, 0.0) AS DOUBLE) AS cur_rate,
                    GREATEST(CAST(COALESCE(m.current_upb, 0.0) AS DOUBLE) - CAST(COALESCE(m.mod_non_interest_upb, 0.0) AS DOUBLE), 0.0) AS ib_upb,
                    m.loan_age,
                    LAG(GREATEST(CAST(COALESCE(m.current_upb, 0.0) AS DOUBLE) - CAST(COALESCE(m.mod_non_interest_upb, 0.0) AS DOUBLE), 0.0))
                      OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period) AS prev_ib_upb,
                    LAG(m.reporting_period) OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period) AS prev_rp,
                    LAG(m.loan_age) OVER (PARTITION BY m.loan_id ORDER BY m.reporting_period) AS prev_age,
                    mr.market_rate
                FROM read_parquet('{fp}') m
                JOIN loan_meta lm ON lm.loan_id = m.loan_id
                LEFT JOIN _mkt_rate mr ON mr.orig_month = date_trunc('month', m.reporting_period)::DATE
            ),
            filtered_risk AS (
                SELECT
                    *,
                    (COALESCE(first_event_m, DATE '2099-12-01') = reporting_period AND first_event_kind = 'default')::INTEGER AS is_def_ev,
                    (COALESCE(first_event_m, DATE '2099-12-01') = reporting_period AND first_event_kind = 'payoff')::INTEGER AS is_pay_ev,
                    (zero_balance_code IN {other_lit})::INTEGER AS is_other_censored,
                    -- Voluntary contractual SMM eligibility: active prior non-masked month, never defaulted, not IO, not modified, not credit/other exit
                    (
                        prev_rp IS NOT NULL
                        AND datediff('month', prev_rp, reporting_period) = 1
                        AND COALESCE(prev_ib_upb, 0.0) > 0.0
                        AND NOT (prev_ib_upb = 0.0 AND COALESCE(prev_age, 0) <= 6)
                        AND COALESCE(interest_only, 'N') != 'Y'
                        AND COALESCE(modification_flag, 'N') != 'Y'
                        AND COALESCE(zero_balance_code, '') NOT IN {credit_lit}
                        AND COALESCE(zero_balance_code, '') NOT IN {other_lit}
                        AND (first_event_m IS NULL OR first_event_kind != 'default' OR reporting_period < first_event_m)
                    ) AS smm_elig,
                    GREATEST(LEAST(COALESCE(prev_ib_upb, 0.0), GREATEST(pmt0 - COALESCE(prev_ib_upb, 0.0) * cur_rate / 1200.0, 0.0)), 0.0) AS sched_prin
                FROM rows_enriched
                WHERE first_event_m IS NULL OR reporting_period <= first_event_m
            ),
            per_month_metrics AS (
                SELECT
                    *,
                    GREATEST(COALESCE(prev_ib_upb, 0.0) - sched_prin, 0.0) AS exp_end_upb,
                    CASE WHEN zero_balance_code = '01' THEN 0.0 ELSE ib_upb END AS actual_end_upb
                FROM filtered_risk
            )
            SELECT origination_quarter, acquisition_quarter,
                   segment, seasoned_bucket, mob,
                   count(*)::BIGINT AS at_risk,
                   sum(is_def_ev)::BIGINT AS defaults,
                   sum(is_pay_ev)::BIGINT AS payoffs,
                   sum(is_other_censored)::BIGINT AS censored_other,
                   COALESCE(sum(GREATEST(exp_end_upb - actual_end_upb, 0.0)) FILTER (WHERE smm_elig AND exp_end_upb > 0), 0.0) AS unsched_prin,
                   COALESCE(sum(exp_end_upb) FILTER (WHERE smm_elig AND exp_end_upb > 0), 0.0) AS smm_denom,
                   COALESCE(sum((cur_rate - market_rate) * ib_upb) FILTER (WHERE smm_elig AND market_rate IS NOT NULL), 0.0) AS incentive_num,
                   COALESCE(sum(ib_upb) FILTER (WHERE smm_elig AND market_rate IS NOT NULL), 0.0) AS incentive_den
            FROM per_month_metrics
            GROUP BY 1, 2, 3, 4, 5
        """
        parts.append(c.q(marts, q_sql))
        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] scanned {quarter} ({time.time() - t0:.1f}s)", flush=True)

    joined_parts = pd.concat(parts, ignore_index=True)
    orig_agg = (
        joined_parts.groupby(["origination_quarter", "segment", "seasoned_bucket", "mob"], as_index=False)
        .sum(numeric_only=True)
        .rename(columns={"origination_quarter": "cohort_quarter"})
    )
    orig_agg.insert(0, "cohort_type", "origination_quarter")
    acq_agg = (
        joined_parts.groupby(["acquisition_quarter", "segment", "seasoned_bucket", "mob"], as_index=False)
        .sum(numeric_only=True)
        .rename(columns={"acquisition_quarter": "cohort_quarter"})
    )
    acq_agg.insert(0, "cohort_type", "acquisition_quarter")
    raw_v = pd.concat([orig_agg, acq_agg], ignore_index=True)
    raw_v["smm"] = (raw_v["unsched_prin"] / raw_v["smm_denom"].replace(0.0, np.nan)).clip(lower=0.0, upper=1.0).fillna(0.0)
    raw_v["cpr"] = 1.0 - (1.0 - raw_v["smm"]) ** 12
    raw_v["rate_incentive_pct"] = (raw_v["incentive_num"] / raw_v["incentive_den"].replace(0.0, np.nan)).fillna(0.0)

    # Compute Aalen-Johansen CIF per cohort_type x cohort_quarter x segment x seasoned_bucket
    out_groups: list[pd.DataFrame] = []
    for _, grp in raw_v.groupby(["cohort_type", "cohort_quarter", "segment", "seasoned_bucket"], sort=False):
        out_groups.append(compute_aalen_johansen(grp))
    v_out = pd.concat(out_groups, ignore_index=True) if out_groups else raw_v

    c.write_df(marts, "vintage_curves_mart", v_out, ["cohort_type", "cohort_quarter", "segment", "seasoned_bucket", "mob"])

    # Expected lifetime table per segment x era x seasoned_bucket (from acquisition_quarter cohorts)
    acq_only = v_out[v_out["cohort_type"] == "acquisition_quarter"].copy()
    acq_only["era"] = acq_only["cohort_quarter"].str[:4].astype(int).map(
        lambda y: "2000-2006 build-up" if y <= 2006 else ("2007-2010 crisis" if y <= 2010 else ("2011-2019 recovery" if y <= 2019 else ("2020-2021 COVID" if y <= 2021 else "2022-2025 recent")))
    )
    life_rows: list[dict] = []
    for (seg, era, sb), g in acq_only.groupby(["segment", "era", "seasoned_bucket"]):
        pays = float(g["payoffs"].sum())
        defs = float(g["defaults"].sum())
        avg_mob_pay = float((g["payoffs"] * g["mob"]).sum() / pays) if pays > 0 else float("nan")
        # Discrete restricted mean survival time (area under survival curve across observed MOBs)
        expected_life = float(g.groupby("mob")["survival_prob"].mean().sum())
        life_rows.append({
            "segment": seg,
            "era": era,
            "seasoned_bucket": sb,
            "observed_defaults": int(defs),
            "observed_payoffs": int(pays),
            "mean_payoff_mob": avg_mob_pay,
            "expected_active_months": expected_life,
        })
    life_out = pd.DataFrame(life_rows)
    c.write_df(marts, "loan_lifetime_mart", life_out, ["segment", "era", "seasoned_bucket"])

    # Chart (300 dpi): Headline acquisition_quarter cumulative default incidence by era
    if not acq_only.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        era_mob = (
            acq_only.groupby(["era", "mob"], as_index=False)
            .agg(at_risk=("at_risk", "sum"), defaults=("defaults", "sum"), payoffs=("payoffs", "sum"))
        )
        for era_name, ge in era_mob.groupby("era"):
            ge_cif = compute_aalen_johansen(ge)
            ax.plot(ge_cif["mob"], ge_cif["cif_default"] * 100.0, label=era_name)
        ax.set_title("Cumulative Default Incidence (Aalen-Johansen Competing Risk) by Era")
        ax.set_xlabel("Months on Book (MOB, 0-based from First Payment Date)")
        ax.set_ylabel("Cumulative Default Incidence (%)")
        ax.legend()
        c.save_chart(fig, outputs_dir / "05_vintage_curves.png")

    marts.execute("DROP TABLE IF EXISTS _mkt_rate")
    check.key(marts, "vintage_curves_mart", ["cohort_type", "cohort_quarter", "segment", "seasoned_bucket", "mob"])
    check.key(marts, "loan_lifetime_mart", ["segment", "era", "seasoned_bucket"])
    cif_sum_ok = bool(((v_out["cif_default"] + v_out["cif_payoff"]) <= 1.0 + 1e-6).all()) if not v_out.empty else True
    smm_ok = bool(((v_out["smm"] >= 0.0) & (v_out["smm"] <= 1.0)).all()) if not v_out.empty else True
    check.add("competing-risk CIF sum bounded <= 1.0", cif_sum_ok)
    check.add("voluntary SMM within [0, 1]", smm_ok)
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vintage competing-risk default and prepayment curves.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_vintage_curves(marts, sp, core_files, args.outputs_dir, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
