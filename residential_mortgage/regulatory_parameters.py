"""Regulatory parameters: the one place every threshold and rate used by the platform is set.

Populated for Module 2 (2026-11-25, per D-030 and D-031; Modules 3 to 8 remain placeholders
until each module's design is signed off).

Each value carries:
- the source: document, article or paragraph, and the date checked;
- whether it is a UK rule, or a project choice (with the reason).

Where a UK rule meets US Fannie Mae data, the departure is listed in
docs\\departures_from_uk_rules.md. The LGD discount rates (SONIA+5% currency-adapted to
FEDFUNDS+5%, and max(9%, long_run_rate)) are built in 00_data\\build_macro_tables.py (D-025).
"""

# ── Definition of default and portfolio checks (Module 2) ─────────────────────────────────
# PRA Rulebook IRB Part Art. 178(1)(b); checked 2026-11-25 (exact PRA wording pending PDF check).
# UK rule: > 90 days past due. Project choice / data departure #9: 3 whole months behind (90-119 DPD).
DPD_DEFAULT_MONTHS: int = 3

# PRA Rulebook IRB Part Art. 178(2)(d) & SS3/24 2.16; checked 2026-11-25 (secondary UK sources).
# UK rule: retail past-due materiality threshold is £0 and 0%. Departures entry #10: met by any arrears >= 3m.
RETAIL_MATERIALITY_GBP: float = 0.0
RETAIL_MATERIALITY_PCT: float = 0.0

# PRA Rulebook IRB Part Art. 178(5)(a); checked 2026-11-15 & 2026-11-25.
# UK rule: at least 3 months clean before leaving non-restructuring default.
PROBATION_ARREARS_MONTHS: int = 3

# PRA Rulebook IRB Part Art. 178(5A); checked 2026-11-15 & 2026-11-25.
# UK rule: at least 12 months (1 year) clean before leaving distressed-restructuring default.
PROBATION_RESTRUCTURING_MONTHS: int = 12

# Project choice (M2-3, Module 2): US Fannie Mae zero_balance_code values treated as credit default exits.
# Departures entry #12: US foreclosure/sale codes in place of UK possession.
CREDIT_EXIT_CODES: tuple[str, ...] = ("02", "03", "09", "15")

# Empirical codes verified 2026-11-25 on sampled_loans_table (2018Q1-2020Q2, 2018Q1-2020Q1 & 2005Q1-2015Q1):
# '7' = Not Applicable sentinel and 'N' = None; only ('F', 'T', 'R') are active assistance plans.
ACTIVE_RELIEF_PLANS: tuple[str, ...] = ("F", "T", "R")
NO_RELIEF_PLAN_CODES: tuple[str, ...] = ("7", "N")
DEFERRAL_RESOLUTION_CODES: tuple[str, ...] = ("C", "P", "D")

# PRA Dear CEO letters (26 Mar 2020 Annex para 9; 4 Jun 2020 Annex para 33, 38) &
# FCA Payment Deferral Guidance / Tailored Support Guidance (Nov 2020, 1.7, 1.8, 2.3); read in full 2026-11-16.
# UK rule limits overlaid onto longer US CARES Act forbearance (M2-4, Departures entry #13).
COVID_DEFERRAL_ELIGIBLE_START: str = "2020-03-01"
COVID_DEFERRAL_ELIGIBLE_END: str = "2021-03-31"
COVID_DEFERRAL_MAX_END: str = "2021-07-31"
COVID_DEFERRAL_MAX_MONTHS: int = 6

# PRA Rulebook IRB Part Art. 180(2)(e); checked 2026-11-25.
# UK rule: at least 5 years historical observation period for retail PD estimation.
MIN_DATA_YEARS: int = 5

# PRA Rulebook Standardised Approach Part Art. 124D (checked 2026-11-25; wording check pending PDF).
# UK rule: residential property revaluation at least every 5 years (3 years for large exposures),
# and immediate update if market prices fall more than 10%. IRB indexation: CRM Art. 208(3) / SS11/13 13.9.
PROPERTY_REVAL_MAX_YEARS: int = 5
LTV_DOWNWARD_MARKET_DECLINE_PCT: float = 0.10

# Reference benchmarks cited in docs\module_2\module-2-plan.md (scripts 6, 7, 15) for descriptive checks only.
# Pending word-for-word PRA Rulebook / SS4/24 check before Module 4 (LGD) & Module 6 (Capital) sign-off:
LGD_HOUSE_PRICE_FALL_MIN_PCT: float = 0.25   # 25% minimum HPI decline benchmark (check SS4/24 at Module 4)
LGD_HOUSE_PRICE_FALL_REF_PCT: float = 0.40   # 40% stressed HPI decline benchmark (check SS4/24 at Module 4)
IRB_RESIDENTIAL_CORRELATION: float = 0.15    # CRR IRB Part Art. 154(3) retail mortgage correlation benchmark
SA_OWNER_OCCUPIED_LTV_SPLIT: float = 0.55    # SA real-estate split benchmark (check PS9/24 at Module 6)

# Probability of default (Module 3)

# Loss given default (Module 4)

# IFRS 9 staging (Module 5)

# Basel 3.1 capital (Module 6)

# Stress testing (Module 7)
