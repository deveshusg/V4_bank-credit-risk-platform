"""Stock-and-flow balance audit and plausibility checks (Stage A, script 01).

Replaces broken Phase 1 01_data_audit.py and absorbs remaining checks from
retired 01b_data_plausibility.py (D2-B / D-031):
1. Consistent active-loan count tie-out (open_active excludes exit rows,
   bridging same-month entry+exits, internal gaps, and early no-exit stops).
2. Balance roll-forward on active rows avoiding payoff total_principal
   double-counting, treating mod_non_interest_upb as stock (memo change only),
   tracking masked 0.00 early unmasking jumps separately, and keeping
   unexplained residuals explicit (never NaN).
3. Continuity and plausibility mart (data_plausibility_mart): duplicate
   loan-months, gap loans, early no-exits, servicer transfers, range checks,
   yearly field fill rates, and unexplained arrears resets (re-aging).

Run: python residential_mortgage/02_portfolio_analytics/scripts/01_data_audit.py [--full]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd

# Make shared Module 2 helpers importable
# Resolve this script's folder and prepend it to Python's module search path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


# Build the three per-quarter SQL queries (monthly flows, yearly coverage, and loan lifespan checks)
# Wrap one core Parquet file in a shared prior/next-month window CTE and return three SELECT strings
def audit_quarter_sql(parquet_path: Path, dataset_end_iso: str) -> tuple[str, str, str]:
    """Return SQL queries for monthly flow, yearly plausibility, and loan-level flags on one quarter."""
    fp = str(parquet_path).replace("\\", "/")
    # Line up each loan-month with its prior and next month
    # Partition by loan_id ordered by reporting_period using DuckDB LAG/LEAD window functions
    cte = f"""
        WITH ordered AS (
            SELECT
                loan_id,
                reporting_period,
                servicer_name,
                current_rate,
                CAST(current_upb AS DOUBLE) AS current_upb,
                loan_age,
                CAST(total_principal AS DOUBLE) AS total_principal,
                delinquency_months,
                modification_flag,
                zero_balance_code,
                CAST(upb_at_removal AS DOUBLE) AS upb_at_removal,
                alt_delinquency_resolution,
                borrower_assistance_plan,
                CAST(mod_non_interest_upb AS DOUBLE) AS mod_non_interest_upb,
                CAST(principal_forgiveness AS DOUBLE) AS principal_forgiveness,
                CAST(foreclosure_writeoff AS DOUBLE) AS foreclosure_writeoff,
                LAG(reporting_period) OVER w AS prev_rp,
                LEAD(reporting_period) OVER w AS next_rp,
                LAG(CAST(current_upb AS DOUBLE)) OVER w AS prev_upb,
                LAG(loan_age) OVER w AS prev_loan_age,
                LAG(zero_balance_code) OVER w AS prev_zbc,
                LAG(delinquency_months) OVER w AS prev_dpd,
                LAG(CAST(mod_non_interest_upb AS DOUBLE)) OVER w AS prev_mod_non_int
            FROM read_parquet('{fp}')
            WINDOW w AS (PARTITION BY loan_id ORDER BY reporting_period)
        ),
        classified AS (
            -- Tag each row's transition role (entry, exit, smooth continuation, gap, or early unmasking)
            -- Compare reporting_period gaps via datediff('month', ...) and check zero_balance_code / prev_upb
            SELECT *,
                (prev_rp IS NULL) AS is_first,
                (next_rp IS NULL) AS is_last,
                (prev_rp IS NOT NULL AND datediff('month', prev_rp, reporting_period) = 1) AS is_contig_prev,
                (next_rp IS NOT NULL AND datediff('month', reporting_period, next_rp) = 1) AS is_contig_next,
                (prev_rp IS NOT NULL AND datediff('month', prev_rp, reporting_period) > 1) AS is_gap_return,
                (next_rp IS NOT NULL AND datediff('month', reporting_period, next_rp) > 1) AS is_gap_drop,
                (prev_rp IS NOT NULL AND datediff('month', prev_rp, reporting_period) = 1
                 AND zero_balance_code IS NULL AND prev_zbc IS NULL
                 AND COALESCE(prev_upb, 0.0) = 0.0 AND COALESCE(prev_loan_age, 0) <= 6
                 AND COALESCE(current_upb, 0.0) > 0.0) AS is_unmask_jump
            FROM ordered
        )
    """
    monthly_sql = cte + f"""
        -- Aggregate same-month active loan counts, inflows, principal repayments, capitalisations, and exits
        -- Group classified rows by reporting_period using FILTER clauses (counting cap_added_upb only when total_principal is blank)
        , same_month_events AS (
            SELECT
                reporting_period,
                count(*) FILTER (WHERE zero_balance_code IS NULL)::BIGINT AS open_loans,
                count(*) FILTER (WHERE is_first AND zero_balance_code IS NULL)::BIGINT AS new_loans_active,
                count(*) FILTER (WHERE is_first AND zero_balance_code IS NOT NULL)::BIGINT AS same_month_entry_exit,
                count(*) FILTER (WHERE NOT is_first AND zero_balance_code IS NOT NULL AND is_contig_prev AND prev_zbc IS NULL)::BIGINT AS exits_from_prior,
                count(*) FILTER (WHERE NOT is_first AND zero_balance_code IS NULL AND is_gap_return)::BIGINT AS gap_reappear,
                count(*) FILTER (WHERE NOT is_first AND zero_balance_code IS NOT NULL AND (is_gap_return OR NOT is_contig_prev))::BIGINT AS gap_or_noncontig_exit,
                COALESCE(sum(current_upb) FILTER (WHERE zero_balance_code IS NULL), 0.0) AS closing_upb,
                COALESCE(sum(current_upb) FILTER (WHERE is_first AND zero_balance_code IS NULL), 0.0) AS new_active_upb,
                COALESCE(sum(current_upb) FILTER (WHERE NOT is_first AND zero_balance_code IS NULL AND is_gap_return), 0.0) AS gap_upb_in,
                COALESCE(sum(current_upb) FILTER (WHERE is_unmask_jump), 0.0) AS unmask_jump_upb,
                COALESCE(sum(total_principal) FILTER (
                    WHERE is_contig_prev AND zero_balance_code IS NULL AND prev_zbc IS NULL
                      AND total_principal IS NOT NULL AND COALESCE(prev_upb, 0.0) > 0.0 AND NOT is_unmask_jump
                ), 0.0) AS reported_principal_paid_upb,
                COALESCE(sum(GREATEST(prev_upb - COALESCE(current_upb, 0.0), 0.0)) FILTER (
                    WHERE is_contig_prev AND zero_balance_code IS NULL AND prev_zbc IS NULL
                      AND total_principal IS NULL AND COALESCE(prev_upb, 0.0) > 0.0 AND NOT is_unmask_jump
                ), 0.0) AS inferred_principal_upb,
                COALESCE(sum(GREATEST(COALESCE(current_upb, 0.0) - prev_upb, 0.0)) FILTER (
                    WHERE is_contig_prev AND zero_balance_code IS NULL AND prev_zbc IS NULL
                      AND total_principal IS NULL AND NOT is_unmask_jump
                ), 0.0) AS cap_added_upb,
                COALESCE(sum(COALESCE(mod_non_interest_upb, 0.0) - COALESCE(prev_mod_non_int, 0.0)) FILTER (
                    WHERE is_contig_prev AND zero_balance_code IS NULL
                ), 0.0) AS delta_mod_non_interest_upb,
                COALESCE(sum(upb_at_removal) FILTER (WHERE NOT is_first AND is_contig_prev AND prev_zbc IS NULL AND zero_balance_code = '01'), 0.0) AS payoff_upb,
                COALESCE(sum(upb_at_removal) FILTER (WHERE NOT is_first AND is_contig_prev AND prev_zbc IS NULL AND zero_balance_code IN ('02','03','09','15')), 0.0) AS credit_exit_upb,
                COALESCE(sum(upb_at_removal) FILTER (WHERE NOT is_first AND is_contig_prev AND prev_zbc IS NULL AND zero_balance_code IN ('06','16','96')), 0.0) AS other_exit_upb,
                COALESCE(sum(COALESCE(prev_upb, 0.0) - COALESCE(upb_at_removal, 0.0)) FILTER (WHERE NOT is_first AND is_contig_prev AND prev_zbc IS NULL AND zero_balance_code IS NOT NULL), 0.0) AS exit_prev_upb_diff,
                COALESCE(sum(principal_forgiveness) FILTER (WHERE zero_balance_code IS NULL), 0.0) AS active_forgiven_upb,
                COALESCE(sum(foreclosure_writeoff) FILTER (WHERE zero_balance_code IS NULL), 0.0) AS active_writeoff_upb,
                COALESCE(sum(foreclosure_writeoff) FILTER (WHERE zero_balance_code IS NOT NULL), 0.0) AS exit_writeoff_upb,
                count(*) FILTER (WHERE COALESCE(current_upb, -1.0) = 0.0 AND zero_balance_code IS NULL AND COALESCE(loan_age, 0) <= 6)::BIGINT AS masked_early_rows
            FROM classified
            GROUP BY reporting_period
        ),
        -- Attribute mid-life disappearances and early no-exit stops to the next reporting month
        -- Shift reporting_period forward by INTERVAL 1 MONTH for rows where the loan drops out without an exit code
        next_month_drops AS (
            SELECT
                CAST(reporting_period + INTERVAL 1 MONTH AS DATE) AS reporting_period,
                count(*) FILTER (WHERE zero_balance_code IS NULL AND is_gap_drop)::BIGINT AS gap_disappear,
                COALESCE(sum(current_upb) FILTER (WHERE zero_balance_code IS NULL AND is_gap_drop), 0.0) AS gap_upb_out,
                count(*) FILTER (WHERE zero_balance_code IS NULL AND is_last AND reporting_period < DATE '{dataset_end_iso}')::BIGINT AS early_noexit,
                COALESCE(sum(current_upb) FILTER (WHERE zero_balance_code IS NULL AND is_last AND reporting_period < DATE '{dataset_end_iso}'), 0.0) AS early_noexit_upb
            FROM classified
            GROUP BY 1
        )
        -- Align same-month events with next-month drops into one monthly ledger row
        -- Full-outer-join both CTEs on reporting_period and zero-fill missing counts or balances with COALESCE
        SELECT
            COALESCE(s.reporting_period, n.reporting_period) AS reporting_period,
            COALESCE(s.open_loans, 0)::BIGINT AS open_loans,
            COALESCE(s.new_loans_active, 0)::BIGINT AS new_loans_active,
            COALESCE(s.same_month_entry_exit, 0)::BIGINT AS same_month_entry_exit,
            COALESCE(s.exits_from_prior, 0)::BIGINT AS exits_from_prior,
            COALESCE(s.gap_reappear, 0)::BIGINT AS gap_reappear,
            COALESCE(n.gap_disappear, 0)::BIGINT AS gap_disappear,
            COALESCE(n.early_noexit, 0)::BIGINT AS early_noexit,
            COALESCE(s.gap_or_noncontig_exit, 0)::BIGINT AS gap_or_noncontig_exit,
            COALESCE(s.closing_upb, 0.0) AS closing_upb,
            COALESCE(s.new_active_upb, 0.0) AS new_active_upb,
            COALESCE(s.gap_upb_in, 0.0) AS gap_upb_in,
            COALESCE(n.gap_upb_out, 0.0) AS gap_upb_out,
            COALESCE(n.early_noexit_upb, 0.0) AS early_noexit_upb,
            COALESCE(s.unmask_jump_upb, 0.0) AS unmask_jump_upb,
            COALESCE(s.reported_principal_paid_upb, 0.0) AS reported_principal_paid_upb,
            COALESCE(s.inferred_principal_upb, 0.0) AS inferred_principal_upb,
            COALESCE(s.cap_added_upb, 0.0) AS cap_added_upb,
            COALESCE(s.delta_mod_non_interest_upb, 0.0) AS delta_mod_non_interest_upb,
            COALESCE(s.payoff_upb, 0.0) AS payoff_upb,
            COALESCE(s.credit_exit_upb, 0.0) AS credit_exit_upb,
            COALESCE(s.other_exit_upb, 0.0) AS other_exit_upb,
            COALESCE(s.exit_prev_upb_diff, 0.0) AS exit_prev_upb_diff,
            COALESCE(s.active_forgiven_upb, 0.0) AS active_forgiven_upb,
            COALESCE(s.active_writeoff_upb, 0.0) AS active_writeoff_upb,
            COALESCE(s.exit_writeoff_upb, 0.0) AS exit_writeoff_upb,
            COALESCE(s.masked_early_rows, 0)::BIGINT AS masked_early_rows
        FROM same_month_events s
        FULL OUTER JOIN next_month_drops n ON s.reporting_period = n.reporting_period
        WHERE COALESCE(s.reporting_period, n.reporting_period) <= DATE '{dataset_end_iso}'
    """

    # Summarize yearly reporting coverage, relief flags, invalid values, and unexplained arrears resets
    # Group classified rows by calendar year and count each quality indicator with conditional FILTER clauses
    yearly_sql = cte + """
        SELECT
            year(reporting_period)::VARCHAR AS year,
            count(*)::BIGINT AS total_rows,
            count(*) FILTER (WHERE zero_balance_code IS NULL)::BIGINT AS active_rows,
            count(*) FILTER (WHERE COALESCE(current_upb, -1.0) = 0.0 AND zero_balance_code IS NULL AND COALESCE(loan_age, 0) <= 6)::BIGINT AS masked_early_rows,
            count(*) FILTER (WHERE delinquency_months IS NULL)::BIGINT AS xx_or_blank_dpd_rows,
            count(*) FILTER (WHERE total_principal IS NOT NULL)::BIGINT AS total_principal_filled_rows,
            count(*) FILTER (WHERE borrower_assistance_plan IN ('F','T','R'))::BIGINT AS active_plan_rows,
            count(*) FILTER (WHERE alt_delinquency_resolution IN ('C','P','D'))::BIGINT AS deferral_flag_rows,
            count(*) FILTER (WHERE COALESCE(current_upb, 0.0) < 0.0)::BIGINT AS negative_upb_rows,
            count(*) FILTER (WHERE current_rate IS NOT NULL AND current_rate <= 0.0)::BIGINT AS invalid_rate_rows,
            count(*) FILTER (
                WHERE is_contig_prev AND zero_balance_code IS NULL
                  AND prev_dpd >= 2 AND delinquency_months = 0
                  AND COALESCE(modification_flag, '') != 'Y'
                  AND COALESCE(alt_delinquency_resolution, '') NOT IN ('C','P','D')
            )::BIGINT AS reaging_events
        FROM classified
        GROUP BY 1
    """

    # Check each loan's full lifespan for skipped months, duplicates, early stops, and servicer switches
    # Collapse each loan_id to its min/max dates and compare observed row count against expected month span
    loan_summary_sql = cte + f"""
        , per_loan AS (
            SELECT
                loan_id,
                min(reporting_period) AS first_rp,
                max(reporting_period) AS last_rp,
                count(*) AS n_rows,
                datediff('month', min(reporting_period), max(reporting_period)) + 1 AS span_months,
                bool_or(zero_balance_code IS NOT NULL) AS has_exit,
                count(DISTINCT servicer_name) FILTER (WHERE servicer_name IS NOT NULL) AS n_servicers
            FROM classified
            GROUP BY loan_id
        )
        SELECT
            count(*)::BIGINT AS total_loans,
            count(*) FILTER (WHERE n_rows < span_months)::BIGINT AS gap_loans,
            count(*) FILTER (WHERE n_rows > span_months)::BIGINT AS dup_loans,
            count(*) FILTER (WHERE last_rp < DATE '{dataset_end_iso}' AND NOT has_exit)::BIGINT AS early_noexit_loans,
            count(*) FILTER (WHERE n_servicers > 1)::BIGINT AS multi_servicer_loans
        FROM per_loan
    """
    return monthly_sql, yearly_sql, loan_summary_sql


# Execute the full portfolio balance and data-health audit across all 104 quarters
# Scan each core Parquet file, roll up monthly/yearly/loan summaries, save two marts and two charts, and verify 7 alarms
def run_audit(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
    dataset_end_iso: str = "2025-12-01",
    sample_filter: bool = False,
) -> int:
    """Execute Stock-and-flow roll-forward and plausibility audit over core Parquet files."""
    t0 = time.time()
    check = c.Checker("01_data_audit: roll-forward and plausibility")

    # Accumulate monthly flows, yearly health counts, and loan lifespan totals across all quarters
    # Execute the three SQL queries per core Parquet file and append each result to in-memory lists/counters
    monthly_parts: list[pd.DataFrame] = []
    yearly_parts: list[pd.DataFrame] = []
    loan_totals = {"total_loans": 0, "gap_loans": 0, "dup_loans": 0, "early_noexit_loans": 0, "multi_servicer_loans": 0}

    for idx, f in enumerate(core_files, 1):
        m_sql, y_sql, l_sql = audit_quarter_sql(f, dataset_end_iso=dataset_end_iso)
        monthly_parts.append(c.q(marts, m_sql))
        yearly_parts.append(c.q(marts, y_sql))
        lr = marts.execute(l_sql).fetchall()[0]
        loan_totals["total_loans"] += int(lr[0] or 0)
        loan_totals["gap_loans"] += int(lr[1] or 0)
        loan_totals["dup_loans"] += int(lr[2] or 0)
        loan_totals["early_noexit_loans"] += int(lr[3] or 0)
        loan_totals["multi_servicer_loans"] += int(lr[4] or 0)
        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] scanned {f.stem} ({time.time() - t0:.1f}s)", flush=True)

    # Combine quarterly flow tables into a single 312-month portfolio timeline
    # Concatenate all DataFrames, sum numeric columns by reporting_period, and sort chronologically
    df = (
        pd.concat(monthly_parts, ignore_index=True)
        .groupby("reporting_period", as_index=False)
        .sum(numeric_only=True)
        .sort_values("reporting_period")
        .reset_index(drop=True)
    )
    # Reconcile active loan counts month over month
    # Shift prior closing open_loans forward by 1 row and subtract opening + inflows - outflows from open_loans
    df["opening_loans"] = df["open_loans"].shift(1).fillna(0).astype("int64")
    df["count_residual"] = df["open_loans"] - (
        df["opening_loans"]
        + df["new_loans_active"]
        + df["gap_reappear"]
        - df["exits_from_prior"]
        - df["gap_disappear"]
        - df["early_noexit"]
    )
    # Reconcile Unpaid Principal Balance (UPB) and isolate any unexplained monthly residual
    # Shift closing_upb forward for opening_upb, sum reported + inferred principal, and compute closing minus expected
    df["opening_upb"] = df["closing_upb"].shift(1).fillna(0.0)
    df["principal_paid_eff_upb"] = df["reported_principal_paid_upb"] + df["inferred_principal_upb"]
    df["unexplained_upb"] = df["closing_upb"] - (
        df["opening_upb"]
        + df["new_active_upb"]
        + df["unmask_jump_upb"]
        + df["cap_added_upb"]
        + df["gap_upb_in"]
        - df["principal_paid_eff_upb"]
        - df["payoff_upb"]
        - df["credit_exit_upb"]
        - df["other_exit_upb"]
        - df["exit_prev_upb_diff"]
        - df["gap_upb_out"]
        - df["early_noexit_upb"]
    )
    df["unexplained_pct_of_closing"] = (
        df["unexplained_upb"] / df["closing_upb"].replace(0.0, float("nan")) * 100.0
    ).fillna(0.0)

    # Persist the monthly balance roll-forward bridge in DuckDB
    # Write df via module2_common.write_df keyed by reporting_period
    c.write_df(marts, "balance_rollforward_mart", df, ["reporting_period"])

    # Combine yearly plausibility counts across all 104 quarters
    # Concatenate yearly_parts, sum by calendar year, and flatten portfolio loan totals into long-form rows
    ydf = (
        pd.concat(yearly_parts, ignore_index=True)
        .groupby("year", as_index=False)
        .sum(numeric_only=True)
        .sort_values("year")
        .reset_index(drop=True)
    )
    plaus_rows: list[dict] = []
    for k, v in loan_totals.items():
        plaus_rows.append({"check_scope": "portfolio_loans", "metric_name": k, "year": "ALL", "value": float(v), "share_pct": 100.0 * v / max(loan_totals["total_loans"], 1)})

    # Check origination data completeness and valid value bounds
    # Query loans_table directly in DuckDB for null FICO/DTI/first-payment dates and out-of-range LTV/UPB
    where_l = c.scope(sample_filter, prefix=src_prefix) if src_prefix else "TRUE"
    orig_tbl = f"{src_prefix}loans_table"
    orig_stats = marts.execute(f"""
        SELECT
            count(*)::BIGINT AS loans_n,
            count(*) FILTER (WHERE orig_ltv IS NULL OR orig_ltv <= 0 OR orig_ltv > 150)::BIGINT AS bad_ltv,
            count(*) FILTER (WHERE dti IS NULL)::BIGINT AS null_dti,
            count(*) FILTER (WHERE credit_score IS NULL)::BIGINT AS null_fico,
            count(*) FILTER (WHERE orig_upb IS NULL OR orig_upb <= 0)::BIGINT AS bad_upb,
            count(*) FILTER (WHERE first_payment_date IS NULL)::BIGINT AS null_fpd
        FROM {orig_tbl}
        WHERE {where_l}
    """).fetchall()[0]
    loans_n = max(int(orig_stats[0] or 0), 1)
    for m_name, cnt in zip(["invalid_orig_ltv_loans", "null_dti_loans", "null_fico_loans", "invalid_orig_upb_loans", "null_first_payment_loans"], orig_stats[1:]):
        plaus_rows.append({"check_scope": "origination", "metric_name": m_name, "year": "ALL", "value": float(cnt), "share_pct": 100.0 * cnt / loans_n})

    # Compute portfolio-wide totals for re-aging, negative UPB, and invalid interest rates
    # Sum yearly flags across all years and append overall row shares to the plausibility list
    total_reaging = int(ydf["reaging_events"].sum())
    total_neg_upb = int(ydf["negative_upb_rows"].sum())
    total_bad_rate = int(ydf["invalid_rate_rows"].sum())
    plaus_rows.append({"check_scope": "monthly_rows", "metric_name": "reaging_events_total", "year": "ALL", "value": float(total_reaging), "share_pct": 100.0 * total_reaging / max(int(ydf["total_rows"].sum()), 1)})
    plaus_rows.append({"check_scope": "monthly_rows", "metric_name": "negative_upb_rows", "year": "ALL", "value": float(total_neg_upb), "share_pct": 100.0 * total_neg_upb / max(int(ydf["total_rows"].sum()), 1)})
    plaus_rows.append({"check_scope": "monthly_rows", "metric_name": "invalid_rate_rows", "year": "ALL", "value": float(total_bad_rate), "share_pct": 100.0 * total_bad_rate / max(int(ydf["total_rows"].sum()), 1)})

    # Build yearly percentage trend rows and persist the data plausibility scorecard
    # Divide each yearly metric by total or active rows and write data_plausibility_mart to DuckDB
    for _, r in ydf.iterrows():
        tot = max(float(r["total_rows"]), 1.0)
        act = max(float(r["active_rows"]), 1.0)
        for m_name, val, denom in [
            ("total_principal_fill_pct", 100.0 * r["total_principal_filled_rows"] / tot, 1.0),
            ("masked_early_active_pct", 100.0 * r["masked_early_rows"] / act, 1.0),
            ("xx_or_blank_dpd_pct", 100.0 * r["xx_or_blank_dpd_rows"] / tot, 1.0),
            ("active_relief_plan_pct", 100.0 * r["active_plan_rows"] / tot, 1.0),
            ("deferral_flag_pct", 100.0 * r["deferral_flag_rows"] / tot, 1.0),
            ("reaging_events", float(r["reaging_events"]), 100.0 * r["reaging_events"] / act),
        ]:
            plaus_rows.append({
                "check_scope": "yearly_trend",
                "metric_name": m_name,
                "year": str(r["year"]),
                "value": float(r["reaging_events"] if m_name == "reaging_events" else val),
                "share_pct": float(denom if m_name == "reaging_events" else val),
            })

    pdf_out = pd.DataFrame(plaus_rows)
    c.write_df(marts, "data_plausibility_mart", pdf_out, ["check_scope", "metric_name", "year"])

    # Render the latest month's balance roll-forward waterfall chart in USD billions
    # Stack positive and negative component bars sequentially and save to outputs_dir at 300 dpi
    if len(df) > 0:
        last = df.iloc[-1]
        steps = [
            ("Opening", float(last["opening_upb"]) / 1e9),
            ("New active", float(last["new_active_upb"]) / 1e9),
            ("Unmask jump", float(last["unmask_jump_upb"]) / 1e9),
            ("Cap added", float(last["cap_added_upb"]) / 1e9),
            ("Principal paid", -float(last["principal_paid_eff_upb"]) / 1e9),
            ("Payoffs (01)", -float(last["payoff_upb"]) / 1e9),
            ("Credit exits", -float(last["credit_exit_upb"]) / 1e9),
            ("Other exits", -float(last["other_exit_upb"]) / 1e9),
            ("Exit diff/gaps", -(float(last["exit_prev_upb_diff"]) + float(last["gap_upb_out"]) - float(last["gap_upb_in"])) / 1e9),
            ("Unexplained", float(last["unexplained_upb"]) / 1e9),
        ]
        fig, ax = plt.subplots(figsize=(12, 5))
        pos = 0.0
        for label, val in steps:
            color = "#2a78d6" if val >= 0 else "#eb6834"
            ax.bar(label, val, bottom=pos if val >= 0 else pos + val, width=0.6, color=color)
            pos += val
        ax.axhline(0, color="black", linewidth=0.6)
        ax.set_title(f"Balance Roll-Forward Waterfall ({str(last['reporting_period'])[:10]})")
        ax.set_xlabel("Balance Component")
        ax.set_ylabel("Unpaid Principal Balance (USD Billions)")
        ax.yaxis.set_major_formatter(mtick.FormatStrFormatter("%.1f"))
        plt.xticks(rotation=25, ha="right")
        c.save_chart(fig, c.script_out(outputs_dir, "01_data_audit") / "01_balance_waterfall.png")

    # Render the 26-year servicer field coverage and early balance masking chart
    # Plot yearly percentages for principal fill, masked $0 UPB, and blank DPD and save at 300 dpi
    if len(ydf) > 0:
        fig, ax = plt.subplots(figsize=(11, 4.8))
        ax.plot(ydf["year"], 100.0 * ydf["total_principal_filled_rows"] / ydf["total_rows"].clip(lower=1), label="total_principal filled (%)")
        ax.plot(ydf["year"], 100.0 * ydf["masked_early_rows"] / ydf["active_rows"].clip(lower=1), label="masked early 0.00 UPB (%)")
        ax.plot(ydf["year"], 100.0 * ydf["xx_or_blank_dpd_rows"] / ydf["total_rows"].clip(lower=1), label="unknown/blank DPD (%)")
        ax.set_title("Monthly Field Coverage and Early Balance Masking by Calendar Year")
        ax.set_xlabel("Calendar Year")
        ax.set_ylabel("Share of Rows (%)")
        plt.xticks(rotation=45, ha="right")
        ax.legend()
        c.save_chart(fig, c.script_out(outputs_dir, "01_data_audit") / "01_fill_rates.png")

    # Evaluate all 7 automated audit alarms and verify primary keys on both output marts
    # Compute worst-case residuals across 312 months and register pass/fail assertions via Checker
    max_count_res = int(df["count_residual"].abs().max()) if len(df) > 0 else 0
    nan_count = int(df[["opening_upb", "closing_upb", "unexplained_upb"]].isna().sum().sum())
    max_abs_unexp = float(df["unexplained_upb"].abs().max()) if len(df) > 0 else 0.0
    max_unexp_pct = float(df["unexplained_pct_of_closing"].abs().max()) if len(df) > 0 else 0.0
    check.add("active loan count roll-forward ties exactly every month", max_count_res == 0, f"max_abs_residual={max_count_res}")
    check.add("zero NaN values in balance roll-forward columns", nan_count == 0, f"nan_cells={nan_count}")
    check.add("unexplained UPB < 0.01% of closing UPB every month", max_unexp_pct < 0.01, f"max_abs_pct={max_unexp_pct:.6f}% (max_abs_upb={max_abs_unexp:,.2f})")
    check.add("zero duplicate monthly rows per loan", loan_totals["dup_loans"] == 0, f"dup_loans={loan_totals['dup_loans']}")
    check.add("zero negative UPB rows", total_neg_upb == 0, f"negative_upb_rows={total_neg_upb}")
    check.key(marts, "balance_rollforward_mart", ["reporting_period"])
    check.key(marts, "data_plausibility_mart", ["check_scope", "metric_name", "year"])

    print(
        f"  Summary: loans={loan_totals['total_loans']:,}, gaps={loan_totals['gap_loans']:,}, "
        f"early_noexit={loan_totals['early_noexit_loans']:,}, reaging={total_reaging:,}, "
        f"max_abs_unexplained_upb={max_abs_unexp:,.2f}",
        flush=True,
    )
    return check.finish()


# Define command-line flags (--sample/--full and custom path overrides)
# Build an ArgumentParser and attach shared Module 2 options via module2_common.add_common_args
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Balance roll-forward and plausibility audit.")
    c.add_common_args(parser)
    return parser.parse_args()


# Run the audit script from end to end and return a pass/fail exit code
# Resolve sample vs. full paths, connect to marts DB, attach source DB, run audit, and close connection
def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_audit(marts, sp, core_files, args.outputs_dir, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
