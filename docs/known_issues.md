Must fix
The probation query will never cure a modified loan.
As I understand Fannie Mae’s file, the modification flag stays “Y” for the life of the loan once modified. The query only allows a cure when the flag is 0, so every modified loan stays in default forever.
The trigger needs to be the month the flag changes from N to Y. Have it confirm the flag behaviour in the glossary first.
It also starts at reporting_period = 1 although that column is a date, uses = 1 where the rest of the plan uses ‘Y’, and leaves out the foreclosure and short-sale triggers.
It is still labelled “Verified”, though no run is shown.
The investor-loan risk weight table is missing a band. The 60 to 70% LTV band (40%) has been merged into 60 to 80% at 50%. That is seven bands shrunk to six, and the code would overstate weights.
The forced-sale discount is counted twice in the component LGD. SS4/24’s 40% reference already includes it, so applying a 10 to 20% haircut on top double counts.
The balance sheet doesn’t add up. CET1 of 765 at 14% means risk-weighted assets of about 5,460, an average weight of about 55% on the mortgages. Article 124F gives far less for this book. Set CET1 as 14% of the risk-weighted assets that step 25 computes, not as a fixed figure.
Economic data (fixed 2026-11-15, D-025): residential_mortgage/00_data/build_macro_tables.py loads the federal funds rate (FRED FEDFUNDS), unemployment (FRED UNRATE) and the FHFA house price index (HPI Master) into macro_monthly_table, macro_state_hpi_table, macro_monthly_view, macro_economic_mart and macro_sources_table. Fixed after the review: October 2025 unemployment is blank in the source and now stays blank with unemployment_missing = TRUE (it was a copy of September); 1-month and 12-month changes are taken by date, so a change that spans the blank month is blank; all 6 checks can now fail; downloads only when asked, with curl --fail, and the old file is kept; source dates are recorded. Still open: values sit on their own month, before they were published, so the leakage audit must lag them (unemployment about 1 month, house prices about 2 months).
The data size is probably understated about four-fold. Twenty million loans with an average life of about 50 months is about a billion monthly rows, not 250 to 300 million. The 10% sample would be about 100 million rows. Measure one quarter before committing.
Unrun results are still written as fact. Examples are “Empirical finding: cure rates decline steeply”, “confirming zero unexplained discrepancy”, and the data log sample with PASS and its figures. You approved rewording these (15C), but it was not done.
The PD design contradicts SS4/24.
It still calls the capital PD “cycle-neutral”, which 11.41 rules out for mortgages.
The cyclicality formula is not the PRA’s measure. The PRA measures the share of the change in default rate that comes from loans moving between grades.
The 30% is the cap on imputed cyclicality, not a “maximum cyclicality standard”.
Smaller fixes
Citations:
The 90-day rule is Article 178(1)(b), and materiality is 178(2)(d), not SS3/24 3.2 and 3.6.
Arrears probation is 178(5)(a); only restructuring is 178(5A).
“SS4/24 18.17” and “CRE36.87” for the backtest thresholds look invented; confirm them or drop them.
Use SS1/23’s exact principle titles.
IFRS 9:
A loan on probation is still in default, so it is Stage 3, not Stage 2 (line 451).
The 30-days-past-due backstop is a rebuttable presumption, not “mandatory”.
LGD discounting (fixed 2026-11-15, D-025): macro_economic_mart holds two rates per month, to be taken for the month of default. Long-run = federal funds rate + 5% (SS11/13 13.13A: SONIA + 5% for GBP, a comparable rate in the exposure's currency otherwise). Downturn = the higher of 9% and the long-run rate (SS11/13 13.13, 13.13B; PS9/24 3.141 "at least 9%"); the "higher of" is stricter than the PRA's wording. The federal funds rate is a monthly average, not the rate on the day of default. SS4/24 paragraph numbers are still to be read by hand. See docs/departures_from_uk_rules.md.
Rating scale: add a default grade, and say what happens to PDs above 20%.
Build order:
field_map.py must come before build_db.py.
Staging (step 20) needs the point-in-time PD (step 12).
Step 12 should say its macro coefficients are fitted inside that script.