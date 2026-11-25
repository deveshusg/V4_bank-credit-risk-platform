"""Leakage audit: classify every column of loans_table and loan_monthly_view.

Each field gets a class (origination, monthly_lag_1, quarantined, key). The class sets
the lag rule and whether a model may use the field as a feature. The result is saved
as field_leakage_table, which the feature catalogue (step 7) reads.

Run: python residential_mortgage\\01_data_foundation\\scripts\\03_leakage_audit.py [--db PATH] [--full]
"""

import argparse
import sys
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
from field_map import FIELDS  # noqa: E402

DEFAULT_DB = config.base_db_path(full=False)
FULL_DB = config.base_db_path(full=True)

LOANS = "loans_table"
MONTHLY = "loan_monthly_view"

# Lag rule and feature permission for each class.
CLASS_RULES = {
    "origination": ("none", True),
    "monthly_lag_1": ("t-1", True),
    "quarantined": ("never", False),
    "key": ("join only", False),
}

# The classification: (source_object, field_name, field_class, reason), grouped by class.
CLASSIFICATION = [
    # --- key (5) ---
    (LOANS, "loan_id", "key", "Loan identifier. Joins the tables; not a feature."),
    (LOANS, "acquisition_quarter", "key", "Quarter Fannie Mae acquired the loan. Groups loans by vintage; not a feature."),
    (MONTHLY, "loan_id", "key", "Loan identifier. Joins the tables; not a feature."),
    (MONTHLY, "reporting_period", "key", "Month of the record. Orders time; every lag is counted from it."),
    (MONTHLY, "acquisition_quarter", "key", "Quarter Fannie Mae acquired the loan, taken from the file name. Groups loans by vintage; not a feature."),
    # --- origination (33) ---
    (LOANS, "channel", "origination", "How the loan was sold to Fannie Mae (retail, broker, correspondent). Fixed at origination."),
    (LOANS, "seller_name", "origination", "Lender that sold the loan. Taken from the loan's first month."),
    (LOANS, "note_rate", "origination", "Interest rate on the note at origination."),
    (LOANS, "orig_upb", "origination", "Loan amount at origination."),
    (LOANS, "loan_term", "origination", "Term in months at origination."),
    (LOANS, "orig_date", "origination", "Date the loan was made."),
    (LOANS, "first_payment_date", "origination", "First scheduled payment date, set at origination."),
    (LOANS, "orig_ltv", "origination", "Loan to value at origination."),
    (LOANS, "orig_cltv", "origination", "Combined loan to value at origination."),
    (LOANS, "num_borrowers", "origination", "Number of borrowers at origination."),
    (LOANS, "dti", "origination", "Debt to income at origination."),
    (LOANS, "credit_score", "origination", "Borrower credit score at origination."),
    (LOANS, "co_borrower_credit_score", "origination", "Co-borrower credit score at origination."),
    (LOANS, "first_time_buyer", "origination", "First-time home buyer at origination."),
    (LOANS, "loan_purpose", "origination", "Purchase, refinance or cash-out refinance."),
    (LOANS, "property_type", "origination", "Property type at origination."),
    (LOANS, "num_units", "origination", "Number of units at origination."),
    (LOANS, "occupancy", "origination", "Owner occupied, second home or investor at origination."),
    (LOANS, "property_state", "origination", "State of the property."),
    (LOANS, "msa", "origination", "Metropolitan area of the property. Taken from the loan's first month."),
    (LOANS, "zip3", "origination", "First three digits of the property zip code."),
    (LOANS, "mi_pct", "origination", "Mortgage insurance cover at origination."),
    (LOANS, "amortization_type", "origination", "Fixed or adjustable rate."),
    (LOANS, "prepay_penalty", "origination", "Prepayment penalty in the loan terms."),
    (LOANS, "interest_only", "origination", "Interest-only loan terms."),
    (LOANS, "io_first_pi_date", "origination", "First full payment date of an interest-only loan, set in the loan terms."),
    (LOANS, "mi_type", "origination", "Who pays the mortgage insurance, set at origination."),
    (LOANS, "special_eligibility_program", "origination", "Special lending program at origination."),
    (LOANS, "relocation_mortgage", "origination", "Relocation loan, set at origination."),
    (LOANS, "property_valuation_method", "origination", "How the property was valued at origination."),
    (LOANS, "high_balance_loan", "origination", "High-balance loan at origination."),
    (LOANS, "hltv_refi_option", "origination", "High loan-to-value refinance program at origination."),
    (LOANS, "orig_classic_fico", "origination", "Lowest borrower credit score at origination."),
    # --- monthly_lag_1 (21) ---
    (MONTHLY, "servicer_name", "monthly_lag_1", "Servicer at the reporting date. A change of servicer can follow arrears, so use month t-1."),
    (MONTHLY, "current_rate", "monthly_lag_1", "Interest rate at the reporting date. Changes on modification."),
    (MONTHLY, "current_upb", "monthly_lag_1", "Balance at the reporting date. Set to zero in the exit month and masked in the first six months, so use month t-1."),
    (MONTHLY, "loan_age", "monthly_lag_1", "Months since origination at the reporting date."),
    (MONTHLY, "months_to_legal_maturity", "monthly_lag_1", "Months left to legal maturity at the reporting date."),
    (MONTHLY, "months_to_maturity", "monthly_lag_1", "Months left to maturity at the reporting date, after prepayments."),
    (MONTHLY, "maturity_date", "monthly_lag_1", "Maturity date at the reporting date. Changes on modification."),
    (MONTHLY, "months_to_amortization", "monthly_lag_1", "Months left before an interest-only loan starts to repay principal."),
    (MONTHLY, "delinquency_status", "monthly_lag_1", "Months in arrears at the reporting date. The month t value is the default target, so models use month t-1."),
    (MONTHLY, "payment_history", "monthly_lag_1", "24-month payment record up to the reporting date. Blank once the loan leaves the pool, so use month t-1."),
    (MONTHLY, "modification_flag", "monthly_lag_1", "Loan modified at or before the reporting date."),
    (MONTHLY, "total_principal", "monthly_lag_1", "Principal paid in the month. In the month a loan pays off it equals the whole balance, so use month t-1."),
    (MONTHLY, "mod_non_interest_upb", "monthly_lag_1", "Part of the balance that bears no interest after a modification."),
    (MONTHLY, "servicer_activity", "monthly_lag_1", "Change in servicing activity in the month."),
    (MONTHLY, "borrower_assistance_plan", "monthly_lag_1", "Forbearance, repayment or trial plan at the reporting date."),
    (MONTHLY, "alt_delinquency_resolution", "monthly_lag_1", "Payment deferral or other arrears resolution at the reporting date."),
    (MONTHLY, "alt_delinquency_resolution_count", "monthly_lag_1", "Number of payment deferrals up to the reporting date."),
    (MONTHLY, "total_deferral_amount", "monthly_lag_1", "Balance deferred up to the reporting date."),
    (MONTHLY, "payment_deferral_mod_event", "monthly_lag_1", "Payment deferral treated as a modification in the month."),
    (MONTHLY, "delinquency_months", "monthly_lag_1", "Months in arrears as a whole number, built from delinquency_status. Same lag."),
    (MONTHLY, "is_dpd_unknown", "monthly_lag_1", "Arrears status not known that month (XX), built from delinquency_status. Same lag."),
    # --- quarantined (19) ---
    (MONTHLY, "zero_balance_code", "quarantined", "Why the loan left the pool. Outcome; filled only in the exit month."),
    (MONTHLY, "exit_reason", "quarantined", "Label of zero_balance_code. Outcome."),
    (MONTHLY, "zero_balance_date", "quarantined", "Date the loan left the pool. Outcome."),
    (MONTHLY, "upb_at_removal", "quarantined", "Balance when the loan left the pool. Outcome."),
    (MONTHLY, "last_paid_date", "quarantined", "Last paid instalment date. Filled only for loans that exit with code 02, 03, 09 or 15 (Fannie Mae FAQ Q55; 0 live rows in the test data). Outcome."),
    (MONTHLY, "foreclosure_date", "quarantined", "Date of foreclosure. Outcome."),
    (MONTHLY, "disposition_date", "quarantined", "Date the property was sold or the loan settled. Outcome."),
    (MONTHLY, "foreclosure_costs", "quarantined", "Cost of foreclosure. Loss."),
    (MONTHLY, "preservation_repair_costs", "quarantined", "Cost of keeping and repairing the property. Loss."),
    (MONTHLY, "asset_recovery_costs", "quarantined", "Cost of recovering the property. Loss."),
    (MONTHLY, "misc_holding_expenses", "quarantined", "Other holding costs and credits. Loss."),
    (MONTHLY, "holding_taxes", "quarantined", "Taxes paid while holding the property. Loss."),
    (MONTHLY, "net_sales_proceeds", "quarantined", "Cash from selling the property. Recovery."),
    (MONTHLY, "credit_enhancement_proceeds", "quarantined", "Cash from mortgage insurance and other cover. Recovery."),
    (MONTHLY, "repurchase_make_whole_proceeds", "quarantined", "Cash from the lender buying the loan back. Recovery."),
    (MONTHLY, "other_foreclosure_proceeds", "quarantined", "Other cash from foreclosure. Recovery."),
    (MONTHLY, "principal_forgiveness", "quarantined", "Principal forgiven, usually with a modification. Loss to the lender; never non-zero in the test data."),
    (MONTHLY, "foreclosure_writeoff", "quarantined", "Principal written off as uncollectable after foreclosure. Loss; 572 non-zero values sit on rows without an exit code (2005Q1)."),
    (MONTHLY, "repurchase_make_whole_flag", "quarantined", "Lender bought the loan back. Outcome."),
]


# Read the column names of one table or view from the database.
def database_pairs(con, source_object):
    rows = con.execute(f"DESCRIBE {source_object}").fetchall()
    return [(source_object, row[0]) for row in rows]


# Layout position and layout name for each column the layout knows.
def layout_lookup():
    return {f.column: (f.position, f.layout_name) for f in FIELDS}


# Loans restated per column, summed over all quarters.
def restated_counts(con):
    rows = con.execute(
        "SELECT column_name, SUM(loans_restated) FROM origination_restatements_table "
        "GROUP BY column_name"
    ).fetchall()
    return {name: int(n) for name, n in rows}


# Check 1 data: pairs not classified, listed twice, or missing from the database.
def compare_to_database(listed, in_database):
    seen, duplicated = set(), []
    for pair in listed:
        if pair in seen and pair not in duplicated:
            duplicated.append(pair)
        seen.add(pair)
    unclassified = [p for p in in_database if p not in seen]
    missing = [p for p in sorted(seen) if p not in set(in_database)]
    return unclassified, duplicated, missing


# Build the output rows in the column order of field_leakage_table.
def build_rows(restated):
    layout = layout_lookup()
    rows = []
    for source, name, field_class, reason in CLASSIFICATION:
        lag_rule, usable = CLASS_RULES[field_class]
        position, layout_name = layout.get(name, (None, None))
        if source == LOANS and field_class != "key":
            loans_restated = restated.get(name, 0)
        else:
            loans_restated = None
        rows.append((name, source, position, layout_name, field_class,
                     lag_rule, usable, loans_restated, reason))
    return rows


# Print up to 5 names for one failed group.
def print_names(label, pairs):
    names = ", ".join(f"{s}.{n}" for s, n in pairs[:5])
    print(f"      {label}: {len(pairs)} ({names})")


def main():
    parser = argparse.ArgumentParser(description="Leakage audit of the base tables.")
    parser.add_argument("--db", default=None, help="DuckDB file (defaults to sample DB; use --full for production DB)")
    parser.add_argument("--full", action="store_true", help="Run against full mortgages.duckdb instead of sample DB")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else (FULL_DB if args.full else DEFAULT_DB)
    print(f"Leakage audit: {db_path.name}")

    # Stop if the database is not there, so a wrong path never creates an empty file.
    if not db_path.exists():
        print(f"FAIL  database not found: {db_path}")
        return 1
    con = duckdb.connect(str(db_path))
    in_database = database_pairs(con, LOANS) + database_pairs(con, MONTHLY)
    listed = [(s, n) for s, n, _, _ in CLASSIFICATION]
    restated = restated_counts(con)

    # Check 1: every column classified exactly once. Stop before writing if it fails.
    unclassified, duplicated, missing = compare_to_database(listed, in_database)
    check1 = not (unclassified or duplicated or missing)
    if not check1:
        print("FAIL  every column classified exactly once (table not written)")
        print_names("unclassified", unclassified)
        print_names("duplicated", duplicated)
        print_names("missing from database", missing)
        print("OVERALL: FAIL")
        con.close()
        return 1

    # Write field_leakage_table in one transaction.
    rows = build_rows(restated)
    con.execute("BEGIN TRANSACTION")
    con.execute(
        "CREATE OR REPLACE TABLE field_leakage_table ("
        "field_name VARCHAR, source_object VARCHAR, layout_position INTEGER, "
        "layout_name VARCHAR, field_class VARCHAR, lag_rule VARCHAR, "
        "usable_as_feature BOOLEAN, loans_restated BIGINT, reason VARCHAR)"
    )
    con.executemany("INSERT INTO field_leakage_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    # Check 2: no quarantined field is usable.
    bad = con.execute(
        "SELECT COUNT(*) FROM field_leakage_table WHERE field_class = 'quarantined' "
        "AND (usable_as_feature OR lag_rule <> 'never')"
    ).fetchone()[0]
    check2 = bad == 0
    # Keep the table only if check 2 passes.
    con.execute("COMMIT" if check2 else "ROLLBACK")

    # Summary.
    total = len(rows)
    n_loans = sum(1 for r in rows if r[1] == LOANS)
    n_monthly = sum(1 for r in rows if r[1] == MONTHLY)
    print(f"Fields classified: {total} (loans_table {n_loans}, loan_monthly_view {n_monthly})")
    for field_class in CLASS_RULES:
        print(f"  {field_class:<15}{sum(1 for r in rows if r[4] == field_class)}")
    # Restatements only matter for fields that keep the latest value (D-017).
    first_month = {f.column for f in FIELDS if f.target == "loans_first"}
    counts = [r[7] for r in rows if r[7] and r[0] not in first_month]
    print(f"Restated origination values: {sum(counts):,} loan-field changes over {len(counts)} "
          "fields (latest value kept, D-017)")
    print(("PASS" if check1 else "FAIL") + "  every column classified exactly once")
    print(("PASS" if check2 else "FAIL") + "  no quarantined field is usable"
          + ("" if check2 else " (table not written)"))
    ok = check1 and check2
    print("OVERALL: " + ("PASS" if ok else "FAIL"))
    con.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
