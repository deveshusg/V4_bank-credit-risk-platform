"""Build the self-contained 0.03% stratified sample DuckDB (mortgages_sample.duckdb).

Reads the full mortgages.duckdb (READ_ONLY) and writes a self-contained single DuckDB
with identical table/view names and column schemas:
  - loans_table: 0.03% per-acquisition-quarter reservoir sample (deterministic seed)
  - loan_monthly_view: SQL view over internal _loan_monthly_table holding the full
    monthly histories of the sampled loans (no raw Parquet dependency at runtime)
  - macro_* tables/views, loaded_quarters_table, origination_restatements_table,
    field_leakage_table, feature_catalogue_table: copied in full

Run: .venv\\Scripts\\python.exe residential_mortgage\\00_data\\scripts\\04_build_sample_db.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import duckdb

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent
PACKAGE_ROOT = DATA_DIR.parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

import config  # noqa: E402
from field_map import EXIT_REASONS, SQL_TYPES, fields_for  # noqa: E402

_PATHS = config.paths()
_SAMPLING = config.load("sampling")["sampling"]
_COMPUTE = config.load("compute")["duckdb"]

DEFAULT_FULL_DB = config.base_db_path(full=True)
DEFAULT_SAMPLE_DB = config.base_db_path(full=False)
DEFAULT_PARQUET_DIR = _PATHS["parquet_dir"]
DEFAULT_RATE = float(_SAMPLING["rate"])
DEFAULT_SEED = int(_SAMPLING["seed"])
DEFAULT_MEM_LIMIT = str(_COMPUTE["memory_limit"])
DEFAULT_THREADS = int(_COMPUTE["threads"])
SCRATCH_DIR = _PATHS["scratch_dir"]

COPY_FULL_TABLES: tuple[str, ...] = (
    "loaded_quarters_table",
    "origination_restatements_table",
    "field_leakage_table",
    "feature_catalogue_table",
    "macro_monthly_table",
    "macro_state_hpi_table",
    "macro_economic_mart",
    "macro_sources_table",
)


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params=None):
    row = con.execute(sql, params or []).fetchone()
    return row[0] if row else None


def _sql_text(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _convert_expr(field) -> str:
    if field.dtype == "text":
        return field.column
    if field.dtype == "date":
        return f"try_strptime({field.column}, '%m%Y')::DATE"
    return f"TRY_CAST({field.column} AS {SQL_TYPES[field.dtype]})"


def _monthly_select_exprs(quarter: str) -> str:
    """Match exact 43 columns and types of 02_build_base_tables.update_loan_monthly_view."""
    cols = [
        f"{_sql_text(quarter)}::VARCHAR AS acquisition_quarter",
        "loan_id",
        "try_strptime(reporting_period, '%m%Y')::DATE AS reporting_period",
    ]
    for f in fields_for("loan_monthly"):
        cols.append(f"{_convert_expr(f)} AS {f.column}")
    whens = " ".join(f"WHEN {_sql_text(c)} THEN {_sql_text(lbl)}" for c, lbl in EXIT_REASONS.items())
    cols += [
        "CASE WHEN delinquency_status IS NULL OR delinquency_status = 'XX' THEN NULL "
        "ELSE TRY_CAST(delinquency_status AS INTEGER) END AS delinquency_months",
        "COALESCE(delinquency_status = 'XX', FALSE) AS is_dpd_unknown",
        f"CASE zero_balance_code {whens} END AS exit_reason",
    ]
    return ", ".join(cols)


def build_sample_database(
    full_db: Path,
    sample_db: Path,
    rate: float,
    seed: int,
    parquet_dir: Path = DEFAULT_PARQUET_DIR,
    memory_limit: str = DEFAULT_MEM_LIMIT,
    threads: int = DEFAULT_THREADS,
) -> tuple[bool, dict]:
    """Create sample_db atomically via .duckdb.tmp from read-only full_db."""
    if not full_db.is_file():
        raise FileNotFoundError(f"Full database not found: {full_db}")

    sample_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = sample_db.with_suffix(".duckdb.tmp")
    for suffix_extra in ("", ".wal"):
        p = Path(str(tmp_db) + suffix_extra)
        if p.exists():
            p.unlink()

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = str(SCRATCH_DIR).replace("\\", "/")
    full_lit = str(full_db).replace("\\", "/")

    t0 = time.perf_counter()
    con = duckdb.connect(str(tmp_db))
    try:
        con.execute(f"PRAGMA memory_limit='{memory_limit}'")
        con.execute(f"PRAGMA temp_directory='{temp_dir}'")
        con.execute(f"PRAGMA threads={threads}")
        con.execute(f"ATTACH '{full_lit}' AS src (READ_ONLY)")

        # 1. Create empty loans_table with exact schema from full DB
        con.execute("CREATE TABLE loans_table AS SELECT * FROM src.loans_table LIMIT 0")

        quarters = con.execute(
            "SELECT quarter, loans FROM src.loaded_quarters_table ORDER BY quarter"
        ).fetchall()
        if not quarters:
            raise RuntimeError("No quarters found in src.loaded_quarters_table.")

        # 2. Stratified per-quarter deterministic sampling (1 thread inside reservoir draw)
        print(f"Sampling {rate * 100:.4g}% per quarter across {len(quarters)} quarters (seed={seed})...", flush=True)
        expected_total = 0
        con.execute("SET threads = 1")
        try:
            for idx, (quarter, q_loans) in enumerate(quarters, 1):
                n = int(scalar(con, "SELECT GREATEST(1, CAST(ROUND(? * ?) AS BIGINT))", [rate, q_loans]))
                expected_total += n
                con.execute(
                    "INSERT INTO loans_table "
                    "SELECT * FROM (SELECT * FROM src.loans_table WHERE acquisition_quarter = ? ORDER BY loan_id) "
                    f"USING SAMPLE reservoir({n} ROWS) REPEATABLE ({seed})",
                    [quarter],
                )
                if idx % 20 == 0 or idx == len(quarters):
                    print(f"  [{idx:3d}/{len(quarters)}] {quarter}: sampled {n:,} / {q_loans:,} loans", flush=True)
        finally:
            con.execute(f"SET threads = {threads}")

        sampled_count = int(scalar(con, "SELECT count(*) FROM loans_table"))
        print(f"loans_table populated: {sampled_count:,} loans ({time.perf_counter() - t0:.1f}s)", flush=True)

        # 3. Extract complete monthly histories per quarter directly from raw Parquet
        #    (filtering loan_id first so TRY_CAST / try_strptime only run on sampled rows),
        #    then sort for tight DuckDB compression.
        print("Extracting full monthly histories per quarter...", flush=True)
        t_m = time.perf_counter()
        con.execute("CREATE TABLE _loan_monthly_stage AS SELECT * FROM src.loan_monthly_view LIMIT 0")
        for idx, (quarter, _) in enumerate(quarters, 1):
            pq = (parquet_dir / f"{quarter}.parquet").resolve()
            if not pq.is_file():
                raise FileNotFoundError(f"Parquet file not found for {quarter}: {pq}")
            pq_lit = str(pq).replace("\\", "/")
            con.execute(
                "CREATE OR REPLACE TEMP TABLE _q_ids AS "
                "SELECT loan_id FROM loans_table WHERE acquisition_quarter = ?",
                [quarter],
            )
            sel_exprs = _monthly_select_exprs(quarter)
            con.execute(f"""
                INSERT INTO _loan_monthly_stage
                WITH filtered AS (
                    SELECT * FROM read_parquet('{pq_lit}')
                    WHERE loan_id IN (SELECT loan_id FROM _q_ids)
                )
                SELECT {sel_exprs}
                FROM filtered
            """)
            if idx % 10 == 0 or idx == len(quarters):
                rows_so_far = int(scalar(con, "SELECT count(*) FROM _loan_monthly_stage"))
                print(
                    f"  [{idx:3d}/{len(quarters)}] {quarter}: {rows_so_far:,} cumulative rows ({time.perf_counter() - t_m:.1f}s)",
                    flush=True,
                )

        con.execute("DROP TABLE IF EXISTS _q_ids")
        print("Sorting monthly records for compact storage...", flush=True)
        con.execute("""
            CREATE TABLE _loan_monthly_table AS
            SELECT * FROM _loan_monthly_stage
            ORDER BY acquisition_quarter, loan_id, reporting_period
        """)
        con.execute("DROP TABLE _loan_monthly_stage")
        con.execute("CREATE OR REPLACE VIEW loan_monthly_view AS SELECT * FROM _loan_monthly_table")
        monthly_rows = int(scalar(con, "SELECT count(*) FROM loan_monthly_view"))
        print(f"loan_monthly_view populated: {monthly_rows:,} rows ({time.perf_counter() - t_m:.1f}s)", flush=True)

        # 4. Copy non-loan metadata and macro tables in full
        existing_src = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'src'").fetchall()}
        copied_tables = []
        for tbl in COPY_FULL_TABLES:
            if tbl in existing_src:
                con.execute(f"CREATE TABLE {tbl} AS SELECT * FROM src.{tbl}")
                copied_tables.append(tbl)
            else:
                print(f"  WARN: {tbl} not found in source DB; skipped")
        if "macro_monthly_table" in copied_tables:
            con.execute("CREATE OR REPLACE VIEW macro_monthly_view AS SELECT * FROM macro_monthly_table")

        # 5. Verification checks before promoting tmp -> final
        checks = []

        src_loan_cols = [(r[0], r[1]) for r in con.execute("DESCRIBE src.loans_table").fetchall()]
        dst_loan_cols = [(r[0], r[1]) for r in con.execute("DESCRIBE loans_table").fetchall()]
        src_mon_cols = [(r[0], r[1]) for r in con.execute("DESCRIBE src.loan_monthly_view").fetchall()]
        dst_mon_cols = [(r[0], r[1]) for r in con.execute("DESCRIBE loan_monthly_view").fetchall()]
        checks.append(("Schema matches full DB (loans_table + loan_monthly_view)", src_loan_cols == dst_loan_cols and src_mon_cols == dst_mon_cols, f"loans={len(dst_loan_cols)} cols, monthly={len(dst_mon_cols)} cols"))

        checks.append(("Sampled loans count matches stratified quarter target", sampled_count == expected_total, f"actual={sampled_count:,}, expected={expected_total:,}"))

        q_covered = int(scalar(con, "SELECT count(DISTINCT acquisition_quarter) FROM loans_table"))
        checks.append(("All acquisition quarters represented", q_covered == len(quarters), f"{q_covered}/{len(quarters)} quarters"))

        mon_loans = int(scalar(con, "SELECT count(DISTINCT loan_id) FROM loan_monthly_view"))
        dup_loans = int(scalar(con, "SELECT count(*) - count(DISTINCT loan_id) FROM loans_table"))
        checks.append(("Zero orphaned or duplicate loans", mon_loans == sampled_count and dup_loans == 0, f"monthly_loans={mon_loans:,}, dup_loans={dup_loans}"))

        dup_pairs = int(scalar(con, "SELECT count(*) - count(DISTINCT (loan_id, reporting_period)) FROM loan_monthly_view"))
        checks.append(("Zero duplicate (loan_id, reporting_period)", dup_pairs == 0, f"dup_pairs={dup_pairs}"))

        dst_tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        checks.append(("sampled_loans_table omitted cleanly", "sampled_loans_table" not in dst_tables, "single loans_table only"))

        macro_ok = all(int(scalar(con, f"SELECT count(*) FROM {t}")) > 0 for t in copied_tables)
        checks.append(("Macro and metadata tables copied in full", macro_ok and len(copied_tables) == len(COPY_FULL_TABLES), f"{len(copied_tables)}/{len(COPY_FULL_TABLES)} tables"))

        con.execute("DETACH src")
        con.execute("CHECKPOINT")

        print("\nChecks:")
        all_ok = True
        for label, ok, detail in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {label} ({detail})")
            all_ok = all_ok and ok

        stats = {
            "loans": sampled_count,
            "monthly_rows": monthly_rows,
            "quarters": q_covered,
            "elapsed_sec": time.perf_counter() - t0,
        }
    finally:
        con.close()

    if not all_ok:
        if tmp_db.exists():
            tmp_db.unlink()
        return False, stats

    wal_tmp = Path(str(tmp_db) + ".wal")
    if wal_tmp.exists():
        wal_tmp.unlink()
    os.replace(tmp_db, sample_db)
    size_mb = sample_db.stat().st_size / (1024 * 1024)
    stats["size_mb"] = size_mb
    print(f"\nWrote {sample_db} ({size_mb:.2f} MB) in {stats['elapsed_sec']:.1f}s")
    print(f"GitHub < 100 MB check: {'PASS' if size_mb < 100.0 else 'WARN (>= 100 MB)'}")
    return True, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 0.03% stratified mortgages_sample.duckdb from mortgages.duckdb.")
    parser.add_argument("--full-db", default=str(DEFAULT_FULL_DB), help="Path to full mortgages.duckdb")
    parser.add_argument("--out-db", default=str(DEFAULT_SAMPLE_DB), help="Output sample DuckDB path")
    parser.add_argument("--parquet-dir", default=str(DEFAULT_PARQUET_DIR), help="Raw quarterly Parquet directory")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE, help="Sampling rate per quarter (default from sampling.toml)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic reservoir seed (default from sampling.toml)")
    args = parser.parse_args()

    ok, _ = build_sample_database(
        full_db=Path(args.full_db).resolve(),
        sample_db=Path(args.out_db).resolve(),
        rate=args.rate,
        seed=args.seed,
        parquet_dir=Path(args.parquet_dir).resolve(),
    )
    print(f"OVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
