"""Survivorship and left-truncation by acquisition vintage (Stage F, script 17).

Reads loans_table in DuckDB SQL and vintage_curves_mart (never scans loan_monthly_core).
Quantifies seasoned late-acquired loans (vs acquisition quarter start date) and
compares cumulative default incidence across unseasoned vs seasoned cohorts.

Output: survivorship_mart (key: (acquisition_quarter, cohort_metric)).
Run: python residential_mortgage/02_portfolio_analytics/17_survivorship.py [--sample]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import module2_common as c  # noqa: E402


def run_survivorship(marts: object, src_prefix: str, sample_filter: bool = False) -> int:
    """Measure late-acquisition volume and survival differences per cohort."""
    check = c.Checker("17_survivorship: survivorship and left-truncation")
    where_l = c.scope(sample_filter, prefix=src_prefix)

    df_acq = c.q(marts, f"""
        WITH l AS (
            SELECT
                acquisition_quarter,
                orig_date,
                CAST(orig_upb AS DOUBLE) AS orig_upb,
                make_date(
                    CAST(substr(acquisition_quarter, 1, 4) AS INTEGER),
                    (CAST(substr(acquisition_quarter, 6, 1) AS INTEGER) - 1) * 3 + 1,
                    1
                ) AS acq_q_start
            FROM {src_prefix}loans_table
            WHERE {where_l}
        )
        SELECT
            acquisition_quarter,
            'acquisition_seasoning'::VARCHAR AS cohort_metric,
            count(*)::BIGINT AS loans,
            COALESCE(sum(orig_upb), 0.0) AS orig_upb_total,
            count(*) FILTER (WHERE datediff('month', orig_date, acq_q_start) > 3)::BIGINT AS seasoned_gt3m_loans,
            count(*) FILTER (WHERE datediff('month', orig_date, acq_q_start) > 12)::BIGINT AS seasoned_gt12m_loans,
            count(*) FILTER (WHERE datediff('month', orig_date, acq_q_start) > 24)::BIGINT AS seasoned_gt24m_loans,
            COALESCE(sum(orig_upb) FILTER (WHERE datediff('month', orig_date, acq_q_start) > 3), 0.0) AS seasoned_gt3m_upb,
            median(GREATEST(datediff('month', orig_date, acq_q_start), 0))::DOUBLE AS median_seasoning_months,
            max(GREATEST(datediff('month', orig_date, acq_q_start), 0))::DOUBLE AS max_seasoning_months
        FROM l
        GROUP BY 1, 2
    """)

    # Compare seasoned vs unseasoned default rates at 36m & 60m from vintage_curves_mart
    vc_comp = c.q(marts, """
        SELECT
            cohort_quarter AS acquisition_quarter,
            'cif_36m_' || seasoned_bucket AS cohort_metric,
            sum(at_risk)::BIGINT AS loans,
            0.0::DOUBLE AS orig_upb_total,
            0::BIGINT AS seasoned_gt3m_loans,
            0::BIGINT AS seasoned_gt12m_loans,
            0::BIGINT AS seasoned_gt24m_loans,
            0.0::DOUBLE AS seasoned_gt3m_upb,
            avg(cif_default) FILTER (WHERE mob = 36)::DOUBLE AS median_seasoning_months,
            max(cif_default)::DOUBLE AS max_seasoning_months
        FROM vintage_curves_mart
        WHERE cohort_type = 'acquisition_quarter' AND mob <= 36
        GROUP BY 1, 2
    """)

    out = pd.concat([df_acq, vc_comp], ignore_index=True)
    if not out.empty:
        out["late_share"] = np.where(
            out["cohort_metric"] == "acquisition_seasoning",
            out["seasoned_gt3m_loans"] / out["loans"].clip(lower=1),
            0.0,
        )
    c.write_df(marts, "survivorship_mart", out, ["acquisition_quarter", "cohort_metric"])

    check.key(marts, "survivorship_mart", ["acquisition_quarter", "cohort_metric"])
    acq_only = out[out["cohort_metric"] == "acquisition_seasoning"]
    if not acq_only.empty:
        tot_s = float(acq_only["seasoned_gt3m_loans"].sum() / max(acq_only["loans"].sum(), 1))
        print(f"  seasoned >3m at acquisition across book: {tot_s:.2%}", flush=True)
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Survivorship and left-truncation sizing.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    rc = run_survivorship(marts, sp, sample_filter=args.sample)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
