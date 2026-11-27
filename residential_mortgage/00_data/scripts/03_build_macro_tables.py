"""Build the macroeconomic tables and views in DuckDB.

Raw files (in residential_mortgage/00_data/raw/macro/):
    * fedfunds.csv   : federal funds rate, monthly average (FRED, series FEDFUNDS)
    * unrate.csv     : unemployment rate, monthly (BLS via FRED, series UNRATE)
    * hpi_master.csv : house price indexes, national monthly and state quarterly (FHFA)

Tables and views built:
    * macro_monthly_table   : national monthly series, 2000-01 to the last federal funds month
    * macro_state_hpi_table : state quarterly house price index, 50 states and DC
    * macro_monthly_view    : view over macro_monthly_table
    * macro_economic_mart   : the macro features table. Monthly changes and the two
                              LGD discount rates.
    * macro_sources_table   : one row per source series: file, URL, saved date, last value

LGD discount rates (formulas are unchanged):
    * long-run rate = ROUND(federal funds rate + 5, 4)
      PRA SS11/13 13.13A: SONIA at the moment of default plus 5% for GBP exposures, and
      "a comparable liquid interest rate in the currency of that exposure" for others.
      The loans are in US dollars. We use the federal funds rate because, like SONIA,
      it is an unsecured overnight rate and it covers 2000 to 2026.
    * downturn rate = the higher of 9 and the long-run rate.
      PRA SS11/13 13.13 sets a 9% floor for downturn LGD (13.13B sets the same floor
      for LGD in-default). PS9/24 3.141 says "at least 9%".
      The "higher of" form is our stricter choice. It is not the PRA wording.
    * Join these rates on the month of default, not the reporting month.
    * The source rate is a monthly average, not the rate on the day of default.
    * SS4/24 replaces SS11/13 from 1 January 2027. Its paragraph numbers are not yet
      confirmed.
    * The departures from the UK rules are listed in docs\\departures_from_uk_rules.md.

Missing data:
    * A blank or absent unemployment month stays NULL and is flagged in
      unemployment_missing. Nothing is filled in.
    * Changes are taken by date (this month minus 1 or 12 months), not by row.
      A change that spans a missing month is NULL.

Timing warning: every value sits on the first day of its own month or quarter, before
it was published. The leakage audit must lag them. See macro_sources_table.

Downloads: nothing is downloaded unless --force-download is given.
6 checks run inside the transaction. The build is rolled back if any check fails.
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
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

for _p in (str(SCRIPT_DIR), str(PACKAGE_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _settings import config  # noqa: E402

_PATHS = config.paths()
_SOURCES = config.load("sources")

DEFAULT_DB = config.base_db_path(full=False)
FULL_DB = config.base_db_path(full=True)
DEFAULT_MACRO_DIR = _PATHS["macro_dir"]

# Unemployment months known to be blank in the source file. Any other blank month inside
# the series fails check 2. Add a month here only after confirming it is blank at the source.
KNOWN_UNEMPLOYMENT_GAPS = list(_SOURCES["fred"]["known_unemployment_gaps"])

# Module constants so a test can point them at file:// paths.
URL_FEDFUNDS = _SOURCES["fred"]["fedfunds_url"]
URL_UNRATE = _SOURCES["fred"]["unrate_url"]
URL_HPI_MASTER = _SOURCES["fhfa"]["hpi_url"]

# file name -> (header the first line must match, "equals" or "startswith")
EXPECTED_HEADERS = {
    "fedfunds.csv": ("observation_date,FEDFUNDS", "equals"),
    "unrate.csv": ("observation_date,UNRATE", "equals"),
    "hpi_master.csv": ("hpi_type,hpi_flavor,frequency,level", "startswith"),
}


# Build active download URL map for FRED rates, unemployment, and FHFA house price indices
# Substitutes configured national HPI release suffix into raw filenames dynamically
def source_urls() -> dict:
    """File name -> URL. Read at call time so tests can change the constants."""
    return {
        "fedfunds.csv": URL_FEDFUNDS,
        "unrate.csv": URL_UNRATE,
        "hpi_master.csv": URL_HPI_MASTER,
    }


# ---------------------------------------------------------------------------------------
# Raw files and downloads
# ---------------------------------------------------------------------------------------
# Validate the first CSV header line of a downloaded macro file before promoting it
# Reads line 1 UTF-8 text and compares via equals or startswith against RAW_FILE_CHECKS
def first_line_ok(path: Path, filename: str) -> bool:
    """True if the first line of the file is the expected header."""
    header, mode = EXPECTED_HEADERS[filename]
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            line = f.readline().strip()
    except OSError:
        return False
    return line == header if mode == "equals" else line.startswith(header)


# Fetch a macro series CSV via urllib into a staging temporary path
# Streams network response in 64 KB chunks using a browser user-agent header and timeout
def download_to_temp(url: str, dest: Path) -> Path:
    """Download url to a .tmp file next to dest. Return the .tmp path or exit 1."""
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    res = subprocess.run(
        ["curl.exe", "--fail", "-s", "-L", url, "-o", str(tmp)],
        capture_output=True, text=True,
    )
    if res.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        if tmp.exists():
            tmp.unlink()
        sys.exit(f"Download failed for {url} (curl code {res.returncode}). Old file kept.")
    if not first_line_ok(tmp, dest.name):
        tmp.unlink()
        sys.exit(f"Download of {url} does not start with the expected header. Old file kept.")
    return tmp


# Guarantee all four raw macro CSVs exist locally and pass header checks
# Downloads any missing files (or all on --force-download) to temp, verifies headers, then swaps
def ensure_macro_sources(macro_dir: Path, force_download: bool = False):
    """Make sure the raw files exist. Download only when --force-download is given."""
    urls = source_urls()
    missing = [n for n in urls if not (macro_dir / n).exists() or (macro_dir / n).stat().st_size == 0]
    if missing and not force_download:
        print(f"Missing raw file(s) in {macro_dir}: {', '.join(missing)}")
        print("Nothing was downloaded. Run again with --force-download to download them.")
        sys.exit(1)

    if force_download:
        macro_dir.mkdir(parents=True, exist_ok=True)
        # Download and check every file first, then replace, so one bad file changes nothing.
        temps = {}
        try:
            for name, url in urls.items():
                print(f"Downloading {name}...")
                temps[name] = download_to_temp(url, macro_dir / name)
        except SystemExit:
            for t in temps.values():
                if t.exists():
                    t.unlink()
            raise
        for name, tmp in temps.items():
            dest = macro_dir / name
            if dest.exists():
                old_date = datetime.fromtimestamp(dest.stat().st_mtime).strftime("%Y-%m-%d_%H%M")
                dest.replace(dest.with_name(f"{dest.stem}.{old_date}.csv"))
            tmp.replace(dest)
            print(f"  Saved {name} ({dest.stat().st_size:,} bytes)")


# Execute a one-value SQL lookup against DuckDB and return its top-left field
# Calls fetchone() on con.execute(sql, params) safely
def scalar(con, sql: str, params=None):
    """Run a query and return a single value."""
    return con.execute(sql, params or []).fetchone()[0]


# ---------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------
# Run six completeness, timeliness, key, state-grid, and discount-rate validation checks
# Verifies continuous dates from 2000-01, lag ceilings, 51 state series, and downturn bounds
def run_checks(con) -> list[tuple[int, str, bool, str]]:
    """Run the 6 checks against the 5 macro tables. Return (number, title, ok, detail)."""
    results = []

    # 1. Coverage: first month, last month, no gap.
    # In a normal build the month calendar makes the months complete from 2000-01, so a
    # gap in a source file shows up in check 2 (rates) or check 3 (house prices). This
    # check guards the table itself: a short history, a lost row or an extra row.
    n, first, last = con.execute(
        "SELECT count(*), min(period), max(period) FROM macro_monthly_table"
    ).fetchone()
    if n == 0 or first is None:
        ok, detail = False, "no rows"
    else:
        expected = scalar(con, "SELECT datediff('month', ?::DATE, ?::DATE) + 1", [first, last])
        ok = (str(first) == "2000-01-01" and str(last) >= "2025-12-01" and n == expected)
        detail = f"{n} rows, {first} to {last}, expected {expected} months with no gap"
    results.append((1, "Months start 2000-01, reach 2025-12 or later, no gap", ok, detail))

    # 2. No NULL keys; unemployment blank only in a known gap or after its last published
    #    month (how far behind it may run is check 3's job)
    nulls_monthly, nulls_features = con.execute(
        "SELECT (SELECT count(*) FROM macro_monthly_table "
        "        WHERE period IS NULL OR federal_funds_rate_pct IS NULL), "
        "       (SELECT count(*) FROM macro_economic_mart "
        "        WHERE period IS NULL OR federal_funds_rate_pct IS NULL)"
    ).fetchone()
    key_nulls = nulls_monthly + nulls_features
    unemp_nulls = scalar(
        con,
        "SELECT count(*) FROM macro_monthly_table "
        "WHERE unemployment_rate_pct IS NULL AND unemployment_missing IS NOT TRUE",
    )
    unknown_gaps = scalar(
        con,
        "SELECT count(*) FROM macro_monthly_table "
        "WHERE unemployment_rate_pct IS NULL "
        "  AND CAST(period AS VARCHAR) NOT IN (SELECT unnest(?::VARCHAR[])) "
        "  AND period < (SELECT max(period) FROM macro_monthly_table "
        "                WHERE unemployment_rate_pct IS NOT NULL)",
        [KNOWN_UNEMPLOYMENT_GAPS],
    )
    state_nulls = scalar(
        con,
        "SELECT count(*) FROM macro_state_hpi_table "
        "WHERE house_price_index_sa IS NULL OR house_price_index_nsa IS NULL "
        "   OR house_price_index_all_sales_nsa IS NULL",
    )
    ok = key_nulls == 0 and unemp_nulls == 0 and unknown_gaps == 0 and state_nulls == 0
    results.append((
        2, "No NULL period or rate; unemployment blank only in a known gap; no NULL state index", ok,
        f"NULL period/rate: {nulls_monthly} in monthly table, {nulls_features} in macro "
        f"features table; {unemp_nulls} unflagged NULL unemployment, "
        f"{unknown_gaps} blank unemployment months not in the known gaps "
        f"({', '.join(g[:7] for g in KNOWN_UNEMPLOYMENT_GAPS)}); {state_nulls} NULL state index",
    ))

    # 3. Bounds, and each series runs close enough to the last rate month:
    #    national index at most 3 months behind, unemployment at most 2 months,
    #    state index (dated on the first day of its quarter) at most 9 months.
    bad_rates = scalar(
        con,
        "SELECT count(*) FROM macro_monthly_table "
        "WHERE federal_funds_rate_pct < 0 OR federal_funds_rate_pct > 25 "
        "   OR unemployment_rate_pct < 2 OR unemployment_rate_pct > 20",
    )
    bad_nat = scalar(
        con,
        "SELECT count(*) FROM macro_monthly_table "
        "WHERE national_house_price_index_sa <= 50 OR national_house_price_index_nsa <= 50",
    )
    bad_state = scalar(
        con,
        "SELECT count(*) FROM macro_state_hpi_table "
        "WHERE house_price_index_sa <= 50 OR house_price_index_nsa <= 50 "
        "   OR house_price_index_all_sales_nsa <= 50",
    )
    last_pub, last_rate = con.execute(
        "SELECT max(period) FILTER (WHERE national_house_price_index_sa IS NOT NULL), "
        "       max(period) FILTER (WHERE federal_funds_rate_pct IS NOT NULL) "
        "FROM macro_monthly_table"
    ).fetchone()
    if last_pub is None or last_rate is None:
        blanks, lag_months, lag_ok = 0, None, False
    else:
        blanks = scalar(
            con,
            "SELECT count(*) FROM macro_monthly_table "
            "WHERE period < ? AND national_house_price_index_sa IS NULL",
            [last_pub],
        )
        lag_months = scalar(con, "SELECT datediff('month', ?::DATE, ?::DATE)", [last_pub, last_rate])
        lag_ok = lag_months <= 3
    last_un = scalar(
        con, "SELECT max(period) FROM macro_monthly_table WHERE unemployment_rate_pct IS NOT NULL"
    )
    last_state = scalar(con, "SELECT max(quarter_date) FROM macro_state_hpi_table")
    if last_rate is None or last_un is None or last_state is None:
        un_lag, state_lag, fresh_ok = None, None, False
    else:
        un_lag = scalar(con, "SELECT datediff('month', ?::DATE, ?::DATE)", [last_un, last_rate])
        state_lag = scalar(con, "SELECT datediff('month', ?::DATE, ?::DATE)", [last_state, last_rate])
        fresh_ok = un_lag <= 2 and state_lag <= 9
    ok = (bad_rates == 0 and bad_nat == 0 and bad_state == 0 and blanks == 0
          and lag_ok and fresh_ok)
    results.append((
        3, "Rates and indexes within bounds; all series close to the last rate month", ok,
        f"{bad_rates} rate, {bad_nat} national index, {bad_state} state index out of bounds; "
        f"{blanks} blank national months before last published; months behind last rate "
        f"month: national index {lag_months}, unemployment {un_lag}, state index {state_lag}",
    ))

    # 4. No duplicate keys
    dup_monthly = scalar(con, "SELECT count(*) - count(DISTINCT period) FROM macro_monthly_table")
    dup_mart = scalar(con, "SELECT count(*) - count(DISTINCT period) FROM macro_economic_mart")
    dup_state = scalar(
        con,
        "SELECT count(*) - count(DISTINCT (state, quarter_date)) FROM macro_state_hpi_table",
    )
    ok = dup_monthly == 0 and dup_mart == 0 and dup_state == 0
    results.append((
        4, "No duplicate month or (state, quarter)", ok,
        f"{dup_monthly} duplicate months in monthly table, {dup_mart} in macro features table, "
        f"{dup_state} duplicate state quarters",
    ))

    # 5. 51 states, each with every quarter from 2000Q1 to the last quarter, no gap
    n_states, complete, min_q, max_q, last_q = con.execute(
        """
        WITH s AS (
            SELECT state, min(quarter_date) AS first_q, max(quarter_date) AS last_q,
                   count(*) AS q
            FROM macro_state_hpi_table GROUP BY state
        ), overall AS (SELECT max(quarter_date) AS last_q FROM macro_state_hpi_table)
        SELECT count(*),
               count(*) FILTER (WHERE s.first_q = DATE '2000-01-01'
                                  AND s.last_q = overall.last_q
                                  AND s.q = datediff('quarter', s.first_q, s.last_q) + 1),
               min(s.q), max(s.q), any_value(overall.last_q)
        FROM s, overall
        """
    ).fetchone()
    ok = n_states == 51 and complete == 51
    results.append((
        5, "51 states, each with every quarter from 2000Q1 to the last quarter", ok,
        f"{n_states} states, {complete} complete to {last_q}, quarters per state {min_q} to {max_q}",
    ))

    # 6. Discount rates on every row of the macro features table
    n_rows = scalar(con, "SELECT count(*) FROM macro_economic_mart")
    bad_rates6 = scalar(
        con,
        """
        SELECT count(*) FROM (
            SELECT lgd_discount_rate_long_run_pct AS lr,
                   lgd_discount_rate_downturn_pct AS dt,
                   ROUND(federal_funds_rate_pct + 5, 4) AS exp_lr
            FROM macro_economic_mart
        )
        WHERE lr IS NULL OR dt IS NULL OR exp_lr IS NULL
           OR lr <> exp_lr
           OR dt <> CASE WHEN exp_lr > 9 THEN exp_lr ELSE 9.0000 END
        """,
    )
    ok = n_rows > 0 and bad_rates6 == 0
    results.append((
        6, "Discount rates: long-run = rate + 5, downturn = higher of 9 and long-run", ok,
        f"{bad_rates6} bad rows of {n_rows}",
    ))

    return results


# ---------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------
SOURCE_NOTES = [
    # series_name, file_name, publication_delay
    ("federal funds rate", "fedfunds.csv", "monthly average, published early the next month"),
    ("unemployment rate", "unrate.csv", "about 1 month after the month"),
    ("national house price index monthly", "hpi_master.csv", "about 2 months after the month"),
    ("state house price index quarterly", "hpi_master.csv", "about 2 months after the quarter ends"),
]


# Transform raw FRED and FHFA CSVs into monthly/quarterly macro tables and LGD discount marts
# Creates clean calendar tables, computes 1m/12m shifts inside a transaction, and validates checks
def build_macro_tables(con, macro_dir: Path):
    """Build the tables and views, run the checks, commit only if all pass.

    Returns (checks, all_ok).
    """
    p = str(macro_dir).replace("\\", "/")
    ff_path, un_path, hpi_path = f"{p}/fedfunds.csv", f"{p}/unrate.csv", f"{p}/hpi_master.csv"
    urls = source_urls()

    con.execute("BEGIN TRANSACTION")
    try:
        # Raw files, read as text so blanks stay blank.
        # trim() makes sure an unreadable value (such as "abc") becomes NULL instead of
        # stopping the run, so check 2 can report it.
        con.execute(f"""
        CREATE OR REPLACE TEMP VIEW raw_fedfunds AS
        SELECT observation_date::DATE AS period, TRY_CAST(trim(FEDFUNDS) AS DECIMAL(6,4)) AS rate
        FROM read_csv('{ff_path}', all_varchar = true)
        """)
        con.execute(f"""
        CREATE OR REPLACE TEMP VIEW raw_unrate AS
        SELECT observation_date::DATE AS period,
               UNRATE AS raw_value,
               TRY_CAST(trim(UNRATE) AS DECIMAL(5,2)) AS rate
        FROM read_csv('{un_path}', all_varchar = true)
        """)
        con.execute(f"""
        CREATE OR REPLACE TEMP VIEW raw_hpi AS
        SELECT hpi_type, hpi_flavor, frequency, level, place_id,
               yr::INT AS yr, period::INT AS per,
               TRY_CAST(trim(index_sa) AS DECIMAL(8,2)) AS index_sa,
               TRY_CAST(trim(index_nsa) AS DECIMAL(8,2)) AS index_nsa
        FROM read_csv('{hpi_path}', all_varchar = true)
        """)
        con.execute("""
        CREATE OR REPLACE TEMP VIEW raw_hpi_national AS
        SELECT MAKE_DATE(yr, per, 1) AS period, index_sa, index_nsa
        FROM raw_hpi
        WHERE level = 'USA or Census Division' AND place_id = 'USA'
          AND frequency = 'monthly' AND hpi_flavor = 'purchase-only'
          AND hpi_type = 'traditional'
        """)
        con.execute("""
        CREATE OR REPLACE TEMP VIEW raw_hpi_state AS
        SELECT place_id AS state, yr, per,
               MAKE_DATE(yr, (per - 1) * 3 + 1, 1) AS quarter_date,
               hpi_flavor, index_sa, index_nsa
        FROM raw_hpi
        WHERE level = 'State' AND hpi_type = 'traditional' AND frequency = 'quarterly'
        """)

        # Month calendar from 1998-01 to the last month in the federal funds file, even if
        # that month is blank (then check 2 fails instead of the month being dropped).
        # Each series is left-joined, so a missing month shows as NULL.
        con.execute("""
        CREATE OR REPLACE TEMP TABLE macro_calendar AS
        WITH last_month AS (
            SELECT max(period) AS last_period FROM raw_fedfunds
        ),
        cal AS (
            SELECT g::DATE AS period
            FROM last_month, generate_series(DATE '1998-01-01', last_month.last_period, INTERVAL 1 MONTH) t(g)
        )
        SELECT c.period,
               f.rate  AS federal_funds_rate_pct,
               u.rate  AS unemployment_rate_pct,
               (u.raw_value IS NULL OR trim(u.raw_value) = '') AS unemployment_missing,
               h.index_sa  AS national_house_price_index_sa,
               h.index_nsa AS national_house_price_index_nsa
        FROM cal c
        LEFT JOIN raw_fedfunds f ON f.period = c.period
        LEFT JOIN raw_unrate u ON u.period = c.period
        LEFT JOIN raw_hpi_national h ON h.period = c.period
        """)

        # National monthly table. Changes are taken by date (period minus 1 or 12 months).
        con.execute("DROP VIEW IF EXISTS macro_monthly_view")
        con.execute("DROP TABLE IF EXISTS macro_economic_mart")
        con.execute("DROP TABLE IF EXISTS macro_monthly_table")
        con.execute("""
        CREATE TABLE macro_monthly_table AS
        SELECT
            c.period,
            strftime(c.period, '%m%Y') AS reporting_period,
            EXTRACT(year FROM c.period)::INT AS year,
            EXTRACT(month FROM c.period)::INT AS month,
            concat(EXTRACT(year FROM c.period)::VARCHAR, 'Q', EXTRACT(quarter FROM c.period)::VARCHAR) AS quarter_label,
            c.federal_funds_rate_pct,
            c.unemployment_rate_pct,
            c.unemployment_missing,
            c.national_house_price_index_sa,
            c.national_house_price_index_nsa,
            c.unemployment_rate_pct - p1.unemployment_rate_pct  AS unemployment_change_1m,
            c.unemployment_rate_pct - p12.unemployment_rate_pct AS unemployment_change_12m,
            ROUND((c.national_house_price_index_sa - p1.national_house_price_index_sa)
                  / NULLIF(p1.national_house_price_index_sa, 0) * 100, 4) AS house_price_change_1m_pct,
            ROUND((c.national_house_price_index_sa - p12.national_house_price_index_sa)
                  / NULLIF(p12.national_house_price_index_sa, 0) * 100, 4) AS house_price_change_12m_pct
        FROM macro_calendar c
        LEFT JOIN macro_calendar p1  ON p1.period  = (c.period - INTERVAL 1 MONTH)::DATE
        LEFT JOIN macro_calendar p12 ON p12.period = (c.period - INTERVAL 12 MONTH)::DATE
        WHERE c.period >= DATE '2000-01-01'
        ORDER BY c.period
        """)

        # State quarterly table. Yearly change by quarter_date minus 12 months, same state.
        # One row per purchase-only source row, with the all-sales index joined on. Nothing
        # is grouped, so a duplicated source row gives a duplicated row and check 4 fails.
        con.execute("DROP TABLE IF EXISTS macro_state_hpi_table")
        con.execute("""
        CREATE TABLE macro_state_hpi_table AS
        WITH s AS (
            SELECT po.state, po.yr AS year, po.per AS quarter,
                   concat(po.yr::VARCHAR, 'Q', po.per::VARCHAR) AS quarter_label,
                   po.quarter_date,
                   po.index_sa  AS house_price_index_sa,
                   po.index_nsa AS house_price_index_nsa,
                   alls.index_nsa AS house_price_index_all_sales_nsa
            FROM raw_hpi_state po
            LEFT JOIN raw_hpi_state alls
              ON alls.state = po.state AND alls.quarter_date = po.quarter_date
             AND alls.hpi_flavor = 'all-transactions'
            WHERE po.hpi_flavor = 'purchase-only' AND po.yr >= 1998
        )
        SELECT c.state, c.year, c.quarter, c.quarter_label, c.quarter_date,
               c.house_price_index_sa, c.house_price_index_nsa, c.house_price_index_all_sales_nsa,
               ROUND((c.house_price_index_sa - p.house_price_index_sa)
                     / NULLIF(p.house_price_index_sa, 0) * 100, 4) AS house_price_change_12m_pct
        FROM s c
        LEFT JOIN s p ON p.state = c.state AND p.quarter_date = (c.quarter_date - INTERVAL 12 MONTH)::DATE
        WHERE c.year >= 2000
        ORDER BY c.state, c.quarter_date
        """)

        con.execute("CREATE VIEW macro_monthly_view AS SELECT * FROM macro_monthly_table")

        # Macro features table (macro_economic_mart) with the LGD discount rates.
        # The downturn rate uses CASE so that a blank long-run rate gives a blank downturn rate.
        con.execute("""
        CREATE TABLE macro_economic_mart AS
        WITH r AS (
            SELECT *, ROUND(federal_funds_rate_pct + 5, 4) AS long_run
            FROM macro_monthly_table
        )
        SELECT period, reporting_period, year, month, quarter_label,
               federal_funds_rate_pct, unemployment_rate_pct, unemployment_missing,
               national_house_price_index_sa,
               unemployment_change_1m, unemployment_change_12m,
               house_price_change_1m_pct, house_price_change_12m_pct,
               long_run AS lgd_discount_rate_long_run_pct,
               CASE WHEN long_run IS NULL THEN NULL
                    WHEN long_run > 9 THEN long_run
                    ELSE 9.0000 END AS lgd_discount_rate_downturn_pct
        FROM r
        ORDER BY period
        """)

        # Sources table: one row per series.
        con.execute("DROP TABLE IF EXISTS macro_sources_table")
        con.execute("""
        CREATE TABLE macro_sources_table (
            series_name VARCHAR, file_name VARCHAR, source_url VARCHAR,
            file_saved_date DATE, first_observation DATE, last_observation DATE,
            rows_read BIGINT, publication_delay VARCHAR, recorded_at TIMESTAMP
        )
        """)
        stats = {
            "federal funds rate": "SELECT min(period) FILTER (WHERE rate IS NOT NULL), "
                                  "max(period) FILTER (WHERE rate IS NOT NULL), count(*) FROM raw_fedfunds",
            "unemployment rate": "SELECT min(period) FILTER (WHERE rate IS NOT NULL), "
                                 "max(period) FILTER (WHERE rate IS NOT NULL), count(*) FROM raw_unrate",
            "national house price index monthly":
                "SELECT min(period) FILTER (WHERE index_sa IS NOT NULL), "
                "max(period) FILTER (WHERE index_sa IS NOT NULL), count(*) FROM raw_hpi_national",
            "state house price index quarterly":
                "SELECT min(quarter_date) FILTER (WHERE index_sa IS NOT NULL), "
                "max(quarter_date) FILTER (WHERE index_sa IS NOT NULL), count(*) "
                "FROM raw_hpi_state WHERE hpi_flavor = 'purchase-only'",
        }
        for series_name, file_name, delay in SOURCE_NOTES:
            first_obs, last_obs, n_read = con.execute(stats[series_name]).fetchone()
            saved = datetime.fromtimestamp((macro_dir / file_name).stat().st_mtime).date()
            con.execute(
                "INSERT INTO macro_sources_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, now()::TIMESTAMP)",
                [series_name, file_name, urls[file_name], saved, first_obs, last_obs, n_read, delay],
            )

        # Checks, inside the transaction.
        checks = run_checks(con)
        for num, title, ok, detail in checks:
            print(f"  {'PASS' if ok else 'FAIL'} check {num}: {title} ({detail})")
        all_ok = all(c[2] for c in checks)
        con.execute("COMMIT" if all_ok else "ROLLBACK")
        return checks, all_ok

    except Exception:
        con.execute("ROLLBACK")
        raise


# Parse macro pipeline flags, sync raw CSV inputs, populate DuckDB tables, and print diagnostics
# Updates either sample or --full mortgages DuckDB cleanly and rolls back on any failed check
def main():
    parser = argparse.ArgumentParser(description="Build the macroeconomic tables in DuckDB.")
    parser.add_argument("--db", default=None, help="Target DuckDB file (overrides default sample / --full)")
    parser.add_argument("--full", action="store_true", help="Write into full mortgages.duckdb instead of sample DB")
    parser.add_argument("--macro-dir", default=str(DEFAULT_MACRO_DIR), help="Folder with the raw CSV files")
    parser.add_argument("--force-download", action="store_true",
                        help="Download the raw files again (old files are kept with their date)")
    args = parser.parse_args()

    target_db = Path(args.db) if args.db else (FULL_DB if args.full else DEFAULT_DB)
    db_path = target_db.resolve()
    macro_dir = Path(args.macro_dir).resolve()
    start = time.perf_counter()

    ensure_macro_sources(macro_dir, force_download=args.force_download)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        print(f"Target database: {db_path}")
        print("Checks:")
        checks, all_ok = build_macro_tables(con, macro_dir)
        if not all_ok:
            print("OVERALL: FAIL (rolled back)")
            sys.exit(1)

        print("Files used:")
        for name, fname, last_obs, saved in con.execute(
            "SELECT series_name, file_name, last_observation, file_saved_date "
            "FROM macro_sources_table ORDER BY rowid"
        ).fetchall():
            print(f"  {name}: {fname}, saved {saved}, last value {last_obs}")

        m_rows, min_p, max_p = con.execute(
            "SELECT count(*), min(period), max(period) FROM macro_monthly_table"
        ).fetchone()
        s_rows, n_states = con.execute(
            "SELECT count(*), count(DISTINCT state) FROM macro_state_hpi_table"
        ).fetchone()
        n_quarters = scalar(con, "SELECT count(DISTINCT quarter_date) FROM macro_state_hpi_table")
        f_rows = scalar(con, "SELECT count(*) FROM macro_economic_mart")
        missing = [str(r[0])[:7] for r in con.execute(
            "SELECT period FROM macro_monthly_table WHERE unemployment_missing ORDER BY period"
        ).fetchall()]
        print("Row counts:")
        print(f"  macro_monthly_table   : {m_rows:,} months ({min_p} to {max_p})")
        print(f"  macro_state_hpi_table : {s_rows:,} rows ({n_states} states x {n_quarters} quarters)")
        print(f"  macro features table (macro_economic_mart): {f_rows:,} rows")
        print(f"  macro_sources_table   : {scalar(con, 'SELECT count(*) FROM macro_sources_table')} rows")
        last_un = scalar(con, "SELECT max(period) FROM macro_monthly_table WHERE unemployment_rate_pct IS NOT NULL")
        last_un = str(last_un)[:7] if last_un is not None else "9999-99"
        gaps = [m for m in missing if m <= last_un]
        not_yet = [m for m in missing if m > last_un]
        unit = "month" if len(gaps) == 1 else "months"
        listing = f" ({', '.join(gaps)})" if gaps else ""
        print(f"Unemployment missing in source: {len(gaps)} {unit}{listing}")
        if not_yet:
            print(f"Unemployment not yet published after {last_un}: {', '.join(not_yet)} (also flagged)")
        print(f"OVERALL: PASS in {time.perf_counter() - start:.2f}s")
    finally:
        con.close()


if __name__ == "__main__":
    main()
