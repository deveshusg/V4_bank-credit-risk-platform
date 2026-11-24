"""Field map for the Fannie Mae Single-Family Loan Performance files.

Source document: references/fannie_mae_glossary_file_layout.pdf
("Single-Family Loan Performance Dataset and Credit Risk Transfer - Glossary and
File Layout", version 11/9/2026). The layout lists 118 fields. The files in the zip
carry positions 1 to 113 only; positions 114 to 118 (VantageScore 4.0 scores, Pricing
Indicator, Fannie Score) are in the layout but not in these files, so the field list
below has 113 fields, not 118.

For each field this file gives: position, the name used in the layout, the column name
used in our database, the data type, and where the value goes (the target):
  key           in both tables (loan identifier and reporting period)
  loans         one value per loan: the latest non-blank value, which is Fannie Mae's
                corrected value (origination fields are restated during a loan's life)
  loans_first   one value per loan: the earliest non-blank value (seller name, MSA)
  loan_monthly  one value per loan per month
  not_loaded    marked NA for Single-Family data in the layout

Run it directly to check it: python residential_mortgage\\00_data\\field_map.py
"""

import sys
from dataclasses import dataclass


# One row of the layout.
@dataclass(frozen=True)
class Field:
    position: int
    layout_name: str
    column: str
    dtype: str
    target: str


# Rows: (position, layout name, column, dtype, target).
_ROWS = [
    (1, "Reference Pool ID", "reference_pool_id", "text", "not_loaded"),
    (2, "Loan Identifier", "loan_id", "text", "key"),
    (3, "Monthly Reporting Period", "reporting_period", "date", "key"),
    (4, "Channel", "channel", "text", "loans"),
    (5, "Seller Name", "seller_name", "text", "loans_first"),
    (6, "Servicer Name", "servicer_name", "text", "loan_monthly"),
    (7, "Master Servicer", "master_servicer", "text", "not_loaded"),
    (8, "Original Interest Rate", "note_rate", "rate", "loans"),
    (9, "Current Interest Rate", "current_rate", "rate", "loan_monthly"),
    (10, "Original UPB", "orig_upb", "money", "loans"),
    (11, "UPB at Issuance", "upb_at_issuance", "money", "not_loaded"),
    (12, "Current Actual UPB", "current_upb", "money", "loan_monthly"),
    (13, "Original Loan Term", "loan_term", "int", "loans"),
    (14, "Origination Date", "orig_date", "date", "loans"),
    (15, "First Payment Date", "first_payment_date", "date", "loans"),
    (16, "Loan Age", "loan_age", "int", "loan_monthly"),
    (17, "Remaining Months to Legal Maturity", "months_to_legal_maturity", "int", "loan_monthly"),
    (18, "Remaining Months To Maturity", "months_to_maturity", "int", "loan_monthly"),
    (19, "Maturity Date", "maturity_date", "date", "loan_monthly"),
    (20, "Original Loan to Value Ratio (LTV)", "orig_ltv", "int", "loans"),
    (21, "Original Combined Loan to Value Ratio (CLTV)", "orig_cltv", "int", "loans"),
    (22, "Number of Borrowers", "num_borrowers", "int", "loans"),
    (23, "Debt-To-Income (DTI)", "dti", "int", "loans"),
    # The layout says position 24 is not populated from March 2026 and points to position 111,
    # which is defined differently ("lowest representative credit score of all borrowers").
    (24, "Borrower Credit Score at Origination", "credit_score", "int", "loans"),
    (25, "Co-Borrower Credit Score at Origination", "co_borrower_credit_score", "int", "loans"),
    (26, "First Time Home Buyer Indicator", "first_time_buyer", "text", "loans"),
    (27, "Loan Purpose", "loan_purpose", "text", "loans"),
    (28, "Property Type", "property_type", "text", "loans"),
    (29, "Number of Units", "num_units", "int", "loans"),
    (30, "Occupancy Status", "occupancy", "text", "loans"),
    (31, "Property State", "property_state", "text", "loans"),
    (32, "Metropolitan Statistical Area (MSA) or Metropolitan Statistical Division Area (MSDA)", "msa", "text", "loans_first"),
    (33, "Zip Code Short", "zip3", "text", "loans"),
    (34, "Mortgage Insurance Percentage", "mi_pct", "percent", "loans"),
    (35, "Amortization Type", "amortization_type", "text", "loans"),
    (36, "Prepayment Penalty Indicator", "prepay_penalty", "text", "loans"),
    (37, "Interest Only Loan Indicator", "interest_only", "text", "loans"),
    (38, "Interest Only First Principal And Interest Payment Date", "io_first_pi_date", "date", "loans"),
    (39, "Months to Amortization", "months_to_amortization", "int", "loan_monthly"),
    (40, "Current Loan Delinquency Status", "delinquency_status", "text", "loan_monthly"),
    (41, "Loan Payment History", "payment_history", "text", "loan_monthly"),
    (42, "Modification Flag", "modification_flag", "text", "loan_monthly"),
    (43, "Mortgage Insurance Cancellation Indicator", "mi_cancellation", "text", "not_loaded"),
    (44, "Zero Balance Code", "zero_balance_code", "text", "loan_monthly"),
    (45, "Zero Balance Effective Date", "zero_balance_date", "date", "loan_monthly"),
    (46, "UPB at the Time of Removal", "upb_at_removal", "money", "loan_monthly"),
    (47, "Repurchase Date", "repurchase_date", "date", "not_loaded"),
    (48, "Scheduled Principal Current", "scheduled_principal", "money", "not_loaded"),
    (49, "Total Principal Current", "total_principal", "money", "loan_monthly"),
    (50, "Unscheduled Principal Current", "unscheduled_principal", "money", "not_loaded"),
    (51, "Last Paid Installment Date", "last_paid_date", "date", "loan_monthly"),
    (52, "Foreclosure Date", "foreclosure_date", "date", "loan_monthly"),
    (53, "Disposition Date", "disposition_date", "date", "loan_monthly"),
    (54, "Foreclosure Costs", "foreclosure_costs", "money", "loan_monthly"),
    (55, "Property Preservation and Repair Costs", "preservation_repair_costs", "money", "loan_monthly"),
    (56, "Asset Recovery Costs", "asset_recovery_costs", "money", "loan_monthly"),
    (57, "Miscellaneous Holding Expenses and Credits", "misc_holding_expenses", "money", "loan_monthly"),
    (58, "Associated Taxes for Holding Property", "holding_taxes", "money", "loan_monthly"),
    (59, "Net Sales Proceeds", "net_sales_proceeds", "money", "loan_monthly"),
    (60, "Credit Enhancement Proceeds", "credit_enhancement_proceeds", "money", "loan_monthly"),
    (61, "Repurchase Make Whole Proceeds", "repurchase_make_whole_proceeds", "money", "loan_monthly"),
    (62, "Other Foreclosure Proceeds", "other_foreclosure_proceeds", "money", "loan_monthly"),
    (63, "Modification-Related Non-Interest Bearing UPB", "mod_non_interest_upb", "money", "loan_monthly"),
    (64, "Principal Forgiveness Amount", "principal_forgiveness", "money", "loan_monthly"),
    (65, "Original List Start Date", "orig_list_start_date", "date", "not_loaded"),
    (66, "Original List Price", "orig_list_price", "money", "not_loaded"),
    (67, "Current List Start Date", "current_list_start_date", "date", "not_loaded"),
    (68, "Current List Price", "current_list_price", "money", "not_loaded"),
    (69, "Borrower Credit Score At Issuance", "credit_score_at_issuance", "int", "not_loaded"),
    (70, "Co-Borrower Credit Score At Issuance", "co_borrower_credit_score_at_issuance", "int", "not_loaded"),
    (71, "Borrower Credit Score Current", "credit_score_current", "int", "not_loaded"),
    (72, "Co-Borrower Credit Score Current", "co_borrower_credit_score_current", "int", "not_loaded"),
    (73, "Mortgage Insurance Type", "mi_type", "text", "loans"),
    (74, "Servicing Activity Indicator", "servicer_activity", "text", "loan_monthly"),
    (75, "Current Period Modification Loss Amount", "current_mod_loss", "money", "not_loaded"),
    (76, "Cumulative Modification Loss Amount", "cumulative_mod_loss", "money", "not_loaded"),
    (77, "Current Period Credit Event Net Gain or Loss", "current_credit_event_gain_loss", "money", "not_loaded"),
    (78, "Cumulative Credit Event Net Gain or Loss", "cumulative_credit_event_gain_loss", "money", "not_loaded"),
    (79, "Special Eligibility Program", "special_eligibility_program", "text", "loans"),
    (80, "Foreclosure Principal Write-off Amount", "foreclosure_writeoff", "money", "loan_monthly"),
    (81, "Relocation Mortgage Indicator", "relocation_mortgage", "text", "loans"),
    (82, "Zero Balance Code Change Date", "zero_balance_code_change_date", "date", "not_loaded"),
    (83, "Loan Holdback Indicator", "loan_holdback", "text", "not_loaded"),
    (84, "Loan Holdback Effective Date", "loan_holdback_date", "date", "not_loaded"),
    (85, "Delinquent Accrued Interest", "delinquent_accrued_interest", "money", "not_loaded"),
    (86, "Property Valuation Method", "property_valuation_method", "text", "loans"),
    (87, "High Balance Loan Indicator", "high_balance_loan", "text", "loans"),
    (88, "ARM Initial Fixed-Rate Period ≤ 5 YR Indicator", "arm_fixed_5yr_or_less", "text", "not_loaded"),
    (89, "ARM Product Type", "arm_product_type", "text", "not_loaded"),
    (90, "Initial Fixed-Rate Period", "initial_fixed_rate_period", "int", "not_loaded"),
    (91, "Interest Rate Adjustment Frequency", "rate_adjustment_frequency", "int", "not_loaded"),
    (92, "Next Interest Rate Adjustment Date", "next_rate_adjustment_date", "date", "not_loaded"),
    (93, "Next Payment Change Date", "next_payment_change_date", "date", "not_loaded"),
    (94, "Index", "arm_index", "text", "not_loaded"),
    (95, "ARM Cap Structure", "arm_cap_structure", "text", "not_loaded"),
    (96, "Initial Interest Rate Cap Up Percent", "initial_rate_cap_up", "rate4", "not_loaded"),
    (97, "Periodic Interest Rate Cap Up Percent", "periodic_rate_cap_up", "rate4", "not_loaded"),
    (98, "Lifetime Interest Rate Cap Up Percent", "lifetime_rate_cap_up", "rate4", "not_loaded"),
    (99, "Mortgage Margin", "mortgage_margin", "rate4", "not_loaded"),
    (100, "ARM Balloon Indicator", "arm_balloon", "text", "not_loaded"),
    (101, "ARM Plan Number", "arm_plan_number", "int", "not_loaded"),
    (102, "Borrower Assistance Plan", "borrower_assistance_plan", "text", "loan_monthly"),
    (103, "High Loan to Value (HLTV) Refinance Option Indicator", "hltv_refi_option", "text", "loans"),
    (104, "Deal Name", "deal_name", "text", "not_loaded"),
    (105, "Repurchase Make Whole Proceeds Flag", "repurchase_make_whole_flag", "text", "loan_monthly"),
    (106, "Alternative Delinquency Resolution", "alt_delinquency_resolution", "text", "loan_monthly"),
    (107, "Alternative Delinquency Resolution Count", "alt_delinquency_resolution_count", "int", "loan_monthly"),
    (108, "Total Deferral Amount", "total_deferral_amount", "money", "loan_monthly"),
    (109, "Payment Deferral Modification Event Indicator", "payment_deferral_mod_event", "text", "loan_monthly"),
    (110, "Interest Bearing UPB", "interest_bearing_upb", "money", "not_loaded"),
    (111, "Origination Classic FICO®", "orig_classic_fico", "int", "loans"),
    (112, "Issuance Classic FICO®", "issuance_classic_fico", "int", "not_loaded"),
    (113, "Current Classic FICO®", "current_classic_fico", "int", "not_loaded"),
]

# The 113 fields in the files, in position order.
FIELDS = [Field(*row) for row in _ROWS]

FIELDS_IN_FILE = 113

# Fields in the layout but not in these files.
_NOT_IN_FILES_NOTE = "in the layout, not in these files"
NOT_IN_FILES = [
    (114, "Origination VantageScore® 4.0", _NOT_IN_FILES_NOTE),
    (115, "Issuance VantageScore® 4.0", _NOT_IN_FILES_NOTE),
    (116, "Current VantageScore® 4.0", _NOT_IN_FILES_NOTE),
    (117, "Pricing Indicator", _NOT_IN_FILES_NOTE),
    (118, "Fannie Score™", _NOT_IN_FILES_NOTE),
]

# Zero Balance Code to the reason the loan left the pool.
EXIT_REASONS = {
    "01": "prepaid or matured",
    "02": "third-party sale",
    "03": "short sale",
    "06": "repurchased",
    "09": "deed-in-lieu or REO",
    "15": "non-performing note sale",
    "16": "reperforming note sale",
    "96": "removal (non-credit)",
}

MODIFICATION_FLAG_VALUES = ("Y", "N")

# Positions the layout marks NA for Single-Family data.
NOT_FOR_SINGLE_FAMILY = (
    [1, 7, 11, 43, 47, 48, 50]
    + list(range(65, 73))
    + list(range(75, 79))
    + list(range(82, 86))
    + list(range(88, 102))
    + [104, 110, 112, 113]
)

# DuckDB type for each dtype.
SQL_TYPES = {
    "text": "VARCHAR",
    "date": "DATE",
    "int": "INTEGER",
    "money": "DECIMAL(12,2)",
    "rate": "DECIMAL(6,3)",
    "percent": "DECIMAL(6,2)",
    "rate4": "DECIMAL(7,4)",
}

ALLOWED_TARGETS = ["key", "loans", "loans_first", "loan_monthly", "not_loaded"]


# Return the fields that go to one target.
def fields_for(target):
    return [f for f in FIELDS if f.target == target]


# Check 1: 113 rows, positions 1..113 in order.
def check_positions():
    return [f.position for f in FIELDS] == list(range(1, 114)) and len(FIELDS) == FIELDS_IN_FILE


# Check 2: the fields not in the files are 114..118.
def check_not_in_files():
    return [p for p, _, _ in NOT_IN_FILES] == [114, 115, 116, 117, 118]


# Check 3: column names unique, lowercase letters, digits and underscores only.
def check_column_names():
    names = [f.column for f in FIELDS]
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    return len(set(names)) == len(names) and all(n and set(n) <= allowed for n in names)


# Check 4: every dtype is known and every target is allowed.
def check_types_and_targets():
    return all(f.dtype in SQL_TYPES and f.target in ALLOWED_TARGETS for f in FIELDS)


# Check 5: the not_loaded positions are exactly the Single-Family NA positions.
def check_not_loaded():
    not_loaded = sorted(f.position for f in fields_for("not_loaded"))
    return not_loaded == sorted(NOT_FOR_SINGLE_FAMILY)


# Check 6: positions 2 and 3 are the only key fields.
def check_keys():
    return [f.position for f in fields_for("key")] == [2, 3]


# Run the checks, print PASS or FAIL for each, then the count per target.
def main():
    checks = [
        ("113 rows, positions 1 to 113 in order", check_positions),
        ("not-in-files positions are 114 to 118", check_not_in_files),
        ("column names unique and clean", check_column_names),
        ("every dtype and target is allowed", check_types_and_targets),
        ("not_loaded positions equal NOT_FOR_SINGLE_FAMILY", check_not_loaded),
        ("positions 2 and 3 are the only key fields", check_keys),
    ]
    failed = 0
    for text, check in checks:
        ok = check()
        print(("PASS  " if ok else "FAIL  ") + text)
        if not ok:
            failed += 1
    for target in ALLOWED_TARGETS:
        print(f"{target}: {len(fields_for(target))} fields")
    print("OVERALL: " + ("PASS" if failed == 0 else "FAIL"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
