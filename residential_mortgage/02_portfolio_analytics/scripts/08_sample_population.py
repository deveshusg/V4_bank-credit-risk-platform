"""Excluded-population profile for PD sample eligibility (Stage B, script 08).

Reads partitioned Parquet `book_snapshot` strictly inside DuckDB SQL (never loads
280M rows into pandas or requires pyarrow). Compares included vs excluded groups
(`in_default_at_snapshot`, `masked_early_lt6m`, `incomplete_window_2025`,
`missing_fico_or_dti`, `non_credit_exit_before_12m`) across years and key drivers.

Output: sample_population_mart (key: (snapshot_year, population_group, reason)).
Run: python residential_mortgage/02_portfolio_analytics/scripts/08_sample_population.py [--full]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


# Summarize PD modeling population inclusions and exclusions across all December book snapshots
# Aggregates partitioned book_snapshot Parquets by year, group, and exclusion_reason via SQL
def run_sample_population(marts: object, outputs_dir: Path) -> int:
    """Profile PD sample inclusions and exclusions across partitioned book_snapshot."""
    check = c.Checker("08_sample_population: included vs excluded PD profile")
    snap_root = c.snapshot_dir(outputs_dir)
    snap_glob = str(snap_root / "year=*" / "*.parquet").replace("\\", "/")
    part_files = list(snap_root.glob("year=*/*.parquet"))
    if not part_files:
        raise FileNotFoundError(f"book_snapshot Parquet partitions missing in {snap_root}")

    df = c.q(marts, f"""
        WITH s AS (
            SELECT
                year(snapshot_date) AS snapshot_year,
                CASE WHEN bad_12m IN (0, 1) AND exclusion_reason = 'included' THEN 'included'
                     ELSE 'excluded' END AS population_group,
                CASE WHEN bad_12m IN (0, 1) AND exclusion_reason = 'included' THEN 'included_pd_sample'
                     WHEN in_default THEN 'in_default_at_snapshot'
                     WHEN balance_masked_flag THEN 'masked_early_lt6m'
                     WHEN outcome_12m_status = 'incomplete_2025' THEN 'incomplete_window_2025'
                     WHEN outcome_12m_status = 'other_exit' THEN 'non_credit_exit_before_12m'
                     ELSE exclusion_reason END AS reason,
                current_upb,
                credit_score,
                orig_ltv,
                dti,
                note_rate
            FROM read_parquet('{snap_glob}')
        )
        SELECT
            snapshot_year::INTEGER AS snapshot_year,
            population_group,
            reason,
            count(*)::BIGINT AS loans,
            COALESCE(sum(current_upb), 0.0) AS balance_upb,
            avg(credit_score) FILTER (WHERE credit_score IS NOT NULL) AS mean_credit_score,
            avg(orig_ltv) FILTER (WHERE orig_ltv IS NOT NULL) AS mean_orig_ltv,
            avg(dti) FILTER (WHERE dti IS NOT NULL) AS mean_dti,
            avg(note_rate) FILTER (WHERE note_rate IS NOT NULL) AS mean_note_rate
        FROM s
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """)
    c.write_df(marts, "sample_population_mart", df, ["snapshot_year", "population_group", "reason"])

    tot_snap = int(c.scalar(marts, f"SELECT count(*) FROM read_parquet('{snap_glob}')") or 0)
    tot_mart = int(df["loans"].sum()) if not df.empty else 0

    check.key(marts, "sample_population_mart", ["snapshot_year", "population_group", "reason"])
    check.add("sample_population_mart row sum ties identically to book_snapshot", tot_mart == tot_snap, f"mart={tot_mart:,}, snapshot={tot_snap:,}")

    inc = int(df.loc[df["population_group"] == "included", "loans"].sum())
    exc = int(df.loc[df["population_group"] == "excluded", "loans"].sum())
    print(f"  PD sample rows across Decembers: included={inc:,}, excluded={exc:,} (total={tot_snap:,})", flush=True)
    return check.finish()


# Parse CLI arguments for 08_sample_population
# Uses module2_common.add_common_args()
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile excluded vs included PD populations.")
    c.add_common_args(parser)
    return parser.parse_args()


# Connect to marts DB and generate sample_population_mart with 100% snapshot row parity
# Validates scope consistency and asserts mart row sum matches raw book_snapshot count
def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    rc = run_sample_population(marts, args.outputs_dir)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
