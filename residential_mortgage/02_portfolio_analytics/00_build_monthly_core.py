"""Build the narrow, typed monthly core dataset (Stage 0, script 00, D1-B).

Reads each loaded quarterly Parquet file once, writes a slim 23-column ZSTD
Parquet file sorted by (loan_id, reporting_period) into monthly_core[_sample],
extracts workout/exit cashflows into workout_exit_cashflows_mart, records build
scope metadata, and checks row counts, keys, and cent-for-cent balance ties.

Run: python residential_mortgage/02_portfolio_analytics/00_build_monthly_core.py [--sample]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402

WORKOUT_FILTER_SQL = """
    zero_balance_code IS NOT NULL
    OR foreclosure_date IS NOT NULL
    OR disposition_date IS NOT NULL
    OR last_paid_date IS NOT NULL
    OR foreclosure_writeoff IS NOT NULL
    OR foreclosure_costs IS NOT NULL
    OR preservation_repair_costs IS NOT NULL
    OR asset_recovery_costs IS NOT NULL
    OR misc_holding_expenses IS NOT NULL
    OR holding_taxes IS NOT NULL
    OR net_sales_proceeds IS NOT NULL
    OR credit_enhancement_proceeds IS NOT NULL
    OR repurchase_make_whole_proceeds IS NOT NULL
    OR other_foreclosure_proceeds IS NOT NULL
"""


def core_select_sql(raw_parquet: Path, quarter: str, loan_filter_sql: str = "") -> str:
    """Build SQL selecting the 23 typed loan_monthly_core columns from one raw Parquet file."""
    p = str(raw_parquet).replace("\\", "/")
    where_clause = f"WHERE {loan_filter_sql}" if loan_filter_sql else ""
    return f"""
        SELECT
            '{quarter}'::VARCHAR AS acquisition_quarter,
            loan_id::VARCHAR AS loan_id,
            CAST(try_strptime(reporting_period, '%m%Y') AS DATE) AS reporting_period,
            servicer_name::VARCHAR AS servicer_name,
            TRY_CAST(current_rate AS DECIMAL(6, 3)) AS current_rate,
            TRY_CAST(current_upb AS DECIMAL(12, 2)) AS current_upb,
            TRY_CAST(loan_age AS INTEGER) AS loan_age,
            TRY_CAST(months_to_legal_maturity AS INTEGER) AS months_to_legal_maturity,
            TRY_CAST(months_to_maturity AS INTEGER) AS months_to_maturity,
            TRY_CAST(total_principal AS DECIMAL(12, 2)) AS total_principal,
            CASE
                WHEN delinquency_status IS NULL OR delinquency_status = 'XX' THEN NULL
                ELSE TRY_CAST(delinquency_status AS INTEGER)
            END AS delinquency_months,
            COALESCE(delinquency_status = 'XX', FALSE) AS is_dpd_unknown,
            modification_flag::VARCHAR AS modification_flag,
            zero_balance_code::VARCHAR AS zero_balance_code,
            CAST(try_strptime(zero_balance_date, '%m%Y') AS DATE) AS zero_balance_date,
            TRY_CAST(upb_at_removal AS DECIMAL(12, 2)) AS upb_at_removal,
            borrower_assistance_plan::VARCHAR AS borrower_assistance_plan,
            alt_delinquency_resolution::VARCHAR AS alt_delinquency_resolution,
            TRY_CAST(alt_delinquency_resolution_count AS INTEGER) AS alt_delinquency_resolution_count,
            TRY_CAST(total_deferral_amount AS DECIMAL(12, 2)) AS total_deferral_amount,
            TRY_CAST(mod_non_interest_upb AS DECIMAL(12, 2)) AS mod_non_interest_upb,
            TRY_CAST(principal_forgiveness AS DECIMAL(12, 2)) AS principal_forgiveness,
            TRY_CAST(foreclosure_writeoff AS DECIMAL(12, 2)) AS foreclosure_writeoff
        FROM read_parquet('{p}')
        {where_clause}
        ORDER BY loan_id, reporting_period
    """


def workout_select_sql(raw_parquet: Path, quarter: str, loan_filter_sql: str = "") -> str:
    """Build SQL selecting workout/exit cashflows from one raw Parquet file."""
    p = str(raw_parquet).replace("\\", "/")
    extra = f"({loan_filter_sql}) AND " if loan_filter_sql else ""
    return f"""
        SELECT
            loan_id::VARCHAR AS loan_id,
            CAST(try_strptime(reporting_period, '%m%Y') AS DATE) AS reporting_period,
            '{quarter}'::VARCHAR AS acquisition_quarter,
            zero_balance_code::VARCHAR AS zero_balance_code,
            repurchase_make_whole_flag::VARCHAR AS repurchase_make_whole_flag,
            CAST(try_strptime(last_paid_date, '%m%Y') AS DATE) AS last_paid_date,
            CAST(try_strptime(foreclosure_date, '%m%Y') AS DATE) AS foreclosure_date,
            CAST(try_strptime(disposition_date, '%m%Y') AS DATE) AS disposition_date,
            TRY_CAST(upb_at_removal AS DECIMAL(12, 2)) AS upb_at_removal,
            TRY_CAST(foreclosure_costs AS DECIMAL(12, 2)) AS foreclosure_costs,
            TRY_CAST(preservation_repair_costs AS DECIMAL(12, 2)) AS preservation_repair_costs,
            TRY_CAST(asset_recovery_costs AS DECIMAL(12, 2)) AS asset_recovery_costs,
            TRY_CAST(misc_holding_expenses AS DECIMAL(12, 2)) AS misc_holding_expenses,
            TRY_CAST(holding_taxes AS DECIMAL(12, 2)) AS holding_taxes,
            TRY_CAST(net_sales_proceeds AS DECIMAL(12, 2)) AS net_sales_proceeds,
            TRY_CAST(credit_enhancement_proceeds AS DECIMAL(12, 2)) AS credit_enhancement_proceeds,
            TRY_CAST(repurchase_make_whole_proceeds AS DECIMAL(12, 2)) AS repurchase_make_whole_proceeds,
            TRY_CAST(other_foreclosure_proceeds AS DECIMAL(12, 2)) AS other_foreclosure_proceeds,
            TRY_CAST(mod_non_interest_upb AS DECIMAL(12, 2)) AS mod_non_interest_upb,
            TRY_CAST(principal_forgiveness AS DECIMAL(12, 2)) AS principal_forgiveness,
            TRY_CAST(foreclosure_writeoff AS DECIMAL(12, 2)) AS foreclosure_writeoff
        FROM read_parquet('{p}')
        WHERE {extra} ({WORKOUT_FILTER_SQL})
    """


def raw_totals_sql(raw_parquet: Path, loan_filter_sql: str = "") -> str:
    """Compute cent-exact core control sums from one raw Parquet file (minimal column scan)."""
    p = str(raw_parquet).replace("\\", "/")
    where_clause = f"WHERE {loan_filter_sql}" if loan_filter_sql else ""
    return f"""
        SELECT
            count(*)::BIGINT AS rows,
            count(DISTINCT loan_id)::BIGINT AS loans,
            COALESCE(sum(TRY_CAST(current_upb AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code IS NULL), 0) AS active_upb,
            COALESCE(sum(TRY_CAST(upb_at_removal AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code = '01'), 0) AS payoff_upb,
            COALESCE(sum(TRY_CAST(upb_at_removal AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code IN ('02','03','09','15')), 0) AS credit_exit_upb,
            COALESCE(sum(TRY_CAST(upb_at_removal AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code IN ('06','16','96')), 0) AS other_exit_upb,
            COALESCE(sum(TRY_CAST(foreclosure_writeoff AS DECIMAL(18, 2))), 0) AS writeoff_upb,
            COALESCE(sum(TRY_CAST(principal_forgiveness AS DECIMAL(18, 2))), 0) AS forgiven_upb
        FROM read_parquet('{p}')
        {where_clause}
    """


def core_totals_sql(core_parquet: Path) -> str:
    """Compute matching control sums and streaming sorted duplicate check from a built core Parquet file."""
    p = str(core_parquet).replace("\\", "/")
    return f"""
        WITH flagged AS (
            SELECT
                loan_id,
                reporting_period,
                zero_balance_code,
                current_upb,
                upb_at_removal,
                foreclosure_writeoff,
                principal_forgiveness,
                LAG(reporting_period) OVER (PARTITION BY loan_id ORDER BY reporting_period) AS prev_rp
            FROM read_parquet('{p}')
        )
        SELECT
            count(*)::BIGINT AS rows,
            count(DISTINCT loan_id)::BIGINT AS loans,
            count(*) FILTER (WHERE loan_id IS NULL OR reporting_period IS NULL)::BIGINT AS null_keys,
            COALESCE(sum(CAST(current_upb AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code IS NULL), 0) AS active_upb,
            COALESCE(sum(CAST(upb_at_removal AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code = '01'), 0) AS payoff_upb,
            COALESCE(sum(CAST(upb_at_removal AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code IN ('02','03','09','15')), 0) AS credit_exit_upb,
            COALESCE(sum(CAST(upb_at_removal AS DECIMAL(18, 2))) FILTER (WHERE zero_balance_code IN ('06','16','96')), 0) AS other_exit_upb,
            COALESCE(sum(CAST(foreclosure_writeoff AS DECIMAL(18, 2))), 0) AS writeoff_upb,
            COALESCE(sum(CAST(principal_forgiveness AS DECIMAL(18, 2))), 0) AS forgiven_upb,
            count(*) FILTER (WHERE prev_rp = reporting_period)::BIGINT AS dup_pairs
        FROM flagged
    """


def build_quarter_core(
    con: duckdb.DuckDBPyConnection,
    raw_parquet: Path,
    quarter: str,
    out_parquet: Path,
    loan_filter_sql: str = "",
) -> tuple[dict, tuple]:
    """Write one quarterly loan_monthly_core Parquet safely via .tmp replace and extract workout rows."""
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp_parquet = out_parquet.with_suffix(".parquet.tmp")
    if tmp_parquet.exists():
        tmp_parquet.unlink()

    sql = core_select_sql(raw_parquet, quarter, loan_filter_sql=loan_filter_sql)
    tmp_lit = str(tmp_parquet).replace("\\", "/")
    con.execute(f"COPY ({sql}) TO '{tmp_lit}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp_parquet, out_parquet)

    raw_tot = con.execute(raw_totals_sql(raw_parquet, loan_filter_sql=loan_filter_sql)).fetchall()[0]
    core_tot = con.execute(core_totals_sql(out_parquet)).fetchall()[0]

    w_sql = workout_select_sql(raw_parquet, quarter, loan_filter_sql=loan_filter_sql)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _q_w AS {w_sql}")
    w_sums = con.execute("""
        SELECT
            COALESCE(sum(CAST(foreclosure_costs AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(preservation_repair_costs AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(asset_recovery_costs AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(misc_holding_expenses AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(holding_taxes AS DECIMAL(18, 2))), 0),
            COALESCE(sum(CAST(net_sales_proceeds AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(credit_enhancement_proceeds AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(repurchase_make_whole_proceeds AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(other_foreclosure_proceeds AS DECIMAL(18, 2))), 0)
        FROM _q_w
    """).fetchall()[0]
    con.execute("INSERT INTO workout_exit_cashflows_mart SELECT * FROM _q_w")
    con.execute("DROP TABLE IF EXISTS _q_w")

    ok = (
        raw_tot[0] == core_tot[0]
        and raw_tot[1] == core_tot[1]
        and core_tot[2] == 0
        and raw_tot[2] == core_tot[3]
        and raw_tot[3] == core_tot[4]
        and raw_tot[4] == core_tot[5]
        and raw_tot[5] == core_tot[6]
        and raw_tot[6] == core_tot[7]
        and raw_tot[7] == core_tot[8]
        and core_tot[9] == 0
    )
    info = {
        "quarter": quarter,
        "rows": int(core_tot[0]),
        "loans": int(core_tot[1]),
        "active_upb": raw_tot[2],
        "payoff_upb": raw_tot[3],
        "credit_exit_upb": raw_tot[4],
        "other_exit_upb": raw_tot[5],
        "writeoff_upb": raw_tot[6],
        "forgiven_upb": raw_tot[7],
        "total_costs": w_sums[0],
        "total_proceeds": w_sums[1],
        "dup_pairs": int(core_tot[9]),
        "ok": ok,
    }
    return info, (raw_tot, core_tot)


def init_workout_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create empty workout_exit_cashflows_mart schema."""
    con.execute("""
        CREATE OR REPLACE TABLE workout_exit_cashflows_mart (
            loan_id VARCHAR,
            reporting_period DATE,
            acquisition_quarter VARCHAR,
            zero_balance_code VARCHAR,
            repurchase_make_whole_flag VARCHAR,
            last_paid_date DATE,
            foreclosure_date DATE,
            disposition_date DATE,
            upb_at_removal DECIMAL(12, 2),
            foreclosure_costs DECIMAL(12, 2),
            preservation_repair_costs DECIMAL(12, 2),
            asset_recovery_costs DECIMAL(12, 2),
            misc_holding_expenses DECIMAL(12, 2),
            holding_taxes DECIMAL(12, 2),
            net_sales_proceeds DECIMAL(12, 2),
            credit_enhancement_proceeds DECIMAL(12, 2),
            repurchase_make_whole_proceeds DECIMAL(12, 2),
            other_foreclosure_proceeds DECIMAL(12, 2),
            mod_non_interest_upb DECIMAL(12, 2),
            principal_forgiveness DECIMAL(12, 2),
            foreclosure_writeoff DECIMAL(12, 2)
        )
    """)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build narrow typed loan_monthly_core and workout cashflows.")
    c.add_common_args(parser)
    parser.add_argument("--raw-dir", default=str(c.RAW_PARQUET_DIR), help="raw quarterly Parquet directory")
    parser.add_argument("--quarter", default=None, help="single acquisition quarter (e.g. 2005Q1)")
    return parser.parse_args()


def main() -> int:
    t0 = time.time()
    args = c.resolve_paths(parse_args())
    raw_dir = Path(args.raw_dir)
    args.marts.parent.mkdir(parents=True, exist_ok=True)
    args.core_dir.mkdir(parents=True, exist_ok=True)

    check = c.Checker("00_build_monthly_core: narrow typed core & workout cashflows")
    marts = c.connect(args.marts, read_only=False)
    sp = c.attach_db(marts, args.db, "src")

    q_rows = marts.execute(f"SELECT quarter, monthly_rows, loans FROM {sp}loaded_quarters_table ORDER BY quarter").fetchall()
    if args.quarter:
        q_rows = [r for r in q_rows if r[0] == args.quarter]
        if not q_rows:
            raise ValueError(f"Quarter {args.quarter} not found in loaded_quarters_table.")

    scope_label = "sample" if args.sample else "full"
    print(f"00_build_monthly_core ({scope_label}): {len(q_rows)} quarters -> {args.core_dir}", flush=True)

    init_workout_table(marts)
    loan_filter = "loan_id IN (SELECT loan_id FROM _q_sample_ids)" if args.sample else ""

    all_ok = True
    total_rows = 0
    total_costs_raw = 0
    total_proceeds_raw = 0
    dup_sum = 0
    core_files: list[Path] = []
    for idx, (quarter, expected_full_rows, expected_full_loans) in enumerate(q_rows, 1):
        if args.sample:
            marts.execute(
                f"CREATE OR REPLACE TEMP TABLE _q_sample_ids AS SELECT loan_id FROM {sp}sampled_loans_table WHERE acquisition_quarter = '{quarter}'"
            )
        raw_p = raw_dir / f"{quarter}.parquet"
        out_p = args.core_dir / f"{quarter}.parquet"
        info, _ = build_quarter_core(marts, raw_p, quarter, out_p, loan_filter_sql=loan_filter)
        core_files.append(out_p)
        if not args.sample and not args.quarter:
            if info["rows"] != expected_full_rows or info["loans"] != expected_full_loans:
                info["ok"] = False
        all_ok = all_ok and info["ok"]
        total_rows += info["rows"]
        total_costs_raw += info["total_costs"]
        total_proceeds_raw += info["total_proceeds"]
        dup_sum += info["dup_pairs"]
        if idx % 10 == 0 or idx == len(q_rows) or not info["ok"]:
            elapsed = time.time() - t0
            print(
                f"  [{idx:3d}/{len(q_rows)}] {quarter}: rows={info['rows']:,}, loans={info['loans']:,}, ok={info['ok']} ({elapsed:.1f}s)",
                flush=True,
            )

    # Check workout costs/proceeds reconciliation
    w_tot = marts.execute("""
        SELECT
            COALESCE(sum(CAST(foreclosure_costs AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(preservation_repair_costs AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(asset_recovery_costs AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(misc_holding_expenses AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(holding_taxes AS DECIMAL(18, 2))), 0),
            COALESCE(sum(CAST(net_sales_proceeds AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(credit_enhancement_proceeds AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(repurchase_make_whole_proceeds AS DECIMAL(18, 2))), 0)
              + COALESCE(sum(CAST(other_foreclosure_proceeds AS DECIMAL(18, 2))), 0)
        FROM workout_exit_cashflows_mart
    """).fetchall()[0]

    check.add("all quarters built cleanly and matched raw source totals", all_ok, f"{total_rows:,} monthly rows across {len(q_rows)} quarters")
    check.key(marts, "workout_exit_cashflows_mart", ["loan_id", "reporting_period"])
    check.add(
        "workout costs & proceeds match raw source to the cent",
        (w_tot[0] == total_costs_raw) and (w_tot[1] == total_proceeds_raw),
        f"costs={w_tot[0]:,.2f}, proceeds={w_tot[1]:,.2f}",
    )

    if not args.quarter:
        lit = "[" + ", ".join("'" + str(f).replace("\\", "/") + "'" for f in core_files) + "]"
        marts.execute(f"CREATE OR REPLACE VIEW loan_monthly_core AS SELECT * FROM read_parquet({lit})")
        check.add("zero duplicate (loan_id, reporting_period) in loan_monthly_core", dup_sum == 0, f"duplicates={dup_sum}")

    if args.sample and not args.quarter:
        sample_target_loans = int(c.scalar(marts, f"SELECT count(*) FROM {sp}sampled_loans_table") or 0)
        core_unique_loans = int(c.scalar(marts, "SELECT count(DISTINCT loan_id) FROM loan_monthly_core") or 0)
        check.add(
            "sample core unique loans match sampled_loans_table",
            core_unique_loans == sample_target_loans,
            f"core_loans={core_unique_loans:,}, sampled_loans={sample_target_loans:,}",
        )
    elif not args.sample and not args.quarter:
        ledger_rows = sum(r[1] for r in q_rows)
        check.add(
            "full row total matches loaded_quarters_table sum",
            total_rows == ledger_rows,
            f"core={total_rows:,}, ledger={ledger_rows:,}",
        )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    marts.execute(f"""
        CREATE OR REPLACE TABLE build_metadata AS
        SELECT '{scope_label}'::VARCHAR AS scope,
               '{ts}'::VARCHAR AS built_at_utc,
               {total_rows}::BIGINT AS total_rows,
               {len(q_rows)}::INTEGER AS quarters_built
    """)
    marts.close()
    print(f"Finished 00_build_monthly_core in {time.time() - t0:.1f}s", flush=True)
    return check.finish()


if __name__ == "__main__":
    sys.exit(main())
