"""Shared helpers for Module 2 (02_portfolio_analytics).

Provides database connection and 16 GB RAM memory limits, strict sample vs full
path isolation, regulatory threshold imports from regulatory_parameters.py,
enforced unique-key and non-null checks, COVID deferral hold logic, closed-form
scheduled balance calculation, and matplotlib dpi=300 saving helpers.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable, Sequence

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
PORTFOLIO_DIR = SCRIPT_DIR.parent
REPO_ROOT = PORTFOLIO_DIR.parent
DATA_DIR = PORTFOLIO_DIR / "00_data"
PROCESSED = DATA_DIR / "processed"
RAW_PARQUET_DIR = DATA_DIR / "raw" / "parquet"
SCRATCH_DIR = PROCESSED / ".scratch"

DEFAULT_DB = PROCESSED / "mortgages.duckdb"
DEFAULT_MARTS_FULL = PROCESSED / "module2_marts.duckdb"
DEFAULT_MARTS_SAMPLE = PROCESSED / "module2_marts_sample.duckdb"
DEFAULT_CORE_FULL = PROCESSED / "monthly_core"
DEFAULT_CORE_SAMPLE = PROCESSED / "monthly_core_sample"
OUTPUTS_FULL = SCRIPT_DIR / "outputs"
OUTPUTS_SAMPLE = SCRIPT_DIR / "outputs_sample"
FINDINGS_FULL = REPO_ROOT / "docs" / "module_2" / "18_portfolio_findings.md"
FINDINGS_SAMPLE = OUTPUTS_SAMPLE / "18_portfolio_findings_sample.md"

if str(PORTFOLIO_DIR) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_DIR))

import windows  # noqa: E402

ACTIVE_RELIEF_PLANS: tuple[str, ...] = windows.ACTIVE_RELIEF_PLANS
NO_RELIEF_PLAN_CODES: tuple[str, ...] = windows.NO_RELIEF_PLAN_CODES
DEFERRAL_RESOLUTION_CODES: tuple[str, ...] = windows.DEFERRAL_RESOLUTION_CODES
CREDIT_EXIT_CODES: tuple[str, ...] = windows.CREDIT_EXIT_CODES
OTHER_EXIT_CODES: tuple[str, ...] = ("06", "16", "96")
ALL_EXIT_CODES: tuple[str, ...] = ("01",) + CREDIT_EXIT_CODES + OTHER_EXIT_CODES

DPD_DEFAULT_MONTHS: int = windows.DPD_DEFAULT_MONTHS
PROBATION_ARREARS_MONTHS: int = windows.PROBATION_ARREARS_MONTHS
PROBATION_RESTRUCTURING_MONTHS: int = windows.PROBATION_RESTRUCTURING_MONTHS
COVID_DEFERRAL_ELIGIBLE_START: str = windows.COVID_DEFERRAL_ELIGIBLE_START[:7]
COVID_DEFERRAL_ELIGIBLE_END: str = windows.COVID_DEFERRAL_ELIGIBLE_END[:7]
COVID_DEFERRAL_MAX_END: str = windows.COVID_DEFERRAL_MAX_END[:7]
COVID_DEFERRAL_MAX_MONTHS: int = windows.COVID_DEFERRAL_MAX_MONTHS

MIN_DATA_YEARS: int = windows.MIN_DATA_YEARS
SEASONING_MIN_MOB: int = windows.SEASONING_MIN_MOB
SNAPSHOT_MONTH: int = windows.SNAPSHOT_MONTH
PERFORMANCE_WINDOW_MONTHS: int = windows.PERFORMANCE_WINDOW_MONTHS
OUT_OF_TIME_FROM: str = windows.OUT_OF_TIME_FROM

LGD_HOUSE_PRICE_FALL_MIN_PCT: float = windows.LGD_HOUSE_PRICE_FALL_MIN_PCT
LGD_HOUSE_PRICE_FALL_REF_PCT: float = windows.LGD_HOUSE_PRICE_FALL_REF_PCT
LTV_DOWNWARD_MARKET_DECLINE_PCT: float = windows.LTV_DOWNWARD_MARKET_DECLINE_PCT
IRB_RESIDENTIAL_CORRELATION: float = windows.IRB_RESIDENTIAL_CORRELATION
SA_OWNER_OCCUPIED_LTV_SPLIT: float = windows.SA_OWNER_OCCUPIED_LTV_SPLIT

ERAS: list[str] = [
    "2000-2006 build-up",
    "2007-2010 crisis",
    "2011-2019 recovery",
    "2020-2021 COVID",
    "2022-2025 recent",
]

DEFAULT_MEM_LIMIT = "6GB"


def sql_list(items: Iterable[str]) -> str:
    """Format an iterable of short codes into a SQL tuple literal."""
    return "(" + ", ".join(f"'{item}'" for item in items) + ")"


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Attach standard Module 2 CLI flags with automatic --sample isolation."""
    parser.add_argument("--db", default=str(DEFAULT_DB), help="source mortgages DuckDB file")
    parser.add_argument("--marts", default=None, help="Module 2 marts DuckDB file")
    parser.add_argument("--core-dir", default=None, help="loan_monthly_core Parquet directory")
    parser.add_argument("--outputs-dir", default=None, help="charts and snapshot output directory")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="run on the 10%% development subset using isolated _sample paths",
    )
    return parser


def resolve_paths(args: argparse.Namespace) -> argparse.Namespace:
    """Resolve sample vs full storage paths when not explicitly overridden."""
    args.db = Path(args.db)
    args.marts = Path(args.marts) if args.marts else (DEFAULT_MARTS_SAMPLE if args.sample else DEFAULT_MARTS_FULL)
    args.core_dir = (
        Path(args.core_dir) if args.core_dir else (DEFAULT_CORE_SAMPLE if args.sample else DEFAULT_CORE_FULL)
    )
    args.outputs_dir = (
        Path(args.outputs_dir) if args.outputs_dir else (OUTPUTS_SAMPLE if args.sample else OUTPUTS_FULL)
    )
    return args


def configure_duckdb(con: duckdb.DuckDBPyConnection, memory_limit: str = DEFAULT_MEM_LIMIT) -> None:
    """Apply RAM limit and temporary spill directory for a 16 GB laptop host."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = str(SCRATCH_DIR).replace("\\", "/")
    con.execute(f"PRAGMA memory_limit='{memory_limit}'")
    con.execute(f"PRAGMA temp_directory='{temp_dir}'")


def connect(db: str | Path, read_only: bool = True, memory_limit: str = DEFAULT_MEM_LIMIT) -> duckdb.DuckDBPyConnection:
    """Open DuckDB connection and configure safe RAM/temp spill settings."""
    con = duckdb.connect(str(db), read_only=read_only)
    configure_duckdb(con, memory_limit=memory_limit)
    return con


def attach_db(con: duckdb.DuckDBPyConnection, path: str | Path, alias: str) -> str:
    """Attach another DuckDB database read-only and return its SQL prefix."""
    try:
        con.execute(f"DETACH {alias}")
    except Exception:
        pass
    p = str(path).replace("\\", "/")
    con.execute(f"ATTACH '{p}' AS {alias} (READ_ONLY)")
    return f"{alias}."


def list_core_files(core_dir: Path) -> list[Path]:
    """Return sorted quarterly Parquet files inside a monthly_core directory."""
    files = sorted(core_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No Parquet files found in {core_dir}. Run 00_build_monthly_core.py first."
        )
    return files


def register_core_view(
    con: duckdb.DuckDBPyConnection,
    core_dir: Path,
    view_name: str = "loan_monthly_core",
) -> list[Path]:
    """Register a TEMP VIEW over all quarterly loan_monthly_core Parquet files."""
    files = list_core_files(core_dir)
    lit = "[" + ", ".join("'" + str(f).replace("\\", "/") + "'" for f in files) + "]"
    con.execute(f"CREATE OR REPLACE TEMP VIEW {view_name} AS SELECT * FROM read_parquet({lit})")
    return files


def assert_scope_match(marts_con: duckdb.DuckDBPyConnection, sample_flag: bool) -> None:
    """Reject mixing sample scripts against full marts DB or vice versa."""
    expected = "sample" if sample_flag else "full"
    tables = {r[0] for r in marts_con.execute("SHOW TABLES").fetchall()}
    if "build_metadata" not in tables:
        raise RuntimeError(
            "build_metadata table missing in marts DB. Run 00_build_monthly_core.py first."
        )
    actual = scalar(marts_con, "SELECT scope FROM build_metadata LIMIT 1")
    if actual != expected:
        raise RuntimeError(
            f"Scope mismatch: CLI requested '{expected}' but marts DB holds '{actual}'."
        )


def scope(sample: bool, prefix: str = "", alias: str = "") -> str:
    """Return SQL predicate restricting to sampled_loans_table when sample is True."""
    if sample:
        col = f"{alias}.loan_id" if alias else "loan_id"
        return f"{col} IN (SELECT loan_id FROM {prefix}sampled_loans_table)"
    return "TRUE"


def era_case(col: str = "reporting_period") -> str:
    """Return SQL CASE expression assigning M2-1 calendar eras."""
    return (
        f"CASE WHEN year({col}) <= 2006 THEN '2000-2006 build-up' "
        f"WHEN year({col}) <= 2010 THEN '2007-2010 crisis' "
        f"WHEN year({col}) <= 2019 THEN '2011-2019 recovery' "
        f"WHEN year({col}) <= 2021 THEN '2020-2021 COVID' "
        f"ELSE '2022-2025 recent' END"
    )


def q(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """Execute SQL and return pandas DataFrame."""
    return con.execute(sql).df()


def scalar(con: duckdb.DuckDBPyConnection, sql: str):
    """Execute SQL and return top-left scalar or None."""
    rows = con.execute(sql).fetchall()
    return rows[0][0] if rows else None


def verify_key_stats(con: duckdb.DuckDBPyConnection, table_name: str, keys: Sequence[str]) -> tuple[int, int, int]:
    """Return (row_count, distinct_non_null_key_count, null_key_rows) for a table."""
    if not keys:
        raise ValueError(f"Unique key list cannot be empty for {table_name}.")
    key_cols = ", ".join(f'"{k}"' for k in keys)
    null_pred = " OR ".join(f'"{k}" IS NULL' for k in keys)
    rows = int(scalar(con, f"SELECT count(*) FROM {table_name}") or 0)
    null_rows = int(scalar(con, f"SELECT count(*) FROM {table_name} WHERE {null_pred}") or 0)
    distinct = int(
        scalar(
            con,
            f"SELECT count(*) FROM (SELECT DISTINCT {key_cols} FROM {table_name}) _uk",
        )
        or 0
    )
    return rows, distinct, null_rows


def _enforce_keys(con: duckdb.DuckDBPyConnection, name: str, keys: Sequence[str]) -> tuple[int, int]:
    """Validate non-null unique key on newly created mart, raising ValueError on violation."""
    rows, distinct, null_rows = verify_key_stats(con, name, keys)
    if null_rows > 0:
        raise ValueError(f"Mart {name} contains {null_rows:,} rows with NULL in key {list(keys)}.")
    if rows != distinct:
        raise ValueError(
            f"Mart {name} failed unique key check on {list(keys)}: {rows:,} rows vs {distinct:,} distinct."
        )
    return rows, distinct


def write_mart(
    con: duckdb.DuckDBPyConnection,
    name: str,
    sql: str,
    keys: Sequence[str],
) -> tuple[int, int]:
    """Create or replace a DuckDB mart from SQL and enforce non-null unique keys."""
    con.execute(f"CREATE OR REPLACE TABLE {name} AS {sql}")
    return _enforce_keys(con, name, keys)


def write_df(
    con: duckdb.DuckDBPyConnection,
    name: str,
    df: pd.DataFrame,
    keys: Sequence[str],
) -> tuple[int, int]:
    """Create or replace a small DuckDB mart from a DataFrame and enforce non-null unique keys."""
    con.register("_m2_df", df)
    cols = ", ".join(f'"{c}"' for c in df.columns)
    try:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT {cols} FROM _m2_df").fetchall()
    finally:
        con.unregister("_m2_df")
    return _enforce_keys(con, name, keys)


def insert_df(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    """Append a DataFrame into an existing DuckDB table cleanly."""
    if df.empty:
        return
    con.register("_m2_ins_df", df)
    cols = ", ".join(f'"{c}"' for c in df.columns)
    try:
        con.execute(f"INSERT INTO {name} SELECT {cols} FROM _m2_ins_df").fetchall()
    finally:
        con.unregister("_m2_ins_df")


class Checker:
    """Collect PASS/FAIL validation assertions and emit standard ASCII summary."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.checks: list[tuple[str, bool, str]] = []

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        """Record an assertion result."""
        self.checks.append((label, bool(ok), detail))

    def key(
        self,
        con: duckdb.DuckDBPyConnection,
        mart: str,
        keys: Sequence[str],
        detail: str = "",
    ) -> bool:
        """Check unique non-null key on an existing mart and record PASS/FAIL."""
        rows, distinct, null_rows = verify_key_stats(con, mart, keys)
        ok = (null_rows == 0) and (rows == distinct)
        msg = f"{rows:,} rows, {distinct:,} distinct, {null_rows:,} null keys"
        if detail:
            msg = f"{msg}; {detail}"
        self.add(f"unique key of {mart}", ok, msg)
        return ok

    def finish(self) -> int:
        """Print ASCII PASS/FAIL summary and return process exit code."""
        failed = [c for c in self.checks if not c[1]]
        for label, ok, detail in self.checks:
            status = "PASS  " if ok else "FAIL  "
            print(f"{status}{label}" + (f"  ({detail})" if detail else ""), flush=True)
        overall = "PASS" if not failed else "FAIL"
        print(
            f"OVERALL: {overall}  ({len(self.checks) - len(failed)}/{len(self.checks)} checks)",
            flush=True,
        )
        return 1 if failed else 0


def scheduled_upb(orig_upb: float, note_rate_pct: float, loan_term: int, mob: int) -> float:
    """Compute contractual scheduled UPB at 0-based months on book `mob`.

    `mob = 0` corresponds to payment period `k = clamp(mob + 1, 0, loan_term)`.
    Handles zero note rate safely and guards invalid terms.
    """
    if orig_upb is None or loan_term is None or loan_term <= 0 or mob is None:
        return 0.0
    p0 = float(orig_upb)
    n = int(loan_term)
    k = max(0, min(int(mob) + 1, n))
    if note_rate_pct is None or float(note_rate_pct) <= 0.0:
        return round(max(p0 * (1.0 - k / n), 0.0), 2)
    rm = float(note_rate_pct) / 1200.0
    pow_n = (1.0 + rm) ** n
    pow_k = (1.0 + rm) ** k
    denom = pow_n - 1.0
    if denom <= 0.0:
        return round(max(p0 * (1.0 - k / n), 0.0), 2)
    return round(max(p0 * (pow_n - pow_k) / denom, 0.0), 2)


def scheduled_upb_sql(
    orig_upb_expr: str,
    note_rate_expr: str,
    term_expr: str,
    mob_expr: str,
) -> str:
    """Return DuckDB SQL expression matching scheduled_upb(orig_upb, note_rate, term, mob)."""
    k_expr = f"LEAST(GREATEST(COALESCE({mob_expr}, 0) + 1, 0), COALESCE({term_expr}, 360))"
    r_expr = f"(CAST({note_rate_expr} AS DOUBLE) / 1200.0)"
    n_expr = f"COALESCE({term_expr}, 360)"
    return (
        f"CASE WHEN COALESCE({orig_upb_expr}, 0.0) <= 0.0 OR {n_expr} <= 0 THEN 0.0 "
        f"WHEN COALESCE({note_rate_expr}, 0.0) <= 0.0 THEN "
        f"ROUND(GREATEST(CAST({orig_upb_expr} AS DOUBLE) * (1.0 - CAST({k_expr} AS DOUBLE) / {n_expr}), 0.0), 2) "
        f"ELSE ROUND(GREATEST(CAST({orig_upb_expr} AS DOUBLE) * "
        f"(pow(1.0 + {r_expr}, {n_expr}) - pow(1.0 + {r_expr}, {k_expr})) / "
        f"NULLIF(pow(1.0 + {r_expr}, {n_expr}) - 1.0, 0.0), 0.0), 2) END"
    )


def covid_hold_months(
    mb: Sequence[int | None],
    plans: Sequence[str],
    months: Sequence[str],
) -> tuple[list[int | None], list[bool]]:
    """Apply M2-4 UK COVID deferral hold cumulatively up to 6 months and July 2021.

    Active plans are ('F', 'T', 'R'); ('7', 'N', '', None) do not qualify.
    Spells that started before 2020-03 do not qualify until a fresh eligible
    spell starts inside 2020-03..2021-03. Cumulative budget is 6 months per loan.
    While held: adj_dpd = min(reported_dpd, held) when reported is known;
    unknown ('XX' / None) stays None. Returns (adj_dpd, in_hold_flags).
    """
    n = len(mb)
    out = list(mb)
    in_hold = [False] * n
    in_eligible_spell = False
    in_pre_covid_spell = False
    held: int = 0
    used = 0
    last_known_dpd = 0

    for i in range(n):
        m = months[i]
        plan = plans[i] or ""
        raw_dpd = mb[i]
        is_active_plan = plan in ACTIVE_RELIEF_PLANS

        if not is_active_plan:
            in_eligible_spell = False
            in_pre_covid_spell = False
        else:
            prev_active = (i > 0) and ((plans[i - 1] or "") in ACTIVE_RELIEF_PLANS)
            if not prev_active:
                if m < COVID_DEFERRAL_ELIGIBLE_START:
                    in_pre_covid_spell = True
                    in_eligible_spell = False
                elif m <= COVID_DEFERRAL_ELIGIBLE_END:
                    in_pre_covid_spell = False
                    in_eligible_spell = True
                    held = last_known_dpd
                else:
                    in_pre_covid_spell = False
                    in_eligible_spell = False

            if (
                in_eligible_spell
                and not in_pre_covid_spell
                and m <= COVID_DEFERRAL_MAX_END
                and used < COVID_DEFERRAL_MAX_MONTHS
            ):
                in_hold[i] = True
                used += 1
                if raw_dpd is not None:
                    out[i] = min(raw_dpd, held)
            elif m > COVID_DEFERRAL_MAX_END or used >= COVID_DEFERRAL_MAX_MONTHS:
                in_eligible_spell = False

        if raw_dpd is not None:
            last_known_dpd = raw_dpd

    return out, in_hold


def normal_cdf(x: float) -> float:
    """Standard normal CDF using Python math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def inv_normal_cdf(p: float) -> float:
    """Acklam rational approximation to inverse standard normal CDF (precision ~1e-9)."""
    if not (0.0 < p < 1.0):
        if p <= 0.0:
            return -12.0
        return 12.0
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q_val = math.sqrt(-2.0 * math.log(p))
        num = (((((c[0] * q_val + c[1]) * q_val + c[2]) * q_val + c[3]) * q_val + c[4]) * q_val + c[5])
        den = ((((d[0] * q_val + d[1]) * q_val + d[2]) * q_val + d[3]) * q_val + 1.0)
        return num / den
    if p > phigh:
        q_val = math.sqrt(-2.0 * math.log(1.0 - p))
        num = (((((c[0] * q_val + c[1]) * q_val + c[2]) * q_val + c[3]) * q_val + c[4]) * q_val + c[5])
        den = ((((d[0] * q_val + d[1]) * q_val + d[2]) * q_val + d[3]) * q_val + 1.0)
        return -num / den
    q_val = p - 0.5
    r = q_val * q_val
    num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q_val
    den = (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    return num / den


def wilson_ci(events: int, total: int, z: float = 1.959963984540054) -> tuple[float, float, float]:
    """Return (point_rate, ci_low, ci_high) via Wilson score interval."""
    if total <= 0:
        return 0.0, 0.0, 0.0
    p = events / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    half = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def save_chart(fig: plt.Figure, out_path: Path) -> None:
    """Save matplotlib figure at 300 dpi and close cleanly."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
