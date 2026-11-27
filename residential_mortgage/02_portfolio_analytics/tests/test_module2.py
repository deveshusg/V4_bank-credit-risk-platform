"""Synthetic known-answer unit test suite for Module 2 (unittest / pytest compatible).

Tests deterministic tiny fixtures matching docs/module_2/module-2-design.md Section 6.
Run directly without extra packages:
    .venv\\Scripts\\python.exe residential_mortgage\\02_portfolio_analytics\\tests\\test_module2.py
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

M2_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(M2_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(M2_SCRIPTS))

import module2_common as c  # noqa: E402

build_core = importlib.import_module("00_build_monthly_core")
audit_mod = importlib.import_module("01_data_audit")
def_mod = importlib.import_module("02_default_engine")
roll_mod = importlib.import_module("03_roll_rates")
em_mod = importlib.import_module("04_emergence_and_thresholds")
vin_mod = importlib.import_module("05_vintage_curves")
ltv_mod = importlib.import_module("06_current_ltv")
dr_mod = importlib.import_module("07_default_rate_history")
pop_mod = importlib.import_module("08_sample_population")
drv_mod = importlib.import_module("09_risk_drivers")
seg_mod = importlib.import_module("10_segmentation")
out_mod = importlib.import_module("11_default_outcomes")
forb_mod = importlib.import_module("12_forbearance")
eco_mod = importlib.import_module("13_economy_links")
cyc_mod = importlib.import_module("14_cycle_and_benchmarks")
mix_mod = importlib.import_module("15_portfolio_mix")
rep_mod = importlib.import_module("16_representativeness")
surv_mod = importlib.import_module("17_survivorship")
fnd_mod = importlib.import_module("18_portfolio_findings")


def _ym_list(start_ym: str, count: int) -> list[str]:
    y, m = map(int, start_ym.split("-"))
    out = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


class TestCommonAndMetadata(unittest.TestCase):
    def test_unique_key_rejects_duplicates_and_nulls(self) -> None:
        con = duckdb.connect(":memory:")
        df_dup = pd.DataFrame([
            {"loan_id": "L1", "month": "2020-01", "val": 1},
            {"loan_id": "L1", "month": "2020-01", "val": 2},
        ])
        with self.assertRaises(ValueError):
            c.write_df(con, "t_dup", df_dup, ["loan_id", "month"])

        df_null = pd.DataFrame([
            {"loan_id": "L1", "month": None, "val": 1},
        ])
        with self.assertRaises(ValueError):
            c.write_df(con, "t_null", df_null, ["loan_id", "month"])

        chk = c.Checker("dup check")
        con.execute("CREATE TABLE t_bad AS SELECT 'L1' AS loan_id, '2020-01' AS m UNION ALL SELECT 'L1', '2020-01'")
        self.assertFalse(chk.key(con, "t_bad", ["loan_id", "m"]))
        con.close()

    def test_scope_mismatch_rejection(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE build_metadata AS SELECT 'sample'::VARCHAR AS scope")
        with self.assertRaises(RuntimeError):
            c.assert_scope_match(con, sample_flag=False)
        c.assert_scope_match(con, sample_flag=True)
        con.close()


class TestStage0And01Audit(unittest.TestCase):
    def test_core_build_and_audit_known_answer_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw_pq = root / "2020Q1.parquet"
            core_pq = root / "core" / "2020Q1.parquet"
            src_db = root / "src.duckdb"
            marts_db = root / "marts.duckdb"
            out_dir = root / "outputs"

            # Raw 43-column style string rows covering:
            # L_PAYOFF: active then payoff '01' with total_principal = upb_at_removal (no double count!)
            # L_MASK: active masked 0.00 at age 1 -> unmasks at age 6 -> rep mod_non_interest_upb stock + capitalization
            # L_GAP: skips 2020-02 internal month -> re-ages 2 -> 0 cleanly flagged
            # L_CREDIT: credit exit '09' with costs and proceeds
            rows = [
                # L_PAYOFF: 2020-01 (100000), 2020-02 (99000), 2020-03 payoff ('01', current_upb=0, upb_at_removal=98500, total_principal=98500)
                ("L_PAYOFF", "012020", "S1", "4.0", "100000.00", "10", "350", "350", None, "00", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_PAYOFF", "022020", "S1", "4.0", "99000.00", "11", "349", "349", "1000.00", "00", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_PAYOFF", "032020", "S1", "4.0", "0.00", "12", "348", "0", "98500.00", "00", "N", "01", "032020", "98500.00", "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                # L_MASK: 2020-01 masked 0.00 (age 5), 2020-02 unmasked 50000 (age 6), 2020-03 mod_non_interest_upb stock 5000 repeated & +2000 capitalization
                ("L_MASK", "012020", "S1", "4.5", "0.00", "5", "355", "355", None, "00", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_MASK", "022020", "S1", "4.5", "50000.00", "6", "354", "354", None, "00", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_MASK", "032020", "S1", "4.5", "52000.00", "7", "353", "353", None, "00", "Y", None, None, None, "7", "7", None, None, "5000.00", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_MASK", "042020", "S1", "4.5", "51500.00", "8", "352", "352", None, "00", "Y", None, None, None, "7", "7", None, None, "5000.00", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                # L_GAP: 2020-01 (40000, dpd 2), skips 2020-02, returns 2020-03 (39500, dpd 0 -> not contiguous prev so not reaging), 2020-04 contiguous reaging check on L_REAGE below
                ("L_GAP", "012020", "S1", "5.0", "40000.00", "12", "348", "348", None, "02", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_GAP", "032020", "S1", "5.0", "39500.00", "14", "346", "346", None, "00", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_GAP", "042020", "S1", "5.0", "39000.00", "15", "345", "345", None, "02", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_GAP", "052020", "S1", "5.0", "38500.00", "16", "344", "344", None, "00", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                # L_CREDIT: 2020-01 active 60000 -> 2020-02 exit '09' with costs and proceeds
                ("L_CREDIT", "012020", "S1", "5.0", "60000.00", "20", "340", "340", None, "03", "N", None, None, None, "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
                ("L_CREDIT", "022020", "S1", "5.0", "0.00", "21", "339", "0", None, "04", "N", "09", "022020", "59500.00", "7", "7", None, None, None, None, "1200.00", "022020", "022020", "1500.00", "500.00", "200.00", "100.00", "50.00", "45000.00", "0.00", "0.00", "300.00", None, "Y"),
            ]
            cols = [
                "loan_id", "reporting_period", "servicer_name", "current_rate", "current_upb",
                "loan_age", "months_to_legal_maturity", "months_to_maturity", "total_principal",
                "delinquency_status", "modification_flag", "zero_balance_code", "zero_balance_date",
                "upb_at_removal", "borrower_assistance_plan", "alt_delinquency_resolution",
                "alt_delinquency_resolution_count", "total_deferral_amount", "mod_non_interest_upb",
                "principal_forgiveness", "foreclosure_writeoff", "foreclosure_date", "disposition_date",
                "foreclosure_costs", "preservation_repair_costs", "asset_recovery_costs",
                "misc_holding_expenses", "holding_taxes", "net_sales_proceeds",
                "credit_enhancement_proceeds", "repurchase_make_whole_proceeds",
                "other_foreclosure_proceeds", "last_paid_date", "repurchase_make_whole_flag",
            ]
            raw_df = pd.DataFrame(rows, columns=cols)
            s_con = duckdb.connect(str(src_db))
            s_con.register("r_df", raw_df)
            s_con.execute(f"COPY r_df TO '{str(raw_pq).replace(chr(92), '/')}' (FORMAT PARQUET)")
            s_con.execute("""
                CREATE TABLE loans_table AS
                SELECT DISTINCT loan_id, '2020Q1'::VARCHAR AS acquisition_quarter,
                       80 AS orig_ltv, 4.5 AS note_rate, 100000.0 AS orig_upb,
                       360 AS loan_term, DATE '2019-12-01' AS orig_date, DATE '2020-01-01' AS first_payment_date,
                       34 AS dti, 740 AS credit_score
                FROM r_df
            """)
            s_con.close()

            m_con = c.connect(marts_db, read_only=False)
            sp = c.attach_db(m_con, src_db, "src")
            build_core.init_workout_table(m_con)
            info, _ = build_core.build_quarter_core(m_con, raw_pq, "2020Q1", core_pq)
            self.assertTrue(info["ok"])

            rc = audit_mod.run_audit(m_con, sp, [core_pq], out_dir, dataset_end_iso="2020-05-01")
            self.assertEqual(rc, 0)
            rc_def = def_mod.run_default_engine(m_con, sp, [core_pq])
            self.assertEqual(rc_def, 0)
            self.assertEqual(int(c.scalar(m_con, "SELECT count(*) FROM default_events_mart")), 2)  # L_MASK & L_CREDIT
            self.assertEqual(int(c.scalar(m_con, "SELECT count(*) FROM default_status_monthly")), 4)  # L_MASK 2m + L_CREDIT 2m

            rf = m_con.execute("SELECT * FROM balance_rollforward_mart ORDER BY reporting_period").df()
            # Every month count residual == 0 and unexplained_upb == 0.0 (all movements explicitly captured)
            self.assertTrue((rf["count_residual"] == 0).all())
            self.assertTrue((rf["unexplained_upb"].abs() < 1e-6).all())

            # mod_non_interest_upb 5000 must NOT inflate unexplained balance; payoff 98500 not double-counted
            mar = rf[rf["reporting_period"].astype(str).str.startswith("2020-03")].iloc[0]
            self.assertAlmostEqual(float(mar["payoff_upb"]), 98500.0)
            self.assertAlmostEqual(float(mar["cap_added_upb"]), 2000.0)
            self.assertAlmostEqual(float(mar["reported_principal_paid_upb"]), 0.0)  # '01' row excluded!

            # Re-aging on L_GAP (2020-04 dpd=02 -> 2020-05 dpd=00 without mod/deferral) == 1
            reage = float(
                c.scalar(
                    m_con,
                    "SELECT value FROM data_plausibility_mart WHERE metric_name='reaging_events_total' AND year='ALL'",
                )
            )
            self.assertEqual(int(reage), 1)
            gap_loans = float(
                c.scalar(
                    m_con,
                    "SELECT value FROM data_plausibility_mart WHERE metric_name='gap_loans' AND year='ALL'",
                )
            )
            self.assertEqual(int(gap_loans), 1)
            m_con.close()


class Test02DefaultEngineStateMachine(unittest.TestCase):
    def _run(
        self,
        start_ym: str,
        mb: list[int | None],
        plans: list[str] | None = None,
        mod: list[str] | None = None,
        zbc: list[str] | None = None,
        upb: list[float | None] | None = None,
        upb_rem: list[float | None] | None = None,
        loan_age: list[int | None] | None = None,
        apply_covid: bool = True,
    ) -> list[dict]:
        n = len(mb)
        months = _ym_list(start_ym, n)
        return def_mod.run_loan_records(
            months=months,
            mb=mb,
            plans=plans or ["N"] * n,
            mod=mod or ["N"] * n,
            zbc=zbc or [""] * n,
            upb=upb or [100000.0] * n,
            upb_removal=upb_rem or [None] * n,
            loan_age=loan_age or [12 + i for i in range(n)],
            mob_list=[12 + i for i in range(n)],
            orig_upb=120000.0,
            note_rate=6.0,
            loan_term=360,
            apply_covid_hold=apply_covid,
        )

    def test_pure_arrears_cure_and_strict_1m_restart(self) -> None:
        # 3 -> 0, 0, 1 (RESTARTS clean=0!), 0, 0, 0 -> cures on final month (idx 6)
        evs = self._run("2018-01", [3, 0, 0, 1, 0, 0, 0])
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["end_reason"], "cured")
        self.assertEqual(evs[0]["cure_month"], "2018-07")
        self.assertEqual(evs[0]["probation_months"], 3)

    def test_restructuring_during_arrears_upgrades_probation_to_12m(self) -> None:
        # Arrears trigger at idx 0 (probation=3), clean 0, 0, then N->Y at idx 3 upgrades to 12m + resets clean=0!
        # With only 11 clean months after N->Y (len=15), it must NOT cure early under 3m rule.
        mb = [3, 0, 0] + [0] * 12
        mod = ["N", "N", "N"] + ["Y"] * 12
        evs = self._run("2018-01", mb, mod=mod)
        self.assertEqual(len(evs), 1)
        self.assertTrue(evs[0]["upgraded_by_restructuring"])
        self.assertEqual(evs[0]["probation_months"], 12)
        self.assertEqual(evs[0]["end_reason"], "end of data")

        # Adding 12th clean month after N->Y cures cleanly on 2019-04.
        evs2 = self._run("2018-01", [3, 0, 0] + [0] * 13, mod=["N", "N", "N"] + ["Y"] * 13)
        self.assertEqual(evs2[0]["end_reason"], "cured")
        self.assertEqual(evs2[0]["cure_month"], "2019-04")

    def test_double_flip_y_n_y_and_row0_y(self) -> None:
        # Y -> N -> Y must trigger only ONCE
        evs = self._run("2018-01", [0] * 16, mod=["N", "Y", "N", "Y"] + ["Y"] * 12)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["default_month"], "2018-02")
        self.assertEqual(evs[0]["probation_months"], 12)
        self.assertEqual(evs[0]["end_reason"], "cured")

        # Late-acquired row 0 already 'Y' -> no fake retroactive restructuring trigger
        evs_late = self._run("2018-01", [0, 0, 0], mod=["Y", "Y", "Y"])
        self.assertEqual(len(evs_late), 0)

    def test_simultaneous_restruct_and_arrears(self) -> None:
        evs = self._run("2018-01", [0, 3] + [0] * 12, mod=["N", "Y"] + ["Y"] * 12)
        self.assertEqual(evs[0]["trigger_type"], "restructuring+arrears")
        self.assertEqual(evs[0]["probation_months"], 12)
        self.assertEqual(evs[0]["end_reason"], "cured")

    def test_xx_pause_and_redefault(self) -> None:
        # 3, 0, XX (pauses at clean=1), 0, 0 (cures on 2018-05!), then new 3 -> re_default_number=2
        evs = self._run("2018-01", [3, 0, None, 0, 0, 0, 3, 0, 0, 0])
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0]["cure_month"], "2018-05")
        self.assertEqual(evs[1]["re_default_number"], 2)
        self.assertEqual(evs[1]["default_month"], "2018-07")
        self.assertEqual(evs[1]["cure_month"], "2018-10")

    def test_cumulative_6m_covid_cap_and_7_sentinel_and_precovid(self) -> None:
        # L10: enters 'F' 2020-05 for 4m (held=0), exits 'N' 2020-09..10 (0), misses in 2020-11 (dpd=1, 'N'),
        # re-enters 'T' in 2020-12 (dpd=2 -> held 1, used=5), 2021-01 (dpd=3 -> held 1, used=6),
        # 2021-02 (dpd=4, budget exhausted -> triggers 2021-02!)
        plans = ["N", "F", "F", "F", "F", "N", "N", "N", "T", "T", "T"]
        mb = [0, 1, 2, 3, 4, 0, 0, 1, 2, 3, 4]
        evs = self._run("2020-04", mb, plans=plans)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["default_month"], "2021-02")

        # As-reported triggers earlier in 2020-07 (dpd=3)
        evs_raw = self._run("2020-04", mb, plans=plans, apply_covid=False)
        self.assertEqual(evs_raw[0]["default_month"], "2020-07")

        # '7' sentinel gets ZERO COVID hold
        evs_7 = self._run("2020-04", [0, 1, 2, 3], plans=["7", "7", "7", "7"])
        self.assertEqual(evs_7[0]["default_month"], "2020-07")

        # Pre-COVID 'F' starting 2020-02 stays unheld across 2020-03+
        evs_pre = self._run("2020-02", [1, 2, 3], plans=["F", "F", "F"])
        self.assertEqual(evs_pre[0]["default_month"], "2020-04")

    def test_jul2021_cliff_and_probation_pause_during_hold(self) -> None:
        # Loan defaults on 2020-03 (dpd=3), then enters 'F' in 2020-04..06 with dpd=0 -> probation MUST PAUSE under hold, not cure!
        evs_pause = self._run("2020-03", [3, 0, 0, 0, 0, 0, 0], plans=["N", "F", "F", "F", "N", "N", "N"])
        self.assertEqual(evs_pause[0]["cure_month"], "2020-09")

        # Jul 2021 cliff: starts 'F' in 2021-03 (5m used by 2021-07), triggers 2021-08 when cap cutoff ends
        evs_jul = self._run("2021-02", [0, 1, 2, 3, 4, 5, 6], plans=["N", "F", "F", "F", "F", "F", "F"])
        self.assertEqual(evs_jul[0]["default_month"], "2021-08")

    def test_credit_exit_and_masked_balance_at_default(self) -> None:
        # Direct credit exit with current_upb=0, upb_at_removal=85000
        evs_ce = self._run("2019-01", [0, 1], zbc=["", "09"], upb=[90000.0, 0.0], upb_rem=[None, 85000.0])
        self.assertEqual(evs_ce[0]["trigger_type"], "credit_exit")
        self.assertEqual(evs_ce[0]["end_reason"], "credit exit")
        self.assertAlmostEqual(evs_ce[0]["balance_at_default"], 85000.0)

        # Masked month-2 early default (current_upb=0.00, age=2, orig_upb=120000, 6%, 360m, mob=2 -> k=3)
        evs_mk = def_mod.run_loan_records(
            months=["2018-01", "2018-02", "2018-03", "2018-04"],
            mb=[0, 1, 2, 3],
            plans=["N"] * 4,
            mod=["N"] * 4,
            zbc=[""] * 4,
            upb=[0.0, 0.0, 0.0, 0.0],
            upb_removal=[None] * 4,
            loan_age=[0, 1, 2, 3],
            mob_list=[0, 1, 2, 3],
            orig_upb=120000.0,
            note_rate=6.0,
            loan_term=360,
        )
        self.assertTrue(evs_mk[0]["balance_masked_flag"])
        expected_bal = c.scheduled_upb(120000.0, 6.0, 360, 3)
        self.assertAlmostEqual(evs_mk[0]["balance_at_default"], expected_bal)
        self.assertGreater(evs_mk[0]["balance_at_default"], 119000.0)


class TestStageBToGFormulasAndPipeline(unittest.TestCase):
    def test_aalen_johansen_exact_uncensored_and_drawdown(self) -> None:
        # 10-loan uncensored cohort over 3 months: m0 (10 at risk, 1 def, 1 pay -> 0.1, 0.1),
        # m1 (8 at risk, 1 def, 0 pay -> S=0.8 * (1 - 1/8) = 0.7; CIF_def = 0.1 + 0.8*(1/8)=0.2!)
        df_toy = pd.DataFrame([
            {"mob": 0, "at_risk": 10, "defaults": 1, "payoffs": 1},
            {"mob": 1, "at_risk": 8, "defaults": 1, "payoffs": 0},
            {"mob": 2, "at_risk": 7, "defaults": 0, "payoffs": 2},
        ])
        aj = vin_mod.compute_aalen_johansen(df_toy)
        self.assertAlmostEqual(float(aj.loc[aj["mob"] == 2, "cif_default"].iloc[0]), 2.0 / 10.0, places=6)
        self.assertAlmostEqual(float(aj.loc[aj["mob"] == 2, "cif_payoff"].iloc[0]), 3.0 / 10.0, places=6)
        self.assertAlmostEqual(float(aj.loc[aj["mob"] == 2, "survival_prob"].iloc[0]), 5.0 / 10.0, places=6)

        # Peak-to-trough must catch 2007->2011 -30% crash even when 2025 hits new all-time high
        hpi_toy = pd.DataFrame([
            {"state": "NV", "quarter_date": date(2005, 1, 1), "house_price_index_sa": 150.0},
            {"state": "NV", "quarter_date": date(2007, 1, 1), "house_price_index_sa": 200.0},
            {"state": "NV", "quarter_date": date(2011, 1, 1), "house_price_index_sa": 140.0},
            {"state": "NV", "quarter_date": date(2025, 1, 1), "house_price_index_sa": 300.0},
        ])
        ep = ltv_mod.compute_drawdown_episodes(hpi_toy)
        self.assertEqual(len(ep), 1)
        self.assertAlmostEqual(float(ep.iloc[0]["fall_pct"]), 30.0, places=4)
        self.assertTrue(bool(ep.iloc[0]["exceeds_25pct_min"]))
        self.assertTrue(bool(ep.iloc[0]["exceeds_10pct_art124d"]))
        self.assertFalse(bool(ep.iloc[0]["exceeds_40pct_ref"]))

    def test_vasicek_rho_quadrature_handles_zero_year(self) -> None:
        import numpy as np
        # Plant annual default counts across 20 years including zero-default years
        rng = np.random.default_rng(7)
        n_y = np.full(20, 5000)
        z = rng.normal(0.0, 1.0, size=20)
        rho_true = 0.15
        p_base = 0.01
        thresh = c.inv_normal_cdf(p_base)
        p_cond = np.array([c.normal_cdf((thresh - np.sqrt(rho_true) * zi) / np.sqrt(1.0 - rho_true)) for zi in z])
        k_y = rng.binomial(n_y, p_cond)
        k_y[0] = 0  # Ensure exact zero-event year doesn't break quadrature MLE
        p_hat, rho_hat, _ = dr_mod.fit_vasicek_rho(k_y, n_y)
        self.assertGreater(p_hat, 0.0)
        self.assertGreater(rho_hat, 0.04)
        self.assertLess(rho_hat, 0.35)

    def test_end_to_end_pipeline_00_through_18(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw_pq = root / "2020Q1.parquet"
            core_dir = root / "core"
            core_pq = core_dir / "2020Q1.parquet"
            src_db = root / "src.duckdb"
            marts_db = root / "marts.duckdb"
            out_dir = root / "outputs"
            out_md = root / "findings.md"

            # Synthetic 6-loan multi-month dataset spanning Dec 2019 (pre-2000 clamp tested separately) through Dec 2022
            # covering: L1 cured mod loss, L2 credit exit '09' (FSD + net loss), L3 COVID 'F' + deferral 'C' sticky rows,
            # L4 payoff '01', L5 clean performing benchmark, L6 invalid orig_ltv=0 in territory 'PR'.
            raw_rows = []
            # Build 2020-01 .. 2022-12 (36 months)
            yms = _ym_list("2020-01", 36)
            for idx, ym in enumerate(yms):
                rp_str = f"{ym[5:7]}{ym[:4]}"
                # L1: defaults 2020-04 via N->Y mod with mod_non_interest_upb=1500 & forgiveness=200, stays clean -> cures!
                raw_rows.append(("L1", rp_str, "S1", "4.0", f"{100000.0 - 500.0 * idx:.2f}", str(idx), str(360 - idx), str(360 - idx),
                                 "500.00", "00" if idx != 2 else "01", "N" if idx < 3 else "Y", None, None, None, "7", "7", None, None,
                                 "1500.00" if idx >= 3 else None, "200.00" if idx == 3 else None, None, None, None, None, None, None, None, None, None, None, None, None, None, None))
                # L2: arrears default 2020-03 (dpd=3), exits '09' on 2020-05 with proceeds 60000 & costs 2000
                if idx <= 4:
                    zbc = "09" if idx == 4 else None
                    raw_rows.append(("L2", rp_str, "S1", "5.0", "80000.00" if idx < 4 else "0.00", str(12 + idx), "340", "340",
                                     None, f"{min(idx+1, 5):02d}", "N", zbc, rp_str if zbc else None, "79000.00" if zbc else None,
                                     "7", "7", None, None, None, None, "15000.00" if zbc else None,
                                     rp_str if zbc else None, rp_str if zbc else None,
                                     "2000.00" if zbc else None, None, None, None, None, "60000.00" if zbc else None,
                                     None, None, None, None, None))
                # L3: enters COVID 'F' 2020-05..2020-08 (dpd=1..4 held), deferral 'C' in 2020-09 persisting through 2022-12!
                dpd_3 = "00"
                plan_3 = "7"
                def_3 = "7"
                def_cnt_3 = None
                if 4 <= idx <= 7:
                    plan_3 = "F"
                    dpd_3 = f"{idx - 3:02d}"
                elif idx >= 8:
                    def_3 = "C"
                    def_cnt_3 = "1"
                raw_rows.append(("L3", rp_str, "S2", "4.25", "150000.00", str(12 + idx), "340", "340",
                                 None, dpd_3, "N", None, None, None, plan_3, def_3, def_cnt_3, "5000.00" if idx >= 8 else None,
                                 None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None))
                # L4: payoff '01' in 2021-06
                if idx <= 17:
                    zbc4 = "01" if idx == 17 else None
                    l4_bal = f"{120000.0 - 100.0 * idx:.2f}"
                    raw_rows.append(("L4", rp_str, "S1", "4.0", l4_bal if idx < 17 else "0.00", str(12 + idx), "340", "340",
                                     l4_bal if zbc4 else "100.00", "00", "N", zbc4, rp_str if zbc4 else None, l4_bal if zbc4 else None,
                                     "7", "7", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None))
                # L5: clean performing benchmark all 36 months (with bounce 0->1->0 twice in 2020-2021)
                dpd_5 = "01" if idx in (2, 5) else "00"
                raw_rows.append(("L5", rp_str, "S2", "4.5", "200000.00", str(24 + idx), "330", "330",
                                 None, dpd_5, "N", None, None, None, "7", "7", None, None,
                                 None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None))
                # L6: Puerto Rico territory loan with orig_ltv=0 (must skip divide by zero cleanly!)
                raw_rows.append(("L6", rp_str, "S1", "4.5", "90000.00", str(12 + idx), "340", "340",
                                 None, "00", "N", None, None, None, "7", "7", None, None,
                                 None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None))

            cols = [
                "loan_id", "reporting_period", "servicer_name", "current_rate", "current_upb",
                "loan_age", "months_to_legal_maturity", "months_to_maturity", "total_principal",
                "delinquency_status", "modification_flag", "zero_balance_code", "zero_balance_date",
                "upb_at_removal", "borrower_assistance_plan", "alt_delinquency_resolution",
                "alt_delinquency_resolution_count", "total_deferral_amount", "mod_non_interest_upb",
                "principal_forgiveness", "foreclosure_writeoff", "foreclosure_date", "disposition_date",
                "foreclosure_costs", "preservation_repair_costs", "asset_recovery_costs",
                "misc_holding_expenses", "holding_taxes", "net_sales_proceeds",
                "credit_enhancement_proceeds", "repurchase_make_whole_proceeds",
                "other_foreclosure_proceeds", "last_paid_date", "repurchase_make_whole_flag",
            ]
            raw_df = pd.DataFrame(raw_rows, columns=cols)
            s_con = duckdb.connect(str(src_db))
            s_con.register("r_df", raw_df)
            s_con.execute(f"COPY r_df TO '{str(raw_pq).replace(chr(92), '/')}' (FORMAT PARQUET)")
            s_con.execute("""
                CREATE TABLE loans_table AS
                SELECT * FROM (VALUES
                    ('L1', '2020Q1', 'R', 'SellerA', 4.0, 100000.0, 360, DATE '2019-12-01', DATE '2020-01-01', 80, 80, 1, 35, 720, NULL, 'N', 'P', 'SF', 1, 'P', 'CA', '31080', '900', 0, 'FRM', 'N', 'N', NULL, NULL, '7', 'N', 'A', 'N', 'N', 720),
                    ('L2', '2020Q1', 'B', 'SellerA', 5.0, 90000.0, 360, DATE '2019-01-01', DATE '2019-02-01', 92, 92, 1, 45, 640, NULL, 'Y', 'P', 'SF', 1, 'P', 'NV', '00000', '891', 25, 'FRM', 'N', 'N', NULL, NULL, '7', 'N', 'A', 'N', 'N', 640),
                    ('L3', '2020Q1', 'C', 'SellerB', 4.25, 160000.0, 360, DATE '1999-06-01', DATE '1999-07-01', 75, 75, 2, 32, 760, NULL, 'N', 'R', 'SF', 1, 'I', 'TX', '19100', '750', 0, 'FRM', 'N', 'N', NULL, NULL, '7', 'N', 'A', 'N', 'N', 760),
                    ('L4', '2020Q1', 'R', 'SellerA', 4.0, 130000.0, 360, DATE '2019-01-01', DATE '2019-02-01', 70, 70, 1, 28, 790, NULL, 'N', 'C', 'SF', 1, 'P', 'FL', '33100', '331', 0, 'FRM', 'N', 'N', NULL, NULL, '7', 'N', 'A', 'N', 'N', 790),
                    ('L5', '2020Q1', 'C', 'SellerB', 4.5, 210000.0, 360, DATE '2018-01-01', DATE '2018-02-01', 65, 65, 2, 38, 710, NULL, 'N', 'P', 'SF', 1, 'P', 'CA', '41860', '941', 0, 'FRM', 'N', 'N', NULL, NULL, '7', 'N', 'A', 'N', 'N', 710),
                    ('L6', '2020Q1', 'R', 'SellerB', 4.5, 95000.0, 360, DATE '2019-01-01', DATE '2019-02-01', 0, 0, 1, NULL, NULL, NULL, 'N', 'P', 'SF', 1, 'P', 'PR', '00000', '009', 0, 'FRM', 'N', 'N', NULL, NULL, '7', 'N', 'A', 'N', 'N', NULL)
                ) AS t(loan_id, acquisition_quarter, channel, seller_name, note_rate, orig_upb, loan_term, orig_date, first_payment_date, orig_ltv, orig_cltv, num_borrowers, dti, credit_score, co_borrower_credit_score, first_time_buyer, loan_purpose, property_type, num_units, occupancy, property_state, msa, zip3, mi_pct, amortization_type, prepay_penalty, interest_only, io_first_pi_date, mi_type, special_eligibility_program, relocation_mortgage, property_valuation_method, high_balance_loan, hltv_refi_option, orig_classic_fico)
            """)
            s_con.execute("CREATE TABLE origination_restatements_table AS SELECT 'seller_name'::VARCHAR AS field_name, 1::BIGINT AS loans_restated")
            s_con.execute("CREATE TABLE feature_catalogue_table AS SELECT 'payment_history'::VARCHAR AS field_name")
            s_con.execute("""
                CREATE TABLE macro_economic_mart AS
                SELECT d::DATE AS period, strftime(d, '%Y-%m') AS reporting_period, year(d) AS year, month(d) AS month,
                       concat(year(d)::VARCHAR, 'Q', quarter(d)::VARCHAR) AS quarter_label,
                       (CASE WHEN year(d)=2020 THEN 0.5 ELSE 2.5 END)::DECIMAL(6,4) AS federal_funds_rate_pct,
                       (CASE WHEN year(d)=2020 THEN 8.0 ELSE 4.0 END)::DECIMAL(5,2) AS unemployment_rate_pct,
                       FALSE AS unemployment_missing,
                       (250.0 + (year(d) - 2019) * 15.0)::DECIMAL(8,2) AS national_house_price_index_sa,
                       0.0::DECIMAL(6,2) AS unemployment_change_1m,
                       (CASE WHEN year(d)=2020 THEN 4.0 ELSE -2.0 END)::DECIMAL(6,2) AS unemployment_change_12m,
                       0.5::DOUBLE AS house_price_change_1m_pct,
                       6.0::DOUBLE AS house_price_change_12m_pct,
                       5.5::DECIMAL(15,4) AS lgd_discount_rate_long_run_pct,
                       9.0::DECIMAL(15,4) AS lgd_discount_rate_downturn_pct
                FROM generate_series(DATE '2018-01-01', DATE '2023-06-01', INTERVAL 1 MONTH) AS t(d)
            """)
            s_con.execute("""
                CREATE TABLE macro_state_hpi_table AS
                SELECT st AS state, year(qd)::INTEGER AS year, quarter(qd)::INTEGER AS quarter,
                       concat(year(qd)::VARCHAR, 'Q', quarter(qd)::VARCHAR) AS quarter_label,
                       qd::DATE AS quarter_date,
                       (200.0 + (year(qd) - 2000) * 5.0)::DECIMAL(8,2) AS house_price_index_sa,
                       (200.0 + (year(qd) - 2000) * 5.0)::DECIMAL(8,2) AS house_price_index_nsa,
                       (200.0 + (year(qd) - 2000) * 5.0)::DECIMAL(8,2) AS house_price_index_all_sales_nsa,
                       5.0::DOUBLE AS house_price_change_12m_pct
                FROM (VALUES ('CA'), ('NV'), ('TX'), ('FL')) AS s(st),
                     generate_series(DATE '2000-01-01', DATE '2023-04-01', INTERVAL 3 MONTH) AS q(qd)
            """)
            s_con.close()

            m_con = c.connect(marts_db, read_only=False)
            sp = c.attach_db(m_con, src_db, "src")
            build_core.init_workout_table(m_con)
            info, _ = build_core.build_quarter_core(m_con, raw_pq, "2020Q1", core_pq)
            self.assertTrue(info["ok"])
            m_con.execute("CREATE OR REPLACE TABLE build_metadata AS SELECT 'full'::VARCHAR AS scope, 't'::VARCHAR AS built_at_utc, 1::BIGINT AS total_rows, 1::INTEGER AS quarters_built")

            self.assertEqual(audit_mod.run_audit(m_con, sp, [core_pq], out_dir, dataset_end_iso="2022-12-01"), 0)
            self.assertEqual(def_mod.run_default_engine(m_con, sp, [core_pq]), 0)
            self.assertEqual(roll_mod.run_roll_rates(m_con, sp, [core_pq], out_dir), 0)
            self.assertEqual(em_mod.run_emergence(m_con, [core_pq]), 0)
            self.assertEqual(vin_mod.run_vintage_curves(m_con, sp, [core_pq], out_dir, sample_filter=False), 0)
            self.assertEqual(ltv_mod.run_current_ltv(m_con, sp, [core_pq], out_dir, sample_filter=False), 0)
            self.assertEqual(dr_mod.run_default_rate_history(m_con, sp, [core_pq], out_dir, sample_filter=False), 0)
            self.assertEqual(pop_mod.run_sample_population(m_con, out_dir), 0)
            self.assertEqual(drv_mod.run_risk_drivers(m_con, sp, [core_pq], out_dir, sample_filter=False), 0)
            self.assertEqual(seg_mod.run_segmentation(m_con, sp, out_dir, sample_filter=False), 0)
            self.assertEqual(out_mod.run_default_outcomes(m_con, sp, [core_pq], out_dir, dataset_end_iso="2022-12-01"), 0)
            self.assertEqual(forb_mod.run_forbearance(m_con, [core_pq], dataset_end_iso="2022-12-01"), 0)
            self.assertEqual(eco_mod.run_economy_links(m_con, sp, [core_pq], out_dir), 0)
            self.assertEqual(cyc_mod.run_cycle_and_benchmarks(m_con, [core_pq]), 0)
            self.assertEqual(mix_mod.run_portfolio_mix(m_con, sp, [core_pq], out_dir, dataset_end_iso="2022-12-01"), 0)
            self.assertEqual(rep_mod.run_representativeness(m_con, sp, out_dir, sample_filter=False), 0)
            self.assertEqual(surv_mod.run_survivorship(m_con, sp, sample_filter=False), 0)
            self.assertEqual(fnd_mod.generate_findings(m_con, out_md, "full synthetic"), 0)

            # Assert sticky deferral L3 produced strictly 1 new deferral start (not 28!)
            def_starts = int(c.scalar(m_con, "SELECT sum(new_starts) FROM forbearance_mart WHERE event_type='payment_deferral'"))
            self.assertEqual(def_starts, 1)
            # Assert cured mod L1 recorded non-zero mod_non_interest_upb & forgiveness
            l1_mod = c.q(m_con, "SELECT outcome_category, CAST(mod_non_interest_upb_max AS DOUBLE) AS mniu, CAST(principal_forgiveness_sum AS DOUBLE) AS pf FROM default_outcomes_mart WHERE loan_id='L1'").iloc[0]
            self.assertEqual(l1_mod["outcome_category"], "cured with modification")
            self.assertAlmostEqual(float(l1_mod["mniu"]), 1500.0)
            self.assertAlmostEqual(float(l1_mod["pf"]), 200.0)
            # Assert non-MSA '00000' excluded cleanly from MSA HHI entities count while share tracked
            msa_row = c.q(m_con, "SELECT * FROM concentration_mart WHERE concentration_dim='msa' AND snapshot_year=2022").iloc[0]
            self.assertEqual(int(msa_row["entities_count"]), 3)  # L1, L3, L5 valid MSAs; L6='00000' excluded
            self.assertGreater(float(msa_row["unmapped_or_non_msa_share_pct"]), 0.0)
            # Assert P1-1 psi_by_year_mart covers all drivers with zero PSI in latest year (2022)
            max_yr_psi = float(c.scalar(m_con, "SELECT max(abs(psi_vs_today)) FROM psi_by_year_mart WHERE snapshot_year=2022"))
            self.assertLess(max_yr_psi, 1e-9)
            # Assert P1-2 threshold_sensitivity_mart counts each crossing loan once across all eras
            tot_2m = int(c.scalar(m_con, "SELECT sum(loans_reaching) FROM threshold_sensitivity_mart WHERE dpd_threshold_months=2"))
            self.assertEqual(tot_2m, 1)  # Only L2 reaches >= 2m behind across 2020-2022 in fixture

            # Verify default sample code paths write into module_outputs-style per-script folders
            out_s = root / "out_sample"
            self.assertEqual(dr_mod.run_default_rate_history(m_con, sp, [core_pq], out_s, sample_filter=True), 0)
            self.assertTrue((out_s / "07_default_rate_history" / "book_snapshot" / "year=2020" / "part.parquet").is_file())
            self.assertEqual(drv_mod.run_risk_drivers(m_con, sp, [core_pq], out_s, sample_filter=True), 0)
            self.assertTrue((out_s / "09_risk_drivers" / "book_snapshot_behavioural" / "year=2020" / "part.parquet").is_file())
            self.assertEqual(rep_mod.run_representativeness(m_con, sp, out_s, sample_filter=True), 0)
            self.assertEqual(surv_mod.run_survivorship(m_con, sp, sample_filter=True), 0)
            m_con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
