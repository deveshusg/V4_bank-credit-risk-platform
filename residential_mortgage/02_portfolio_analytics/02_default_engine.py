"""Regulatory default definition and probation state machine (Stage A, script 02).

Implements PRA/CRR rules (Article 178) and Module 2 design specifications:
- Triggers: >= 3 whole months behind, first N->Y distressed restructuring transition,
  or credit exit codes ('02','03','09','15'). Unknown 'XX' neither triggers nor cleans.
- Probation: 3 clean months after arrears default; 12 clean months after distressed
  restructuring. Any month >= 1 behind restarts clean=0. Restructuring while already
  in arrears default upgrades probation from 3 to 12 months and resets clean=0 (Art 178(5A)).
- COVID M2-4: cumulative 6-month hold on active ('F','T','R') spells starting
  2020-03..2021-03 through 2021-07, compared side-by-side against as-reported.
- Quarter-by-quarter execution and DuckDB SQL generate_series status expansion.

Outputs: default_events_mart, default_status_monthly, default_sensitivity_mart.
Run: python residential_mortgage/02_portfolio_analytics/02_default_engine.py [--sample]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


def run_loan_records(
    months: Sequence[str],
    mb: Sequence[int | None],
    plans: Sequence[str],
    mod: Sequence[str],
    zbc: Sequence[str],
    upb: Sequence[float | None],
    upb_removal: Sequence[float | None],
    loan_age: Sequence[int | None],
    mob_list: Sequence[int | None],
    orig_upb: float,
    note_rate: float,
    loan_term: int,
    apply_covid_hold: bool = True,
) -> list[dict]:
    """Run default & probation state machine for a single loan chronologically sorted."""
    if apply_covid_hold:
        adj_dpd, in_hold = c.covid_hold_months(mb, plans, months)
    else:
        adj_dpd = list(mb)
        in_hold = [False] * len(mb)

    events: list[dict] = []
    cur: dict | None = None
    ever_restructured = False
    seen_non_y_mod = False

    for i in range(len(months)):
        m = months[i]
        m_flag = mod[i] or ""
        if m_flag == "Y":
            restruct = seen_non_y_mod and not ever_restructured
            if restruct:
                ever_restructured = True
            elif not seen_non_y_mod:
                # Arrived on first observed row already marked Y; record as pre-modified entry, not new transition.
                ever_restructured = True
        else:
            seen_non_y_mod = True
            restruct = False

        dpd_val = adj_dpd[i]
        arrears = dpd_val is not None and dpd_val >= c.DPD_DEFAULT_MONTHS
        code = zbc[i] or ""
        credit = code in c.CREDIT_EXIT_CODES

        if cur is None:
            if arrears or restruct or credit:
                if credit and not arrears and not restruct:
                    trigger = "credit_exit"
                elif restruct and arrears:
                    trigger = "restructuring+arrears"
                elif restruct:
                    trigger = "restructuring"
                else:
                    trigger = "arrears"

                prob_m = (
                    c.PROBATION_RESTRUCTURING_MONTHS
                    if ("restructuring" in trigger)
                    else c.PROBATION_ARREARS_MONTHS
                )

                # Balance at default (handle credit exit removal UPB and masked early 0.00 UPB)
                rep_upb = upb[i]
                rem_upb = upb_removal[i]
                masked_flag = False
                if code in c.CREDIT_EXIT_CODES:
                    bal_def = float(rem_upb) if rem_upb is not None else float(rep_upb or 0.0)
                elif (rep_upb is None or float(rep_upb) == 0.0) and (
                    loan_age[i] is None or int(loan_age[i]) <= 6
                ):
                    masked_flag = True
                    bal_def = c.scheduled_upb(orig_upb, note_rate, loan_term, mob_list[i] or 0)
                else:
                    bal_def = float(rep_upb or 0.0)

                cur = {
                    "default_month": m,
                    "trigger_type": trigger,
                    "probation_months": prob_m,
                    "upgraded_by_restructuring": False,
                    "balance_at_default_reported": float(rep_upb or 0.0),
                    "balance_at_default": bal_def,
                    "balance_masked_flag": masked_flag,
                    "months_behind_at_default": dpd_val,
                    "clean": 0,
                    "cure_month": None,
                    "end_reason": None,
                    "end_month": m,
                    "re_default_number": len(events) + 1,
                }
                if credit:
                    cur["end_reason"] = "credit exit"
                    events.append(cur)
                    cur = None
                elif code == "01":
                    cur["end_reason"] = "cured - paid off"
                    events.append(cur)
                    cur = None
                elif code in c.OTHER_EXIT_CODES:
                    cur["end_reason"] = "other exit"
                    events.append(cur)
                    cur = None
        else:
            cur["end_month"] = m
            if credit:
                cur["end_reason"] = "credit exit"
                events.append(cur)
                cur = None
                continue
            if code == "01":
                cur["end_reason"] = "cured - paid off"
                events.append(cur)
                cur = None
                continue
            if code in c.OTHER_EXIT_CODES:
                cur["end_reason"] = "other exit"
                events.append(cur)
                cur = None
                continue

            if restruct:
                if cur["probation_months"] < c.PROBATION_RESTRUCTURING_MONTHS:
                    cur["probation_months"] = c.PROBATION_RESTRUCTURING_MONTHS
                    cur["upgraded_by_restructuring"] = True
                cur["clean"] = 0
                continue

            if dpd_val is not None and dpd_val >= 1:
                cur["clean"] = 0
                continue

            if dpd_val is None or in_hold[i]:
                # Unknown 'XX' or active COVID hold pauses probation clock without incrementing.
                continue

            if dpd_val == 0:
                cur["clean"] += 1
                if cur["clean"] >= cur["probation_months"]:
                    cur["end_reason"] = "cured"
                    cur["cure_month"] = m
                    events.append(cur)
                    cur = None

    if cur is not None:
        cur["end_reason"] = "end of data"
        events.append(cur)
    return events


def run_loan_df(g: pd.DataFrame, apply_covid_hold: bool = True) -> list[dict]:
    """Adapt sorted single-loan DataFrame slice to run_loan_records."""
    return run_loan_records(
        months=g["month"].tolist(),
        mb=[None if pd.isna(v) else int(v) for v in g["delinquency_months"]],
        plans=["" if pd.isna(v) else str(v) for v in g["borrower_assistance_plan"]],
        mod=["" if pd.isna(v) else str(v) for v in g["modification_flag"]],
        zbc=["" if pd.isna(v) else str(v) for v in g["zero_balance_code"]],
        upb=[None if pd.isna(v) else float(v) for v in g["current_upb"]],
        upb_removal=[None if pd.isna(v) else float(v) for v in g["upb_at_removal"]],
        loan_age=[None if pd.isna(v) else int(v) for v in g["loan_age"]],
        mob_list=[None if pd.isna(v) else int(v) for v in g["mob"]],
        orig_upb=float(g["orig_upb"].iloc[0] or 0.0),
        note_rate=float(g["note_rate"].iloc[0] or 0.0),
        loan_term=int(g["loan_term"].iloc[0] or 360),
        apply_covid_hold=apply_covid_hold,
    )


def init_default_tables(marts: object) -> None:
    """Create empty target tables for incremental per-quarter insertion."""
    marts.execute("""
        CREATE OR REPLACE TABLE default_events_mart (
            loan_id VARCHAR,
            acquisition_quarter VARCHAR,
            default_month DATE,
            trigger_type VARCHAR,
            probation_months INTEGER,
            upgraded_by_restructuring BOOLEAN,
            balance_at_default_reported DECIMAL(12, 2),
            balance_at_default DECIMAL(12, 2),
            balance_masked_flag BOOLEAN,
            months_behind_at_default INTEGER,
            cure_month DATE,
            end_reason VARCHAR,
            end_month DATE,
            re_default_number INTEGER
        )
    """)


def run_default_engine(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
) -> int:
    """Run state machine quarter-by-quarter across core Parquet files and verify checks."""
    t0 = time.time()
    check = c.Checker("02_default_engine: default events and probation")
    init_default_tables(marts)

    credit_lit = c.sql_list(c.CREDIT_EXIT_CODES)
    sens_records: list[dict] = []
    total_events = 0
    total_candidates = 0

    event_cols = [
        "loan_id", "acquisition_quarter", "default_month", "trigger_type",
        "probation_months", "upgraded_by_restructuring", "balance_at_default_reported",
        "balance_at_default", "balance_masked_flag", "months_behind_at_default",
        "cure_month", "end_reason", "end_month", "re_default_number",
    ]

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        hist = marts.execute(f"""
            WITH cands AS (
                SELECT DISTINCT loan_id
                FROM read_parquet('{fp}')
                WHERE delinquency_months >= {c.DPD_DEFAULT_MONTHS}
                   OR modification_flag = 'Y'
                   OR zero_balance_code IN {credit_lit}
            )
            SELECT
                m.loan_id,
                m.acquisition_quarter,
                strftime(m.reporting_period, '%Y-%m') AS month,
                m.delinquency_months,
                m.modification_flag,
                m.zero_balance_code,
                CAST(m.current_upb AS DOUBLE) AS current_upb,
                CAST(m.upb_at_removal AS DOUBLE) AS upb_at_removal,
                m.borrower_assistance_plan,
                m.loan_age,
                datediff('month', l.first_payment_date, m.reporting_period) AS mob,
                CAST(l.orig_upb AS DOUBLE) AS orig_upb,
                CAST(l.note_rate AS DOUBLE) AS note_rate,
                COALESCE(l.loan_term, 360) AS loan_term
            FROM read_parquet('{fp}') m
            JOIN cands ON cands.loan_id = m.loan_id
            JOIN {src_prefix}loans_table l ON l.loan_id = m.loan_id AND l.acquisition_quarter = '{quarter}'
            ORDER BY m.loan_id, m.reporting_period
        """).df()

        if hist.empty:
            continue

        q_events: list[dict] = []
        n_q_cand = 0
        for loan_id, g in hist.groupby("loan_id", sort=False):
            n_q_cand += 1
            for apply_covid, label in ((True, "covid_adjusted"), (False, "as_reported")):
                evs = run_loan_df(g, apply_covid_hold=apply_covid)
                for ev in evs:
                    if apply_covid:
                        ev["loan_id"] = loan_id
                        ev["acquisition_quarter"] = quarter
                        q_events.append(ev)
                    sens_records.append({
                        "treatment": label,
                        "year": int(ev["default_month"][:4]),
                        "trigger_type": ev["trigger_type"],
                        "balance_at_default": ev["balance_at_default"],
                    })

        total_candidates += n_q_cand
        if q_events:
            qdf = pd.DataFrame(q_events, columns=event_cols)
            qdf["default_month"] = pd.to_datetime(qdf["default_month"] + "-01").dt.date
            qdf["end_month"] = pd.to_datetime(qdf["end_month"] + "-01").dt.date
            qdf["cure_month"] = pd.to_datetime(qdf["cure_month"], errors="coerce").dt.date
            c.insert_df(marts, "default_events_mart", qdf)
            total_events += len(qdf)

        if idx % 10 == 0 or idx == len(core_files):
            print(
                f"  [{idx:3d}/{len(core_files)}] {quarter}: cum_candidates={total_candidates:,}, cum_events={total_events:,} ({time.time() - t0:.1f}s)",
                flush=True,
            )

    # Expand default_events_mart -> default_status_monthly completely in DuckDB SQL
    marts.execute("""
        CREATE OR REPLACE TABLE default_status_monthly AS
        SELECT
            loan_id,
            acquisition_quarter,
            CAST(gs.m AS DATE) AS reporting_period,
            TRUE AS in_default,
            default_month,
            trigger_type,
            re_default_number
        FROM default_events_mart,
        LATERAL generate_series(default_month, end_month, INTERVAL 1 MONTH) AS gs(m)
    """)

    if sens_records:
        sdf = (
            pd.DataFrame(sens_records)
            .groupby(["treatment", "year", "trigger_type"], as_index=False)
            .agg(events=("balance_at_default", "count"), balance_at_default=("balance_at_default", "sum"))
        )
    else:
        sdf = pd.DataFrame(columns=["treatment", "year", "trigger_type", "events", "balance_at_default"])
    c.write_df(marts, "default_sensitivity_mart", sdf, ["treatment", "year", "trigger_type"])

    # Validation checks in DuckDB SQL
    missing_reason = int(c.scalar(marts, "SELECT count(*) FROM default_events_mart WHERE end_reason IS NULL") or 0)
    bad_cure = int(
        c.scalar(
            marts,
            """
            SELECT count(*) FROM default_events_mart
            WHERE (end_reason = 'cured' AND cure_month IS NULL)
               OR (end_reason != 'cured' AND cure_month IS NOT NULL)
            """,
        )
        or 0
    )
    overlap_cnt = int(
        c.scalar(
            marts,
            """
            WITH s AS (
                SELECT loan_id, default_month, end_month,
                       LAG(end_month) OVER (PARTITION BY loan_id ORDER BY default_month, re_default_number) AS prev_end
                FROM default_events_mart
            )
            SELECT count(*) FROM s WHERE prev_end IS NOT NULL AND default_month <= prev_end
            """,
        )
        or 0
    )
    ev_months = int(
        c.scalar(
            marts,
            "SELECT COALESCE(sum(datediff('month', default_month, end_month) + 1), 0) FROM default_events_mart",
        )
        or 0
    )
    st_rows = int(c.scalar(marts, "SELECT count(*) FROM default_status_monthly") or 0)
    bad_178_5a = int(
        c.scalar(
            marts,
            f"""
            SELECT count(*) FROM default_events_mart
            WHERE (trigger_type LIKE '%restructuring%' OR upgraded_by_restructuring)
              AND probation_months < {c.PROBATION_RESTRUCTURING_MONTHS}
            """,
        )
        or 0
    )

    check.add("every default event has an end_reason", missing_reason == 0, f"missing={missing_reason}")
    check.add("cure_month populated if and only if end_reason = cured", bad_cure == 0, f"violations={bad_cure}")
    check.add("no overlapping default spells for any loan", overlap_cnt == 0, f"overlaps={overlap_cnt}")
    check.add("restructuring spells enforce >= 12m probation (Art 178(5A))", bad_178_5a == 0, f"violations={bad_178_5a}")
    check.add("default_status_monthly count equals exact sum of event durations", ev_months == st_rows, f"expected={ev_months:,}, actual={st_rows:,}")
    check.key(marts, "default_events_mart", ["loan_id", "default_month", "re_default_number"])
    check.key(marts, "default_status_monthly", ["loan_id", "reporting_period"])
    check.key(marts, "default_sensitivity_mart", ["treatment", "year", "trigger_type"])

    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regulatory default definition and probation state machine.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_default_engine(marts, sp, core_files)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
