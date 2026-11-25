"""Default outcomes, economic net loss, cured-modification loss and triangle (Stage D, script 11).

Fixes all design review C3 defects:
- Scans loan_monthly_core per acquisition_quarter across [default_month - 12m, end_month]
  for default loans to capture BOTH cured-modification amounts (mod_non_interest_upb,
  principal_forgiveness) AND pre-default 6m/12m EAD balances cleanly.
- Credit-exit net_loss uses upb_at_removal (= balance_at_default - workout_principal_recovery)
  plus estimated accrued interest (months_behind * (note_rate / 1200) * balance_at_default),
  plus 5 cost fields, minus 4 proceed fields; foreclosure_writeoff kept separate.
- forced_sale_discount strictly restricted to liquidations ('02','03','09') with
  net_sales_proceeds > 0 and V_{indexed,sale} > 0 (never maps NULL proceeds to 100%).
- Observable upper-left loss_development_mart (default_month + lag <= 2025-12-01) with
  120+ overflow bucket so resolved + unresolved balances match cohort total identically.

Outputs: default_outcomes_mart, loss_development_mart, recovery_summary_mart, 11_loss_severity.png.
Run: python residential_mortgage/02_portfolio_analytics/scripts/11_default_outcomes.py [--full]
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


def run_default_outcomes(
    marts: object,
    src_prefix: str,
    core_files: list[Path],
    outputs_dir: Path,
    dataset_end_iso: str = "2025-12-01",
) -> int:
    """Resolve post-default cashflows, cured modification losses, FSD and upper-left dev triangle."""
    t0 = time.time()
    check = c.Checker("11_default_outcomes: workout net loss, FSD and loss development triangle")

    marts.execute(ltv_mod.build_hpi_lookup_sql(src_prefix))
    marts.execute("DROP TABLE IF EXISTS default_outcomes_mart")
    marts.execute("""
        CREATE TABLE default_outcomes_mart (
            loan_id VARCHAR,
            acquisition_quarter VARCHAR,
            default_month DATE,
            re_default_number INTEGER,
            era VARCHAR,
            end_month DATE,
            end_reason VARCHAR,
            outcome_category VARCHAR,
            duration_months INTEGER,
            balance_at_default DECIMAL(12, 2),
            upb_6m_prior DECIMAL(12, 2),
            upb_12m_prior DECIMAL(12, 2),
            upb_at_exit_or_cure DECIMAL(12, 2),
            workout_principal_recovery DECIMAL(12, 2),
            estimated_accrued_interest DECIMAL(12, 2),
            total_costs DECIMAL(12, 2),
            total_proceeds DECIMAL(12, 2),
            net_loss DECIMAL(12, 2),
            loss_rate DOUBLE,
            foreclosure_writeoff_reported DECIMAL(12, 2),
            mod_non_interest_upb_max DECIMAL(12, 2),
            principal_forgiveness_sum DECIMAL(12, 2),
            indexed_value_at_sale DOUBLE,
            forced_sale_discount DOUBLE,
            ltv_at_default DOUBLE,
            hpi_change_default_to_sale_pct DOUBLE,
            foreclosure_date DATE,
            disposition_date DATE,
            months_default_to_foreclosure INTEGER,
            months_default_to_sale INTEGER,
            property_state VARCHAR
        )
    """)

    for idx, f in enumerate(core_files, 1):
        quarter = f.stem
        fp = str(f).replace("\\", "/")
        marts.execute(f"""
            INSERT INTO default_outcomes_mart
            WITH max_hq AS (SELECT max(quarter_date) AS max_qd FROM _hpi_q),
            ev AS (
                SELECT *, {c.era_case('default_month')} AS era
                FROM default_events_mart
                WHERE acquisition_quarter = '{quarter}'
            ),
            ev_span AS (
                SELECT
                    e.loan_id,
                    e.default_month,
                    e.re_default_number,
                    max(CAST(m.mod_non_interest_upb AS DOUBLE)) AS mod_non_interest_upb_max,
                    COALESCE(sum(CAST(m.principal_forgiveness AS DOUBLE)), 0.0) AS principal_forgiveness_sum,
                    max(CASE WHEN m.reporting_period = e.default_month THEN CAST(m.current_rate AS DOUBLE) END) AS rate_at_default,
                    max(CASE WHEN m.reporting_period = e.default_month - INTERVAL 6 MONTH THEN CAST(m.current_upb AS DOUBLE) END) AS upb_6m_prior,
                    max(CASE WHEN m.reporting_period = e.default_month - INTERVAL 12 MONTH THEN CAST(m.current_upb AS DOUBLE) END) AS upb_12m_prior,
                    max(CASE WHEN m.reporting_period = e.end_month THEN CAST(m.current_upb AS DOUBLE) END) AS upb_at_end_row
                FROM ev e
                JOIN read_parquet('{fp}') m
                  ON m.loan_id = e.loan_id
                 AND m.reporting_period BETWEEN e.default_month - INTERVAL 12 MONTH AND e.end_month
                GROUP BY 1, 2, 3
            ),
            joined AS (
                SELECT
                    e.*,
                    COALESCE(es.rate_at_default, CAST(lt.note_rate AS DOUBLE), 0.0) AS eff_rate,
                    es.upb_6m_prior,
                    es.upb_12m_prior,
                    es.upb_at_end_row,
                    COALESCE(es.mod_non_interest_upb_max, 0.0) AS mod_non_int_max,
                    COALESCE(es.principal_forgiveness_sum, 0.0) AS prin_forg_sum,
                    w.zero_balance_code AS w_zbc,
                    CAST(w.upb_at_removal AS DOUBLE) AS w_upb_removal,
                    COALESCE(CAST(w.foreclosure_costs AS DOUBLE), 0.0)
                      + COALESCE(CAST(w.preservation_repair_costs AS DOUBLE), 0.0)
                      + COALESCE(CAST(w.asset_recovery_costs AS DOUBLE), 0.0)
                      + COALESCE(CAST(w.misc_holding_expenses AS DOUBLE), 0.0)
                      + COALESCE(CAST(w.holding_taxes AS DOUBLE), 0.0) AS total_costs,
                    COALESCE(CAST(w.net_sales_proceeds AS DOUBLE), 0.0)
                      + COALESCE(CAST(w.credit_enhancement_proceeds AS DOUBLE), 0.0)
                      + COALESCE(CAST(w.repurchase_make_whole_proceeds AS DOUBLE), 0.0)
                      + COALESCE(CAST(w.other_foreclosure_proceeds AS DOUBLE), 0.0) AS total_proceeds,
                    CAST(w.net_sales_proceeds AS DOUBLE) AS net_sales_proceeds,
                    CAST(w.foreclosure_writeoff AS DOUBLE) AS foreclosure_writeoff_rep,
                    w.foreclosure_date,
                    w.disposition_date,
                    lov.property_state,
                    lov.value_at_origination,
                    lov.hpi_orig,
                    COALESCE(h_def.hpi_sa, hn_def.hpi_sa) AS hpi_def,
                    COALESCE(h_sale.hpi_sa, hn_sale.hpi_sa) AS hpi_sale
                FROM ev e
                LEFT JOIN ev_span es
                  ON es.loan_id = e.loan_id AND es.default_month = e.default_month AND es.re_default_number = e.re_default_number
                LEFT JOIN workout_exit_cashflows_mart w
                  ON w.loan_id = e.loan_id AND w.reporting_period = e.end_month
                JOIN {src_prefix}loans_table lt
                  ON lt.loan_id = e.loan_id AND lt.acquisition_quarter = '{quarter}'
                LEFT JOIN loan_origination_value_mart lov
                  ON lov.loan_id = e.loan_id
                LEFT JOIN _hpi_q h_def
                  ON h_def.state = lov.property_state
                 AND h_def.quarter_date = LEAST(GREATEST(date_trunc('quarter', e.default_month)::DATE, DATE '2000-01-01'), (SELECT max_qd FROM max_hq))
                LEFT JOIN (SELECT quarter_date, avg(hpi_sa) AS hpi_sa FROM _hpi_q WHERE is_territory GROUP BY 1) hn_def
                  ON hn_def.quarter_date = LEAST(GREATEST(date_trunc('quarter', e.default_month)::DATE, DATE '2000-01-01'), (SELECT max_qd FROM max_hq))
                LEFT JOIN _hpi_q h_sale
                  ON h_sale.state = lov.property_state
                 AND h_sale.quarter_date = LEAST(GREATEST(date_trunc('quarter', COALESCE(w.disposition_date, e.end_month))::DATE, DATE '2000-01-01'), (SELECT max_qd FROM max_hq))
                LEFT JOIN (SELECT quarter_date, avg(hpi_sa) AS hpi_sa FROM _hpi_q WHERE is_territory GROUP BY 1) hn_sale
                  ON hn_sale.quarter_date = LEAST(GREATEST(date_trunc('quarter', COALESCE(w.disposition_date, e.end_month))::DATE, DATE '2000-01-01'), (SELECT max_qd FROM max_hq))
            ),
            calc AS (
                SELECT
                    *,
                    CASE
                        WHEN end_reason = 'end of data' THEN 'unresolved'
                        WHEN end_reason = 'cured' AND (mod_non_int_max > 0.0 OR prin_forg_sum > 0.0 OR trigger_type LIKE '%restructuring%' OR upgraded_by_restructuring) THEN 'cured with modification'
                        WHEN end_reason = 'cured' THEN 'cured without loss'
                        ELSE end_reason
                    END AS outcome_category,
                    datediff('month', default_month, end_month) AS duration_months,
                    COALESCE(w_upb_removal, upb_at_end_row, CAST(balance_at_default AS DOUBLE)) AS exit_or_cure_upb,
                    CASE
                        WHEN end_reason = 'credit exit'
                        THEN COALESCE(months_behind_at_default, 0) * (eff_rate / 1200.0) * CAST(balance_at_default AS DOUBLE)
                        ELSE 0.0
                    END AS est_accrued_int,
                    CASE
                        WHEN value_at_origination > 0 AND hpi_orig > 0 AND hpi_def > 0
                        THEN value_at_origination * hpi_def / hpi_orig ELSE NULL
                    END AS val_def,
                    CASE
                        WHEN value_at_origination > 0 AND hpi_orig > 0 AND hpi_sale > 0
                        THEN value_at_origination * hpi_sale / hpi_orig ELSE NULL
                    END AS val_sale
                FROM joined
            )
            SELECT
                loan_id,
                acquisition_quarter,
                default_month,
                re_default_number,
                era,
                end_month,
                end_reason,
                outcome_category,
                duration_months::INTEGER,
                CAST(balance_at_default AS DECIMAL(12, 2)),
                CAST(upb_6m_prior AS DECIMAL(12, 2)),
                CAST(upb_12m_prior AS DECIMAL(12, 2)),
                CAST(exit_or_cure_upb AS DECIMAL(12, 2)),
                CAST(CASE WHEN end_reason = 'credit exit' THEN CAST(balance_at_default AS DOUBLE) - exit_or_cure_upb ELSE 0.0 END AS DECIMAL(12, 2)) AS workout_principal_recovery,
                CAST(est_accrued_int AS DECIMAL(12, 2)),
                CAST(total_costs AS DECIMAL(12, 2)),
                CAST(total_proceeds AS DECIMAL(12, 2)),
                CAST(CASE WHEN end_reason = 'credit exit' THEN exit_or_cure_upb + est_accrued_int + total_costs - total_proceeds ELSE 0.0 END AS DECIMAL(12, 2)) AS net_loss,
                CASE
                    WHEN end_reason = 'credit exit' AND CAST(balance_at_default AS DOUBLE) > 0
                    THEN (exit_or_cure_upb + est_accrued_int + total_costs - total_proceeds) / CAST(balance_at_default AS DOUBLE)
                    ELSE NULL
                END AS loss_rate,
                CAST(COALESCE(foreclosure_writeoff_rep, 0.0) AS DECIMAL(12, 2)),
                CAST(mod_non_int_max AS DECIMAL(12, 2)),
                CAST(prin_forg_sum AS DECIMAL(12, 2)),
                val_sale,
                CASE
                    WHEN end_reason = 'credit exit' AND w_zbc IN ('02', '03', '09')
                         AND net_sales_proceeds IS NOT NULL AND net_sales_proceeds > 0 AND val_sale > 0
                    THEN 1.0 - net_sales_proceeds / val_sale
                    ELSE NULL
                END AS forced_sale_discount,
                CASE WHEN val_def > 0 THEN 100.0 * CAST(balance_at_default AS DOUBLE) / val_def ELSE NULL END AS ltv_at_default,
                CASE WHEN hpi_def > 0 AND hpi_sale > 0 THEN (hpi_sale / hpi_def - 1.0) * 100.0 ELSE NULL END AS hpi_change_default_to_sale_pct,
                foreclosure_date,
                disposition_date,
                CASE WHEN foreclosure_date IS NOT NULL THEN datediff('month', default_month, foreclosure_date)::INTEGER ELSE NULL END,
                CASE WHEN disposition_date IS NOT NULL THEN datediff('month', default_month, disposition_date)::INTEGER ELSE NULL END,
                property_state
            FROM calc
        """)
        if idx % 20 == 0 or idx == len(core_files):
            print(f"  [{idx:3d}/{len(core_files)}] resolved outcomes {quarter} ({time.time() - t0:.1f}s)", flush=True)

    # Observable upper-left loss development triangle (0..119, '120+', strictly observable <= dataset_end)
    marts.execute(f"""
        CREATE OR REPLACE TABLE loss_development_mart AS
        WITH cohort_tot AS (
            SELECT
                year(default_month)::INTEGER AS default_year,
                count(*)::BIGINT AS cohort_events,
                COALESCE(sum(CAST(balance_at_default AS DOUBLE)), 0.0) AS cohort_default_upb
            FROM default_outcomes_mart
            GROUP BY 1
        ),
        lags AS (
            SELECT unnest(range(0, 121))::INTEGER AS lag_num
        ),
        obs AS (
            SELECT
                c.default_year,
                CASE WHEN l.lag_num = 120 THEN '120+' ELSE lpad(l.lag_num::VARCHAR, 3, '0') END AS months_since_default,
                l.lag_num AS lag_sort,
                COALESCE(sum(CAST(d.net_loss AS DOUBLE)) FILTER (
                    WHERE d.outcome_category != 'unresolved'
                      AND (
                          (l.lag_num < 120 AND d.duration_months <= l.lag_num)
                          OR (l.lag_num = 120)
                      )
                ), 0.0) AS cum_net_loss,
                COALESCE(sum(CAST(d.balance_at_default AS DOUBLE)) FILTER (
                    WHERE d.outcome_category != 'unresolved'
                      AND (
                          (l.lag_num < 120 AND d.duration_months <= l.lag_num)
                          OR (l.lag_num = 120)
                      )
                ), 0.0) AS resolved_default_upb,
                COALESCE(sum(CAST(d.balance_at_default AS DOUBLE)) FILTER (
                    WHERE d.outcome_category = 'unresolved'
                       OR (l.lag_num < 120 AND d.duration_months > l.lag_num)
                ), 0.0) AS unresolved_default_upb,
                c.cohort_events,
                c.cohort_default_upb
            FROM cohort_tot c
            CROSS JOIN lags l
            JOIN default_outcomes_mart d ON year(d.default_month) = c.default_year
            WHERE make_date(c.default_year, 1, 1) + l.lag_num * INTERVAL 1 MONTH <= DATE '{dataset_end_iso}'
            GROUP BY 1, 2, 3, 7, 8
        )
        SELECT
            default_year,
            months_since_default,
            lag_sort,
            cum_net_loss,
            resolved_default_upb,
            unresolved_default_upb,
            cohort_events,
            cohort_default_upb,
            (resolved_default_upb + unresolved_default_upb) - cohort_default_upb AS conservation_diff_upb
        FROM obs
        ORDER BY default_year, lag_sort
    """)

    # Summary mart across era x state_group x ltv_band
    c.write_mart(
        marts,
        "recovery_summary_mart",
        """
        SELECT
            era,
            CASE WHEN property_state IN ('CA','FL','NY','IL','NJ','TX') THEN property_state ELSE 'OTHER' END AS state_group,
            CASE
                WHEN ltv_at_default IS NULL THEN 'unknown'
                WHEN ltv_at_default <= 70 THEN '<=70'
                WHEN ltv_at_default <= 90 THEN '70-90'
                WHEN ltv_at_default <= 100 THEN '90-100'
                ELSE '>100'
            END AS ltv_band,
            count(*)::BIGINT AS total_events,
            count(*) FILTER (WHERE outcome_category IN ('cured without loss', 'cured with modification', 'cured - paid off'))::BIGINT AS cured_events,
            count(*) FILTER (WHERE end_reason = 'credit exit')::BIGINT AS credit_exit_events,
            count(*) FILTER (WHERE outcome_category = 'unresolved')::BIGINT AS unresolved_events,
            COALESCE(sum(CAST(balance_at_default AS DOUBLE)) FILTER (WHERE end_reason = 'credit exit'), 0.0) AS credit_exit_default_upb,
            COALESCE(sum(CAST(net_loss AS DOUBLE)) FILTER (WHERE end_reason = 'credit exit'), 0.0) AS credit_exit_net_loss,
            avg(forced_sale_discount) FILTER (WHERE forced_sale_discount IS NOT NULL) AS mean_fsd,
            COALESCE(sum(CAST(principal_forgiveness_sum AS DOUBLE)), 0.0) AS forgiven_on_cures_and_exits
        FROM default_outcomes_mart
        GROUP BY 1, 2, 3
        """,
        ["era", "state_group", "ltv_band"],
    )

    # Chart (300 dpi): Credit-exit severity vs LTV at default band
    sev_df = c.q(marts, """
        SELECT ltv_band,
               sum(credit_exit_net_loss) / NULLIF(sum(credit_exit_default_upb), 0.0) * 100.0 AS sev_pct
        FROM recovery_summary_mart
        WHERE credit_exit_events > 0
        GROUP BY 1
    """)
    if not sev_df.empty:
        order = ["<=70", "70-90", "90-100", ">100", "unknown"]
        sev_df["ord"] = sev_df["ltv_band"].map(lambda x: order.index(x) if x in order else 99)
        sev_df = sev_df.sort_values("ord")
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        ax.bar(sev_df["ltv_band"], sev_df["sev_pct"], color="#0d366b", width=0.55)
        ax.set_title("Realised Credit-Exit Loss Rate by Indexed LTV Band at Default")
        ax.set_xlabel("Indexed LTV at Default (%)")
        ax.set_ylabel("UPB-Weighted Net Loss Severity (%)")
        c.save_chart(fig, c.script_out(outputs_dir, "11_default_outcomes") / "11_loss_severity.png")

    marts.execute("DROP TABLE IF EXISTS _hpi_q")
    max_cons_err = float(c.scalar(marts, "SELECT COALESCE(max(abs(conservation_diff_upb)), 0.0) FROM loss_development_mart") or 0.0)
    bad_fsd = int(c.scalar(marts, "SELECT count(*) FROM default_outcomes_mart WHERE end_reason != 'credit exit' AND forced_sale_discount IS NOT NULL") or 0)

    check.key(marts, "default_outcomes_mart", ["loan_id", "default_month", "re_default_number"])
    check.key(marts, "loss_development_mart", ["default_year", "months_since_default"])
    check.key(marts, "recovery_summary_mart", ["era", "state_group", "ltv_band"])
    check.add("development triangle conserves cohort default balance exactly", max_cons_err < 1.0, f"max_diff={max_cons_err:.4f}")
    check.add("forced sale discount computed strictly on property liquidations", bad_fsd == 0)
    return check.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Default outcomes, economic net loss and development triangle.")
    c.add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = c.resolve_paths(parse_args())
    marts = c.connect(args.marts, read_only=False)
    c.assert_scope_match(marts, args.sample)
    sp = c.attach_db(marts, args.db, "src")
    core_files = c.list_core_files(args.core_dir)
    rc = run_default_outcomes(marts, sp, core_files, args.outputs_dir)
    marts.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
