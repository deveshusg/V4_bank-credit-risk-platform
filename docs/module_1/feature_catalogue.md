# Feature catalogue: Module 1

Approved field register for the mortgage data. Later modules use only fields marked
usable, with the lag rule shown. Built by 04_feature_catalogue.py from mortgages.duckdb
on 2026-11-15. Fill rates measured on all loans: 57,597,528 loans and 3,314,483,004 monthly rows.

| Class | Usable | Lag rule | Meaning |
|---|---|---|---|
| origination | yes | none | Known when the loan is made. Usable in every month. |
| monthly_lag_1 | yes | t-1 | Known at the reporting date. A model predicting month t uses month t-1 or earlier, and so does any summary built from it. |
| quarantined | no | never | Outcome, exit or loss information. Used only to build targets. |
| key | no | join only | Identifies the loan, the month or the quarter. Used to join and order time. |

## Origination fields (33, usable, lag none)

| Field | Table | Type | Filled | Restated | Description |
|---|---|---|---|---|---|
| channel | loans_table | VARCHAR | 100.00% | 32,412 | How the loan was sold to Fannie Mae (retail, broker, correspondent). Fixed at origination. |
| seller_name | loans_table | VARCHAR | 100.00% | 5,637,956 | Lender that sold the loan. Taken from the loan's first month. |
| note_rate | loans_table | DECIMAL(6,3) | 100.00% | 245 | Interest rate on the note at origination. |
| orig_upb | loans_table | DECIMAL(12,2) | 100.00% | 389 | Loan amount at origination. |
| loan_term | loans_table | INTEGER | 100.00% | 77 | Term in months at origination. |
| orig_date | loans_table | DATE | 100.00% | 15,204 | Date the loan was made. |
| first_payment_date | loans_table | DATE | 100.00% | 3,015 | First scheduled payment date, set at origination. |
| orig_ltv | loans_table | INTEGER | 100.00% | 30,670 | Loan to value at origination. |
| orig_cltv | loans_table | INTEGER | 99.47% | 3,024 | Combined loan to value at origination. |
| num_borrowers | loans_table | INTEGER | 99.98% | 399 | Number of borrowers at origination. |
| dti | loans_table | INTEGER | 98.67% | 143 | Debt to income at origination. |
| credit_score | loans_table | INTEGER | 99.70% | 3,249 | Borrower credit score at origination. |
| co_borrower_credit_score | loans_table | INTEGER | 48.67% | 642 | Co-borrower credit score at origination. |
| first_time_buyer | loans_table | VARCHAR | 99.97% | 2,543 | First-time home buyer at origination. |
| loan_purpose | loans_table | VARCHAR | 100.00% | 1,072 | Purchase, refinance or cash-out refinance. |
| property_type | loans_table | VARCHAR | 100.00% | 198 | Property type at origination. |
| num_units | loans_table | INTEGER | 100.00% | 122 | Number of units at origination. |
| occupancy | loans_table | VARCHAR | 100.00% | 695 | Owner occupied, second home or investor at origination. |
| property_state | loans_table | VARCHAR | 100.00% | 469 | State of the property. |
| msa | loans_table | VARCHAR | 100.00% | 5,577,703 | Metropolitan area of the property. Taken from the loan's first month. |
| zip3 | loans_table | VARCHAR | 100.00% | 14,276 | First three digits of the property zip code. |
| mi_pct | loans_table | DECIMAL(6,2) | 20.79% | 31,412 | Mortgage insurance cover at origination. |
| amortization_type | loans_table | VARCHAR | 100.00% | 1 | Fixed or adjustable rate. |
| prepay_penalty | loans_table | VARCHAR | 100.00% | 0 | Prepayment penalty in the loan terms. |
| interest_only | loans_table | VARCHAR | 78.15% | 0 | Interest-only loan terms. |
| io_first_pi_date | loans_table | DATE | 0.00% | 0 | First full payment date of an interest-only loan, set in the loan terms. |
| mi_type | loans_table | VARCHAR | 20.79% | 5,204 | Who pays the mortgage insurance, set at origination. |
| special_eligibility_program | loans_table | VARCHAR | 100.00% | 637 | Special lending program at origination. |
| relocation_mortgage | loans_table | VARCHAR | 100.00% | 171 | Relocation loan, set at origination. |
| property_valuation_method | loans_table | VARCHAR | 35.62% | 197 | How the property was valued at origination. |
| high_balance_loan | loans_table | VARCHAR | 100.00% | 2,029 | High-balance loan at origination. |
| hltv_refi_option | loans_table | VARCHAR | 100.00% | 0 | High loan-to-value refinance program at origination. |
| orig_classic_fico | loans_table | INTEGER | 26.96% | 0 | Lowest borrower credit score at origination. |

Data treatment:
- All fields except seller_name, msa: Latest non-blank value over the loan's life: Fannie Mae's corrected value (D-017). A lender would not have had a corrected value on day one; see loans restated.
- seller_name, msa: Value from the loan's first month (D-017). Later months can show the buyer after a merger (seller) or new area boundaries (MSA).

## Monthly fields, use month t-1 (21, usable)

| Field | Table | Type | Filled | Restated | Description |
|---|---|---|---|---|---|
| servicer_name | loan_monthly_view | VARCHAR | 97.76% |  | Servicer at the reporting date. A change of servicer can follow arrears, so use month t-1. |
| current_rate | loan_monthly_view | DECIMAL(6,3) | 98.73% |  | Interest rate at the reporting date. Changes on modification. |
| current_upb | loan_monthly_view | DECIMAL(12,2) | 100.00% |  | Balance at the reporting date. Set to zero in the exit month and masked in the first six months, so use month t-1. |
| loan_age | loan_monthly_view | INTEGER | 98.73% |  | Months since origination at the reporting date. |
| months_to_legal_maturity | loan_monthly_view | INTEGER | 98.72% |  | Months left to legal maturity at the reporting date. |
| months_to_maturity | loan_monthly_view | INTEGER | 97.25% |  | Months left to maturity at the reporting date, after prepayments. |
| maturity_date | loan_monthly_view | DATE | 98.72% |  | Maturity date at the reporting date. Changes on modification. |
| months_to_amortization | loan_monthly_view | INTEGER | 0.00% |  | Months left before an interest-only loan starts to repay principal. |
| delinquency_status | loan_monthly_view | VARCHAR | 100.00% |  | Months in arrears at the reporting date. The month t value is the default target, so models use month t-1. |
| payment_history | loan_monthly_view | VARCHAR | 31.90% |  | 24-month payment record up to the reporting date. Blank once the loan leaves the pool, so use month t-1. |
| modification_flag | loan_monthly_view | VARCHAR | 98.73% |  | Loan modified at or before the reporting date. |
| total_principal | loan_monthly_view | DECIMAL(12,2) | 31.44% |  | Principal paid in the month. In the month a loan pays off it equals the whole balance, so use month t-1. |
| mod_non_interest_upb | loan_monthly_view | DECIMAL(12,2) | 1.44% |  | Part of the balance that bears no interest after a modification. |
| servicer_activity | loan_monthly_view | VARCHAR | 98.73% |  | Change in servicing activity in the month. |
| borrower_assistance_plan | loan_monthly_view | VARCHAR | 32.26% |  | Forbearance, repayment or trial plan at the reporting date. |
| alt_delinquency_resolution | loan_monthly_view | VARCHAR | 32.26% |  | Payment deferral or other arrears resolution at the reporting date. |
| alt_delinquency_resolution_count | loan_monthly_view | INTEGER | 0.58% |  | Number of payment deferrals up to the reporting date. |
| total_deferral_amount | loan_monthly_view | DECIMAL(12,2) | 0.56% |  | Balance deferred up to the reporting date. |
| payment_deferral_mod_event | loan_monthly_view | VARCHAR | 100.00% |  | Payment deferral treated as a modification in the month. |
| delinquency_months | loan_monthly_view | INTEGER | 99.08% |  | Months in arrears as a whole number, built from delinquency_status. Same lag. |
| is_dpd_unknown | loan_monthly_view | BOOLEAN | 100.00% |  | Arrears status not known that month (XX), built from delinquency_status. Same lag. |

Data treatment:
- current_upb: Stored as given. Filling the masked early months is left to the module that first needs it.
- delinquency_status: Months in arrears as text. XX means the status was not known that month; 99 means 99 months or more. Kept as given.
- modification_flag: Y, N or blank. It can go from Y back to N, so "ever modified" must be built from all months up to t-1, not from the latest month.
- delinquency_months: delinquency_status as a whole number. XX and blank become NULL, so a NULL here is not "up to date".
- is_dpd_unknown: TRUE where delinquency_status is XX, FALSE otherwise. Use it with delinquency_months to tell "not known" from "blank".

## Quarantined fields (19, not usable)

| Field | Table | Type | Filled | Restated | Description |
|---|---|---|---|---|---|
| zero_balance_code | loan_monthly_view | VARCHAR | 1.27% |  | Why the loan left the pool. Outcome; filled only in the exit month. |
| zero_balance_date | loan_monthly_view | DATE | 1.27% |  | Date the loan left the pool. Outcome. |
| upb_at_removal | loan_monthly_view | DECIMAL(12,2) | 1.27% |  | Balance when the loan left the pool. Outcome. |
| last_paid_date | loan_monthly_view | DATE | 0.02% |  | Last paid instalment date. Filled only for loans that exit with code 02, 03, 09 or 15 (Fannie Mae FAQ Q55; 0 live rows in the test data). Outcome. |
| foreclosure_date | loan_monthly_view | DATE | 0.02% |  | Date of foreclosure. Outcome. |
| disposition_date | loan_monthly_view | DATE | 0.02% |  | Date the property was sold or the loan settled. Outcome. |
| foreclosure_costs | loan_monthly_view | DECIMAL(12,2) | 0.02% |  | Cost of foreclosure. Loss. |
| preservation_repair_costs | loan_monthly_view | DECIMAL(12,2) | 0.02% |  | Cost of keeping and repairing the property. Loss. |
| asset_recovery_costs | loan_monthly_view | DECIMAL(12,2) | 0.02% |  | Cost of recovering the property. Loss. |
| misc_holding_expenses | loan_monthly_view | DECIMAL(12,2) | 0.02% |  | Other holding costs and credits. Loss. |
| holding_taxes | loan_monthly_view | DECIMAL(12,2) | 0.02% |  | Taxes paid while holding the property. Loss. |
| net_sales_proceeds | loan_monthly_view | DECIMAL(12,2) | 0.02% |  | Cash from selling the property. Recovery. |
| credit_enhancement_proceeds | loan_monthly_view | DECIMAL(12,2) | 0.01% |  | Cash from mortgage insurance and other cover. Recovery. |
| repurchase_make_whole_proceeds | loan_monthly_view | DECIMAL(12,2) | 0.01% |  | Cash from the lender buying the loan back. Recovery. |
| other_foreclosure_proceeds | loan_monthly_view | DECIMAL(12,2) | 0.02% |  | Other cash from foreclosure. Recovery. |
| principal_forgiveness | loan_monthly_view | DECIMAL(12,2) | 0.96% |  | Principal forgiven, usually with a modification. Loss to the lender; never non-zero in the test data. |
| foreclosure_writeoff | loan_monthly_view | DECIMAL(12,2) | 0.96% |  | Principal written off as uncollectable after foreclosure. Loss; 572 non-zero values sit on rows without an exit code (2005Q1). |
| repurchase_make_whole_flag | loan_monthly_view | VARCHAR | 1.27% |  | Lender bought the loan back. Outcome. |
| exit_reason | loan_monthly_view | VARCHAR | 1.27% |  | Label of zero_balance_code. Outcome. |

Data treatment:
- zero_balance_code: Blank while the loan is active. Codes: 01 prepaid or matured; 02 third-party sale; 03 short sale; 06 repurchased; 09 deed-in-lieu or REO; 15 non-performing note sale; 16 reperforming note sale; 96 removal (non-credit). Any other code fails the load.
- exit_reason: Label of zero_balance_code, from the same 8 codes. NULL while the loan is active.

## Key fields (5, not features)

| Field | Table | Type | Filled | Restated | Description |
|---|---|---|---|---|---|
| loan_id | loans_table | VARCHAR | 100.00% |  | Loan identifier. Joins the tables; not a feature. |
| acquisition_quarter | loans_table | VARCHAR | 100.00% |  | Quarter Fannie Mae acquired the loan. Groups loans by vintage; not a feature. |
| loan_id | loan_monthly_view | VARCHAR | 100.00% |  | Loan identifier. Joins the tables; not a feature. |
| reporting_period | loan_monthly_view | DATE | 100.00% |  | Month of the record. Orders time; every lag is counted from it. |
| acquisition_quarter | loan_monthly_view | VARCHAR | 100.00% |  | Quarter Fannie Mae acquired the loan, taken from the file name. Groups loans by vintage; not a feature. |
