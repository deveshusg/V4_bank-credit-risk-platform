"""Build DuckDB loans_table and monthly views from raw Parquet files.

Features:
- Reads quarterly Parquet files from residential_mortgage/00_data/raw/parquet/
- Master database: residential_mortgage/00_data/processed/mortgages.duckdb
- Explicit suffix naming convention:
    * loans_table: 1 row per unique loan_id (latest corrected origination values)
    * loan_monthly_view: view over Parquet files in loaded_quarters_table
    * loaded_quarters_table: ledger of loaded quarters, line counts, UPB tie-outs, timings
    * origination_restatements_table: mid-life restatements tracked per origination column
- 7 integrity checks per quarter with atomic transactions (rollback on fail)
- Reconciles original UPB across first month, restatements, and blank first months
- Updates loan_monthly_view over loaded quarters with recomputed absolute paths
  (moving the repo needs one rerun to refresh paths)
- Writes audit log to data_log.md for default database runs
- ASCII-only terminal output: OK, ..., FAIL. Live updates only when running in a terminal.
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb

# Reconfigure stdout for safe encoding if supported
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent
PACKAGE_ROOT = DATA_DIR.parent
REPO_ROOT = PACKAGE_ROOT.parent

for _p in (str(SCRIPT_DIR), str(PACKAGE_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
from field_map import EXIT_REASONS, FIELDS, MODIFICATION_FLAG_VALUES, SQL_TYPES, fields_for  # noqa: E402

# ---------------------------------------------------------------------------------------
# Path configurations
# ---------------------------------------------------------------------------------------
_PATHS = config.paths()
DEFAULT_DB = config.base_db_path(full=True)
PARQUET_DIR = _PATHS["parquet_dir"]
DATA_LOG = DATA_DIR / "data_log.md"

PERIOD = "try_strptime(reporting_period, '%m%Y')::DATE"


# =======================================================================================
# SECTION 1: TERMINAL UI & FORMATTING
# =======================================================================================

def format_bytes(num_bytes: float) -> str:
    """Format byte count into human-readable text."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def format_seconds(seconds: float) -> str:
    """Format elapsed seconds into MMm SSs or HHh MMm SSs."""
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def print_in_place(line: str):
    """Print an updating line in place if in an interactive terminal."""
    if not sys.stdout.isatty():
        return
    cols = shutil.get_terminal_size((80, 20)).columns
    safe_line = line[: cols - 1].ljust(cols - 1)
    sys.stdout.write(f"\r{safe_line}")
    sys.stdout.flush()


def print_final(line: str):
    """Print a completed line and advance cursor."""
    if sys.stdout.isatty():
        cols = shutil.get_terminal_size((80, 20)).columns
        safe_line = line[: cols - 1].ljust(cols - 1)
        sys.stdout.write(f"\r{safe_line}\n")
    else:
        sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


# =======================================================================================
# SECTION 2: DUCKDB SCHEMA, VIEWS & LOGIC
# =======================================================================================

def scalar(con, sql: str, params=None):
    """Run a query and return a single scalar value."""
    return con.execute(sql, params or []).fetchone()[0]


def sql_text(value) -> str:
    """Escape text for SQL literal."""
    return "'" + str(value).replace("'", "''") + "'"


def convert(field) -> str:
    """Generate SQL expression to convert raw string to target type."""
    if field.dtype == "text":
        return field.column
    if field.dtype == "date":
        return f"try_strptime({field.column}, '%m%Y')::DATE"
    return f"TRY_CAST({field.column} AS {SQL_TYPES[field.dtype]})"


def loans_fields():
    """Return all fields destined for loans_table."""
    return [f for f in FIELDS if f.target in ("loans", "loans_first")]


def parse_quarter(text: str) -> tuple[int, int, str]:
    """Parse and validate quarter string (e.g. 2005Q1)."""
    cleaned = text.strip().upper().replace("-", "")
    match = re.fullmatch(r"(\d{4})Q([1-4])", cleaned)
    if not match:
        sys.exit(f"Error: Invalid quarter format '{text}'. Expected YYYYQn (e.g. 2005Q1).")
    year, q = int(match.group(1)), int(match.group(2))
    return year, q, f"{year}Q{q}"


def init_database(con, parquet_dir: Path):
    """Create master tables if missing and update loan_monthly_view."""
    # 1. Physical loans_table
    loans_cols = ["loan_id VARCHAR", "acquisition_quarter VARCHAR"]
    for f in loans_fields():
        loans_cols.append(f"{f.column} {SQL_TYPES[f.dtype]}")
    con.execute(f"CREATE TABLE IF NOT EXISTS loans_table ({', '.join(loans_cols)})")

    # 2. Physical loaded_quarters_table audit ledger
    con.execute(
        "CREATE TABLE IF NOT EXISTS loaded_quarters_table ("
        "quarter VARCHAR, loaded_at TIMESTAMP, raw_csv_bytes BIGINT, raw_lines BIGINT, "
        "parquet_bytes BIGINT, parquet_rows BIGINT, loans BIGINT, monthly_rows BIGINT, "
        "orig_upb_first_month DECIMAL(18,2), orig_upb_restated DECIMAL(18,2), "
        "orig_upb_blank_first DECIMAL(18,2), orig_upb_total DECIMAL(18,2), "
        "load_seconds DOUBLE, duckdb_version VARCHAR)"
    )

    # 3. Origination restatements tracker table
    con.execute(
        "CREATE TABLE IF NOT EXISTS origination_restatements_table ("
        "quarter VARCHAR, column_name VARCHAR, loans_restated BIGINT)"
    )

    # Refresh loan_monthly_view over any previously loaded quarters
    update_loan_monthly_view(con, parquet_dir)


def update_loan_monthly_view(con, parquet_dir: Path):
    """Rebuild loan_monthly_view over Parquet files in loaded_quarters_table.

    Uses absolute file paths recomputed at runtime. Moving the repo needs one
    rerun of 02_build_base_tables.py to refresh paths. If no quarters are loaded,
    the view is dropped if it exists.
    """
    quarters = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT quarter FROM loaded_quarters_table ORDER BY quarter"
        ).fetchall()
    ]
    valid_files = []
    for q in quarters:
        pf = (parquet_dir / f"{q}.parquet").resolve()
        if pf.exists():
            valid_files.append(str(pf).replace("\\", "/"))

    if not valid_files:
        con.execute("DROP VIEW IF EXISTS loan_monthly_view")
        return

    file_list_sql = ", ".join(f"'{f}'" for f in valid_files)

    monthly_select = [
        "regexp_extract(filename, '([0-9]{4}Q[1-4])', 1) AS acquisition_quarter",
        "loan_id",
        f"{PERIOD} AS reporting_period",
    ]
    for f in fields_for("loan_monthly"):
        monthly_select.append(f"{convert(f)} AS {f.column}")

    monthly_select += [
        "CASE WHEN delinquency_status IS NULL OR delinquency_status = 'XX' THEN NULL "
        "ELSE TRY_CAST(delinquency_status AS INTEGER) END AS delinquency_months",
        "COALESCE(delinquency_status = 'XX', FALSE) AS is_dpd_unknown",
    ]
    whens = " ".join(f"WHEN {sql_text(code)} THEN {sql_text(label)}" for code, label in EXIT_REASONS.items())
    monthly_select.append(f"CASE zero_balance_code {whens} END AS exit_reason")

    view_sql = f"""
    CREATE OR REPLACE VIEW loan_monthly_view AS
    SELECT {', '.join(monthly_select)}
    FROM read_parquet([{file_list_sql}], filename=true)
    """
    con.execute(view_sql)


def load_quarter_loans(con, quarter: str, parquet_file: Path) -> int:
    """Materialize unique loan records into loans_table from raw Parquet."""
    p_path = str(parquet_file).replace("\\", "/")
    names = ["loan_id", "acquisition_quarter"]
    values = ["loan_id", sql_text(quarter)]

    for f in loans_fields():
        names.append(f.column)
        val = convert(f)
        if f.target == "loans":
            # Latest corrected value per D-017
            values.append(f"arg_max({val}, period) FILTER (WHERE {val} IS NOT NULL)")
        else:
            # Earliest non-blank value for seller_name (5) and msa (32); arg_min skips blanks (D-027)
            values.append(f"arg_min({val}, period)")

    sql = f"""
    INSERT INTO loans_table ({', '.join(names)})
    SELECT {', '.join(values)}
    FROM (
        SELECT *, {PERIOD} AS period 
        FROM read_parquet('{p_path}')
        WHERE loan_id IS NOT NULL AND loan_id <> ''
    )
    GROUP BY loan_id;
    """
    con.execute(sql)
    return scalar(con, "SELECT count(*) FROM loans_table WHERE acquisition_quarter = ?", [quarter])


def record_restatements(con, quarter: str, parquet_file: Path) -> dict:
    """Count how many loans had restated origination fields across months."""
    p_path = str(parquet_file).replace("\\", "/")
    fields = [f for f in FIELDS if f.target in ("loans", "loans_first")]
    inner = ", ".join(f"count(DISTINCT {convert(f)}) AS {f.column}" for f in fields)
    outer = ", ".join(f"sum(CASE WHEN {f.column} > 1 THEN 1 ELSE 0 END) AS {f.column}" for f in fields)

    sql = f"SELECT {outer} FROM (SELECT loan_id, {inner} FROM read_parquet('{p_path}') GROUP BY loan_id)"
    cursor = con.execute(sql)
    row = cursor.fetchone()
    restated = {desc[0]: int(n) for desc, n in zip(cursor.description, row) if n}
    for col, count in restated.items():
        con.execute("INSERT INTO origination_restatements_table VALUES (?, ?, ?)", [quarter, col, count])
    return restated


def run_checks(
    con,
    quarter: str,
    parquet_file: Path,
    conversion_record: dict | None,
    unique_loans: int,
) -> tuple[list, dict]:
    """Run 7 integrity checks against the Parquet source and loans_table."""
    p_path = str(parquet_file).replace("\\", "/")

    # Check 1: Parquet rows = raw_lines from conversion record
    parquet_rows = scalar(con, f"SELECT count(*) FROM read_parquet('{p_path}')")
    if conversion_record is None:
        check1_actual = "Missing record"
        check1_expected = f"{quarter}.conversion.json exists"
    else:
        check1_actual = parquet_rows
        check1_expected = conversion_record.get("raw_lines")

    # Check 2: Unique loans loaded == unique loans in Parquet
    parquet_unique_loans = scalar(con, f"SELECT count(DISTINCT loan_id) FROM read_parquet('{p_path}')")

    # Check 3: Original UPB reconciliation
    # A = sum of each loan's first-month orig_upb (by reporting period)
    # R = sum over loans of (latest non-blank orig_upb - first-month orig_upb) where they differ and first month is not blank
    # B = sum of the latest non-blank orig_upb for loans whose first month is blank
    #     (the same value loans_table holds for them, per D-017)
    upb_sql = f"""
    WITH ranked AS (
        SELECT
            loan_id,
            TRY_CAST(orig_upb AS DECIMAL(18,2)) AS upb_dec,
            orig_upb AS upb_raw,
            try_strptime(reporting_period, '%m%Y')::DATE AS p_date,
            row_number() OVER (PARTITION BY loan_id ORDER BY try_strptime(reporting_period, '%m%Y')::DATE) AS rn
        FROM read_parquet('{p_path}')
        WHERE loan_id IS NOT NULL AND loan_id <> ''
    ),
    per_loan AS (
        SELECT
            loan_id,
            MAX(CASE WHEN rn = 1 THEN upb_dec END) AS first_month_upb,
            MAX(CASE WHEN rn = 1 AND (upb_raw IS NULL OR upb_raw = '') THEN 1 ELSE 0 END) AS is_first_blank,
            arg_max(upb_dec, p_date) FILTER (WHERE upb_raw IS NOT NULL AND upb_raw <> '') AS latest_upb
        FROM ranked
        GROUP BY loan_id
    )
    SELECT
        COALESCE(SUM(CASE WHEN is_first_blank = 0 AND first_month_upb IS NOT NULL THEN first_month_upb ELSE 0 END), 0) AS A,
        COALESCE(SUM(CASE WHEN is_first_blank = 0 AND first_month_upb IS NOT NULL AND latest_upb <> first_month_upb THEN latest_upb - first_month_upb ELSE 0 END), 0) AS R,
        COALESCE(SUM(CASE WHEN is_first_blank = 0 AND first_month_upb IS NOT NULL AND latest_upb <> first_month_upb THEN 1 ELSE 0 END), 0) AS count_R,
        COALESCE(SUM(CASE WHEN is_first_blank = 1 AND latest_upb IS NOT NULL THEN latest_upb ELSE 0 END), 0) AS B,
        COALESCE(SUM(CASE WHEN is_first_blank = 1 AND latest_upb IS NOT NULL THEN 1 ELSE 0 END), 0) AS count_B
    FROM per_loan;
    """
    upb_row = con.execute(upb_sql).fetchone()
    A, R, count_R, B, count_B = upb_row
    reconciled_total = A + R + B
    loaded_orig_upb = scalar(con, "SELECT COALESCE(sum(orig_upb), 0.0) FROM loans_table WHERE acquisition_quarter = ?", [quarter])

    reconcile_info = {
        "A": A,
        "R": R,
        "count_R": count_R,
        "B": B,
        "count_B": count_B,
        "loaded_total": loaded_orig_upb,
        "parquet_rows": parquet_rows,
    }

    # Check 4: No loan in another quarter
    other_quarter_overlap = scalar(
        con,
        f"SELECT count(*) FROM (SELECT DISTINCT loan_id FROM read_parquet('{p_path}')) p "
        f"JOIN loans_table l ON l.loan_id = p.loan_id WHERE l.acquisition_quarter <> ?",
        [quarter],
    )

    # Check 5: No duplicate (loan_id, reporting_period) keys AND no NULL loan_id or unreadable period
    dup_and_invalid_sql = f"""
    SELECT
        (SELECT count(*) - count(DISTINCT (loan_id, reporting_period)) FROM read_parquet('{p_path}')) +
        (SELECT count(*) FROM read_parquet('{p_path}') 
         WHERE loan_id IS NULL OR reporting_period IS NULL OR try_strptime(reporting_period, '%m%Y') IS NULL)
    """
    key_errors = scalar(con, dup_and_invalid_sql)

    # Check 6: Conversions - non-blank values that fail TRY_CAST to target type
    test_fields = [f for f in FIELDS if f.target != "not_loaded" and f.dtype != "text"]
    cast_checks = [
        f"CASE WHEN {f.column} IS NOT NULL AND {f.column} <> '' AND {convert(f)} IS NULL THEN 1 ELSE 0 END"
        for f in test_fields
    ]
    cast_sql = f"SELECT COALESCE(SUM({' + '.join(cast_checks)}), 0) FROM read_parquet('{p_path}')"
    conversion_fails = scalar(con, cast_sql)

    # Check 7: Allowed categorical values
    # zero_balance_code in EXIT_REASONS or NULL
    # modification_flag in ('Y', 'N') or NULL
    # delinquency_status NULL, 'XX', or 1-2 digit integer
    exit_codes_sql = ", ".join(sql_text(c) for c in EXIT_REASONS)
    mod_flags_sql = ", ".join(sql_text(f) for f in MODIFICATION_FLAG_VALUES)
    cat_sql = f"""
    SELECT
        COALESCE(SUM(CASE WHEN zero_balance_code IS NOT NULL AND zero_balance_code <> '' 
                          AND zero_balance_code NOT IN ({exit_codes_sql}) THEN 1 ELSE 0 END), 0) +
        COALESCE(SUM(CASE WHEN modification_flag IS NOT NULL AND modification_flag <> '' 
                          AND modification_flag NOT IN ({mod_flags_sql}) THEN 1 ELSE 0 END), 0) +
        COALESCE(SUM(CASE WHEN delinquency_status IS NOT NULL AND delinquency_status <> '' AND delinquency_status <> 'XX' 
                          AND NOT regexp_matches(delinquency_status, '^[0-9]{{1,2}}$') THEN 1 ELSE 0 END), 0)
    FROM read_parquet('{p_path}')
    """
    invalid_categoricals = scalar(con, cat_sql)

    results = [
        (1, "Raw lines match Parquet rows", check1_actual, check1_expected),
        (2, "Unique loans loaded match Parquet", unique_loans, parquet_unique_loans),
        (3, "Original UPB reconciliation (A + R + B)", loaded_orig_upb, reconciled_total),
        (4, "No loan overlap with other quarters", other_quarter_overlap, 0),
        (5, "No duplicate keys or unreadable periods", key_errors, 0),
        (6, "Non-blank conversion failures", conversion_fails, 0),
        (7, "Allowed categorical values", invalid_categoricals, 0),
    ]
    return results, reconcile_info


def write_data_log(
    data_log_path: Path,
    quarter: str,
    monthly_rows: int,
    loans: int,
    A: float,
    R: float,
    count_R: int,
    B: float,
    count_B: int,
    total_upb: float,
    load_seconds: float,
    active_cohorts: list[str],
    raw_csv_bytes: int,
    raw_lines: int,
    restated: dict,
    checks_passed: int,
    checks_total: int,
):
    """Prepend a new load entry to data_log.md."""
    top_restated = sorted(restated.items(), key=lambda kv: -kv[1])[:3]
    restated_str = ", ".join(f"{col} {n:,}" for col, n in top_restated) if top_restated else "none"
    header = "# Data ingestion log\nWritten by 02_build_base_tables.py. Do not edit.\n\n"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cohort_str = f"{len(active_cohorts)} cohort" if len(active_cohorts) == 1 else f"{len(active_cohorts)} cohorts"
    cohort_range = (
        f"({active_cohorts[0]} to {active_cohorts[-1]})"
        if len(active_cohorts) > 1
        else f"({active_cohorts[0]})"
    )

    entry = (
        f"## {now_str} | Quarter: {quarter}\n"
        f"- Acquisition cohort loaded      : {quarter}\n"
        f"- Raw file                       : {raw_csv_bytes / 1e9:,.2f} GB, {raw_lines:,} lines\n"
        f"- Monthly records in Parquet     : {monthly_rows:,}\n"
        f"- Unique loans loaded            : {loans:,}\n"
        f"- Original UPB first month (A)   : {A:,.2f}\n"
        f"- Original UPB restated (R)      : {R:,.2f} ({count_R:,} loans)\n"
        f"- Original UPB blank first (B)   : {B:,.2f} ({count_B:,} loans)\n"
        f"- Total original UPB loaded      : {total_upb:,.2f} (= A + R + B)\n"
        f"- Restated fields (top 3)        : {restated_str}\n"
        f"- Checks                         : {checks_passed} of {checks_total} PASS\n"
        f"- Load time                      : {format_seconds(load_seconds)}\n"
        f"- Active cohorts in database     : {cohort_str} {cohort_range}\n"
    )

    body = ""
    if data_log_path.exists():
        raw_text = data_log_path.read_text(encoding="utf-8")
        if raw_text.startswith(header):
            body = raw_text[len(header):]
        elif raw_text.startswith("# Data ingestion log"):
            lines = raw_text.splitlines(keepends=True)
            idx = 0
            while idx < len(lines) and not lines[idx].startswith("##"):
                idx += 1
            body = "".join(lines[idx:]).lstrip()
        else:
            body = raw_text

    new_text = header + entry + "\n---\n\n" + body if body else header + entry + "\n"
    data_log_path.write_text(new_text.strip() + "\n", encoding="utf-8")


def process_quarter(con, quarter: str, parquet_file: Path, db_is_default: bool) -> bool:
    """Load one quarter into loans_table, draw sample, run checks, and commit in one transaction."""
    already_loaded = scalar(con, "SELECT count(*) FROM loaded_quarters_table WHERE quarter = ?", [quarter])
    if already_loaded > 0:
        print(f"[{quarter}] SKIP: Already loaded in mortgages.duckdb")
        return False

    q_start = time.perf_counter()
    print(f"\n[{quarter}] START: Building Base Tables from Parquet...")

    # Load conversion record if available
    conv_file = parquet_file.with_name(f"{quarter}.conversion.json")
    conv_data = None
    if conv_file.exists():
        try:
            with open(conv_file, "r", encoding="utf-8") as f:
                conv_data = json.load(f)
        except Exception:
            conv_data = None

    con.execute("BEGIN TRANSACTION")
    try:
        # Step 1: Scan and materialize loans_table
        print_in_place(f"  ... [{quarter}] 1/3 Materializing loans_table...")
        loans_loaded = load_quarter_loans(con, quarter, parquet_file)
        print_final(f"  OK [{quarter}] 1/3 Materialized loans_table: {loans_loaded:,} loans")

        # Step 2: Track restatements
        print_in_place(f"  ... [{quarter}] 2/3 Tracking origination restatements...")
        restated = record_restatements(con, quarter, parquet_file)
        print_final(f"  OK [{quarter}] 2/3 Restated fields tracked: {len(restated)}")

        # Step 3: Run checks
        print_in_place(f"  ... [{quarter}] 3/3 Running 7 structural validation checks...")
        checks, info = run_checks(con, quarter, parquet_file, conv_data, loans_loaded)

        for check_num, title, actual, expected in checks:
            if actual != expected:
                raise ValueError(f"CHECK {check_num} FAILED ({title}): actual {actual} != expected {expected}")

        # Ledger record
        raw_csv_bytes = conv_data.get("raw_csv_bytes", 0) if conv_data else 0
        raw_lines = conv_data.get("raw_lines", 0) if conv_data else 0
        parquet_bytes = parquet_file.stat().st_size
        parquet_rows = info["parquet_rows"]
        load_time = time.perf_counter() - q_start

        con.execute(
            "INSERT INTO loaded_quarters_table VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                quarter,
                raw_csv_bytes,
                raw_lines,
                parquet_bytes,
                parquet_rows,
                loans_loaded,
                parquet_rows,
                info["A"],
                info["R"],
                info["B"],
                info["loaded_total"],
                load_time,
                duckdb.__version__,
            ],
        )

        con.execute("COMMIT")

    except Exception as e:
        con.execute("ROLLBACK")
        print_final(f"  FAIL [{quarter}] ERROR: Rolled back transaction. Reason: {e}")
        raise e

    # The quarter is now committed. Nothing below can roll it back.
    print_final(f"  OK [{quarter}] 3/3 All {len(checks)} checks PASS")
    print(
        f"  Reconciliation: A={info['A']:,.2f}, R={info['R']:,.2f} ({info['count_R']:,} loans), "
        f"B={info['B']:,.2f} ({info['count_B']:,} loans), Total={info['loaded_total']:,.2f}"
    )
    print(
        f"[{quarter}] COMPLETE in {format_seconds(load_time)}: {loans_loaded:,} loans | "
        f"Orig UPB: {info['loaded_total']:,.2f}"
    )

    # Add an entry at the top of data_log.md, only for the default database.
    if db_is_default:
        active_cohorts = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT quarter FROM loaded_quarters_table ORDER BY quarter"
            ).fetchall()
        ]
        try:
            write_data_log(
                DATA_LOG,
                quarter,
                parquet_rows,
                loans_loaded,
                info["A"],
                info["R"],
                info["count_R"],
                info["B"],
                info["count_B"],
                info["loaded_total"],
                load_time,
                active_cohorts,
                raw_csv_bytes,
                raw_lines,
                restated,
                len(checks),
                len(checks),
            )
        except Exception as e:
            print(f"  FAIL [{quarter}] Loaded and committed, but data_log.md was not written: {e}")
            raise

    return True


# =======================================================================================
# SECTION 3: CLI & ORCHESTRATION
# =======================================================================================

def list_available_parquet_quarters(parquet_dir: Path) -> list[str]:
    """Find all valid YYYYQn.parquet files in the parquet directory."""
    pattern = re.compile(r"^(\d{4})Q([1-4])\.parquet$", re.IGNORECASE)
    quarters = []
    for f in parquet_dir.glob("*.parquet"):
        match = pattern.match(f.name)
        if match:
            year, q = int(match.group(1)), int(match.group(2))
            quarters.append((year, q, f"{year}Q{q}"))
    quarters.sort()
    return [q[2] for q in quarters]


def build_quarter_list(args, available_quarters: list[str]) -> list[str]:
    """Resolve CLI arguments into an ordered list of quarters to process."""
    if args.all or (args.target and args.target[0].lower() == "all"):
        return available_quarters

    if args.quarter:
        _, _, q_clean = parse_quarter(args.quarter)
        return [q_clean]

    if args.from_quarter and args.to_quarter:
        start_y, start_q, _ = parse_quarter(args.from_quarter)
        end_y, end_q, _ = parse_quarter(args.to_quarter)
        if (start_y, start_q) > (end_y, end_q):
            sys.exit(f"Error: --from ({args.from_quarter}) is after --to ({args.to_quarter}).")
        return [
            q
            for q in available_quarters
            if parse_quarter(q)[:2] >= (start_y, start_q) and parse_quarter(q)[:2] <= (end_y, end_q)
        ]

    if args.target:
        if len(args.target) == 1:
            _, _, q_clean = parse_quarter(args.target[0])
            return [q_clean]
        elif len(args.target) == 2:
            start_y, start_q, _ = parse_quarter(args.target[0])
            end_y, end_q, _ = parse_quarter(args.target[1])
            if (start_y, start_q) > (end_y, end_q):
                sys.exit(f"Error: Start quarter ({args.target[0]}) is after end quarter ({args.target[1]}).")
            return [
                q
                for q in available_quarters
                if parse_quarter(q)[:2] >= (start_y, start_q) and parse_quarter(q)[:2] <= (end_y, end_q)
            ]
        else:
            sys.exit(f"Error: Too many positional arguments ({len(args.target)}). Expected at most 2.")

    sys.exit(
        "Error: Please specify quarters to process.\n"
        "Examples:\n"
        "  python residential_mortgage/00_data/scripts/02_build_base_tables.py 2005Q1\n"
        "  python residential_mortgage/00_data/scripts/02_build_base_tables.py 2000Q1 2008Q4\n"
        "  python residential_mortgage/00_data/scripts/02_build_base_tables.py all\n"
        "  python residential_mortgage/00_data/scripts/02_build_base_tables.py --quarter 2005Q1\n"
        "  python residential_mortgage/00_data/scripts/02_build_base_tables.py --from 2000Q1 --to 2008Q4"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Build DuckDB loans_table and monthly views from raw Parquet files."
    )
    parser.add_argument("target", nargs="*", help="Positional quarter: '2005Q1', '2000Q1 2008Q4', or 'all'")
    parser.add_argument("--quarter", help="Single quarter (e.g. 2005Q1)")
    parser.add_argument("--from", dest="from_quarter", help="Start quarter (e.g. 2000Q1)")
    parser.add_argument("--to", dest="to_quarter", help="End quarter (e.g. 2008Q4)")
    parser.add_argument("--all", action="store_true", help="Process all available parquet quarters")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Target DuckDB file")
    parser.add_argument("--parquet-dir", default=str(PARQUET_DIR), help="Parquet directory")

    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    parquet_dir = Path(args.parquet_dir).resolve()
    db_is_default = (db_path == DEFAULT_DB.resolve())

    db_path.parent.mkdir(parents=True, exist_ok=True)

    available_quarters = list_available_parquet_quarters(parquet_dir)
    quarters_to_run = build_quarter_list(args, available_quarters)

    if not quarters_to_run:
        sys.exit(f"Error: No matching quarters found in {parquet_dir}.")

    print("=" * 80)
    print("Build base tables (Parquet files -> mortgages.duckdb)")
    print(f"Parquet dir:  {parquet_dir}")
    print(f"Database:     {db_path}")
    print(f"Quarters:     {len(quarters_to_run)} queued ({quarters_to_run[0]} to {quarters_to_run[-1]})")
    print("=" * 80)

    con = duckdb.connect(str(db_path))
    try:
        init_database(con, parquet_dir)

        for quarter in quarters_to_run:
            parquet_file = parquet_dir / f"{quarter}.parquet"
            if not parquet_file.exists():
                print(f"[{quarter}] SKIP: Parquet file not found ({parquet_file.name})")
                continue
            process_quarter(con, quarter, parquet_file, db_is_default)

        # Refresh loan_monthly_view after all quarters are processed
        update_loan_monthly_view(con, parquet_dir)

        print("\nBase tables updated. loan_monthly_view covers the loaded quarters only.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
