"""Feature catalogue: one approved register of every field in loans_table and loan_monthly_view.

It takes the class, lag rule and usable flag from field_leakage_table (step 6) unchanged and
adds the database data type, the fill rate and a data-treatment note. The result is saved as
feature_catalogue_table and exported as a Markdown file.

Run: python residential_mortgage\\01_data_foundation\\scripts\\04_feature_catalogue.py [--db PATH] [--full] [--md PATH]
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_FOUNDATION_DIR = SCRIPT_DIR.parent
PACKAGE_ROOT = DATA_FOUNDATION_DIR.parent
DATA_SCRIPTS_DIR = PACKAGE_ROOT / "00_data" / "scripts"

for _p in (str(PACKAGE_ROOT), str(DATA_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
from field_map import FIELDS, EXIT_REASONS  # noqa: E402

DEFAULT_DB = config.base_db_path(full=False)
FULL_DB = config.base_db_path(full=True)
SAMPLE_RATE_PCT = config.load("sampling")["sampling"]["rate"] * 100

LOANS = "loans_table"
MONTHLY = "loan_monthly_view"
CLASS_ORDER = ["origination", "monthly_lag_1", "quarantined", "key"]

# Data-treatment notes: field name to note. These are the only notes.
exit_codes = "; ".join(f"{code} {label}" for code, label in EXIT_REASONS.items())
LATEST_VALUE_NOTE = (
    "Latest non-blank value over the loan's life: Fannie Mae's corrected value (D-017). "
    "A lender would not have had a corrected value on day one; see loans restated."
)
FIRST_MONTH_NOTE = (
    "Value from the loan's first month (D-017). Later months can show the buyer after a "
    "merger (seller) or new area boundaries (MSA)."
)
TREATMENT_NOTES = {
    "delinquency_status": "Months in arrears as text. XX means the status was not known that month; 99 means 99 months or more. Kept as given.",
    "delinquency_months": "delinquency_status as a whole number. XX and blank become NULL, so a NULL here is not \"up to date\".",
    "is_dpd_unknown": "TRUE where delinquency_status is XX, FALSE otherwise. Use it with delinquency_months to tell \"not known\" from \"blank\".",
    "zero_balance_code": f"Blank while the loan is active. Codes: {exit_codes}. Any other code fails the load.",
    "exit_reason": f"Label of zero_balance_code, from the same {len(EXIT_REASONS)} codes. NULL while the loan is active.",
    "modification_flag": "Y, N or blank. It can go from Y back to N, so \"ever modified\" must be built from all months up to t-1, not from the latest month.",
    "current_upb": "Stored as given. Filling the masked early months is left to the module that first needs it.",
}
# Every loans_table field the field map sends to loans (31) keeps the latest value;
# seller_name and msa (loans_first) keep the first month's value.
for f in FIELDS:
    if f.target == "loans":
        TREATMENT_NOTES[f.column] = LATEST_VALUE_NOTE
    elif f.target == "loans_first":
        TREATMENT_NOTES[f.column] = FIRST_MONTH_NOTE

# The four classes: usable, lag rule, and meaning (wording from the step 6 spec).
CLASS_TEXT = {
    "origination": ("yes", "none", "Known when the loan is made. Usable in every month."),
    "monthly_lag_1": ("yes", "t-1", "Known at the reporting date. A model predicting month t uses month t-1 or earlier, and so does any summary built from it."),
    "quarantined": ("no", "never", "Outcome, exit or loss information. Used only to build targets."),
    "key": ("no", "join only", "Identifies the loan, the month or the quarter. Used to join and order time."),
}
SECTION_TITLE = {
    "origination": "Origination fields ({n}, usable, lag none)",
    "monthly_lag_1": "Monthly fields, use month t-1 ({n}, usable)",
    "quarantined": "Quarantined fields ({n}, not usable)",
    "key": "Key fields ({n}, not features)",
}
SUMMARY_TEXT = {
    "origination": "usable",
    "monthly_lag_1": "usable, month t-1",
    "quarantined": "not usable",
    "key": "not usable",
}


# Read the column names and data types of one table or view.
def column_types(con, source_object):
    rows = con.execute(f"DESCRIBE {source_object}").fetchall()
    return {row[0]: row[1] for row in rows}


# Read field_leakage_table and put the rows in catalogue order:
# class, then loans_table first, then layout position (blank last), then field name.
def read_leakage_rows(con):
    rows = con.execute(
        "SELECT field_name, source_object, layout_position, layout_name, field_class, "
        "lag_rule, usable_as_feature, loans_restated, reason FROM field_leakage_table"
    ).fetchall()

    def order(r):
        position = r[2] if r[2] is not None else 10**6
        return (CLASS_ORDER.index(r[4]), 0 if r[1] == LOANS else 1, position, r[0])

    return sorted(rows, key=order)


# Count rows and filled rows for every column of one source object, in one query.
def measure_fill(con, source_object, types, names):
    parts = ["COUNT(*)"]
    for name in names:
        if types[name] == "VARCHAR":
            parts.append(f"COUNT(NULLIF(TRIM(\"{name}\"), ''))")
        else:
            parts.append(f"COUNT(\"{name}\")")
    sql = f"SELECT {', '.join(parts)} FROM {source_object}"
    result = con.execute(sql).fetchone()
    return result[0], {name: result[i + 1] for i, name in enumerate(names)}


# Build the catalogue rows in the column order of feature_catalogue_table.
def build_rows(leakage_rows, types, fill, measured_on):
    rows = []
    for (name, source, position, layout_name, field_class, lag_rule, usable,
         restated, reason) in leakage_rows:
        checked, filled_by_name = fill[source]
        filled = filled_by_name[name]
        fill_rate = filled / checked if checked else None
        rows.append((name, source, field_class, lag_rule, usable, types[source][name],
                     position, layout_name, reason, checked, filled, fill_rate,
                     measured_on, restated, TREATMENT_NOTES.get(name)))
    return rows


# Print up to 5 names for a failed stop check.
def print_names(label, pairs):
    names = ", ".join(f"{s}.{n}" for s, n in pairs[:5])
    print(f"      {label}: {len(pairs)} ({names})")


# Data treatment bullets for one class. Fields that share a note are listed together.
def treatment_bullets(class_rows):
    noted = [r for r in class_rows if r[14]]
    notes = []
    for r in noted:
        if r[14] not in notes:
            notes.append(r[14])
    lines = []
    for note in notes:
        names = [r[0] for r in noted if r[14] == note]
        if len(names) > 5:
            others = [r[0] for r in class_rows if r[14] != note]
            label = "All fields except " + ", ".join(others) if others else "All fields"
        else:
            label = ", ".join(names)
        lines.append(f"- {label}: {note}")
    return lines


# Build the Markdown text, grouped by class.
def build_markdown(rows, db_name, measured_on, n_loans, n_monthly):
    lines = [
        "# Feature catalogue: Module 1",
        "",
        "Approved field register for the mortgage data. Later modules use only fields marked",
        f"usable, with the lag rule shown. Built by 04_feature_catalogue.py from {db_name}",
        f"on {date.today().isoformat()}. Fill rates measured on {measured_on}: "
        f"{n_loans:,} loans and {n_monthly:,} monthly rows.",
        "",
        "| Class | Usable | Lag rule | Meaning |",
        "|---|---|---|---|",
    ]
    for field_class in CLASS_ORDER:
        usable, lag, meaning = CLASS_TEXT[field_class]
        lines.append(f"| {field_class} | {usable} | {lag} | {meaning} |")
    for field_class in CLASS_ORDER:
        class_rows = [r for r in rows if r[2] == field_class]
        lines += ["", "## " + SECTION_TITLE[field_class].format(n=len(class_rows)), "",
                  "| Field | Table | Type | Filled | Restated | Description |",
                  "|---|---|---|---|---|---|"]
        for r in class_rows:
            filled = "" if r[11] is None else f"{r[11] * 100:.2f}%"
            restated = "" if r[13] is None else f"{r[13]:,}"
            lines.append(f"| {r[0]} | {r[1]} | {r[5]} | {filled} | {restated} | {r[8]} |")
        bullets = treatment_bullets(class_rows)
        if bullets:
            lines += ["", "Data treatment:"] + bullets
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Feature catalogue of the base tables.")
    parser.add_argument("--db", default=None, help="DuckDB file (defaults to sample DB; use --full for production DB)")
    parser.add_argument("--full", action="store_true", help="Measure fill rates on full mortgages.duckdb instead of sample DB")
    parser.add_argument("--md", default=None, help="Markdown export file")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else (FULL_DB if args.full else DEFAULT_DB)
    default_md = config.script_outputs("01_data_foundation", "04_feature_catalogue", full=args.full) / "feature_catalogue.md"
    md_path = Path(args.md) if args.md else default_md
    print(f"Feature catalogue: {db_path.name}")

    # Stop if the database is not there, so a wrong path never creates an empty file.
    if not db_path.exists():
        print(f"FAIL  database not found: {db_path}")
        print("OVERALL: FAIL")
        return 1
    con = duckdb.connect(str(db_path))

    # Stop if step 6 has not been run.
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if "field_leakage_table" not in tables:
        print("FAIL  field_leakage_table not found: run 03_leakage_audit.py first")
        print("OVERALL: FAIL")
        con.close()
        return 1

    # Stop if a field in field_leakage_table is not a column of its source object.
    types = {LOANS: column_types(con, LOANS), MONTHLY: column_types(con, MONTHLY)}
    leakage_rows = read_leakage_rows(con)
    not_in_db = [(r[1], r[0]) for r in leakage_rows if r[0] not in types[r[1]]]
    if not_in_db:
        print("FAIL  field_leakage_table has fields that are not columns (step 6 is out of date)")
        print_names("not in database", not_in_db)
        print("OVERALL: FAIL")
        con.close()
        return 1

    # Fill rates: one aggregate query per source object.
    measured_on = "all loans" if args.full else f"{SAMPLE_RATE_PCT:.4g}% stratified sample"
    fill = {}
    for source in (LOANS, MONTHLY):
        names = [r[0] for r in leakage_rows if r[1] == source]
        fill[source] = measure_fill(con, source, types[source], names)
    n_loans, n_monthly = fill[LOANS][0], fill[MONTHLY][0]

    # Write feature_catalogue_table in one transaction.
    rows = build_rows(leakage_rows, types, fill, measured_on)
    con.execute("BEGIN TRANSACTION")
    con.execute(
        "CREATE OR REPLACE TABLE feature_catalogue_table ("
        "field_name VARCHAR, source_object VARCHAR, field_class VARCHAR, lag_rule VARCHAR, "
        "usable_as_feature BOOLEAN, data_type VARCHAR, layout_position INTEGER, "
        "layout_name VARCHAR, description VARCHAR, rows_checked BIGINT, rows_filled BIGINT, "
        "fill_rate DOUBLE, measured_on VARCHAR, loans_restated BIGINT, treatment_note VARCHAR)"
    )
    con.executemany("INSERT INTO feature_catalogue_table VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    # Check 1: same (source_object, field_name) set as field_leakage_table, no pair twice.
    n_leakage = con.execute("SELECT COUNT(*) FROM field_leakage_table").fetchone()[0]
    n_catalogue = con.execute("SELECT COUNT(*) FROM feature_catalogue_table").fetchone()[0]
    n_distinct = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT source_object, field_name FROM feature_catalogue_table)"
    ).fetchone()[0]
    only_one_side = con.execute(
        "SELECT COUNT(*) FROM ("
        "(SELECT source_object, field_name FROM field_leakage_table EXCEPT "
        " SELECT source_object, field_name FROM feature_catalogue_table) UNION ALL "
        "(SELECT source_object, field_name FROM feature_catalogue_table EXCEPT "
        " SELECT source_object, field_name FROM field_leakage_table))"
    ).fetchone()[0]
    check1 = n_catalogue == n_leakage and n_distinct == n_catalogue and only_one_side == 0

    # Check 2: no quarantined field is usable.
    bad = con.execute(
        "SELECT COUNT(*) FROM feature_catalogue_table WHERE field_class = 'quarantined' "
        "AND (usable_as_feature OR lag_rule <> 'never')"
    ).fetchone()[0]
    check2 = bad == 0
    ok = check1 and check2
    con.execute("COMMIT" if ok else "ROLLBACK")
    con.close()

    # Summary.
    print(f"Fill rates measured on: {measured_on} ({n_loans:,} loans, {n_monthly:,} monthly rows)")
    n_by_source = {s: sum(1 for r in rows if r[1] == s) for s in (LOANS, MONTHLY)}
    print(f"Fields: {len(rows)} (loans_table {n_by_source[LOANS]}, loan_monthly_view {n_by_source[MONTHLY]})")
    for field_class in CLASS_ORDER:
        count = sum(1 for r in rows if r[2] == field_class)
        print(f"  {field_class:<15}{count:>3}  {SUMMARY_TEXT[field_class]}")
    print(f"Usable as features: {sum(1 for r in rows if r[4])}")
    print(f"Fields with a data-treatment note: {sum(1 for r in rows if r[14])}")

    # Export the Markdown only after the commit.
    if ok:
        text = build_markdown(rows, db_path.name, measured_on, n_loans, n_monthly)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(md_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        print(f"Exported: {md_path}")
    print(("PASS" if check1 else "FAIL") + "  every field in field_leakage_table appears exactly once")
    print(("PASS" if check2 else "FAIL") + "  no quarantined field is marked usable")
    print("OVERALL: " + ("PASS" if ok else "FAIL (table not written)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
