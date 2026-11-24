"""Canonical time windows: the one place every observation/performance window is defined.

The words "observation window" and "performance window" mean different things and were used
loosely across the docs. This file fixes the vocabulary once and gives each window one name,
one direction (before/after the snapshot date t0), one value and one source.

Rules the whole platform follows (05_observation_windows.ipynb draws them):

- t0 is the snapshot date: the month a model freezes its features and scores a loan.
- The OBSERVATION (feature) window looks BACKWARD from t0 and ends at t0-1.
- The PERFORMANCE (outcome) window looks FORWARD from t0 and is where the label is measured.
  Any field filled inside this window that leaks into a feature is target leakage
  (03_leakage_audit.py and 04_feature_catalogue.py carry the per-field rule).

Where the values come from:
- Window and horizon choices: docs/module_2/module-2-plan.md decisions M2-3, M2-5, M2-9,
  M2-13 and the script specs (roll rates, vintage curves, forbearance).
- The regulatory thresholds in DPD_DEFAULT_MONTHS and PROBATION_* live here for now because
  regulatory_parameters.py is still an empty skeleton (values are added there only when the
  module that needs them is signed off). At Module 2 sign-off these three move into
  residential_mortgage/regulatory_parameters.py and this file imports them from there, so the
  regulatory numbers stay in one place.
"""

# ── The snapshot and the two windows it splits ────────────────────────────────────────────
# t0 is the observation point; features end at t0-1, the outcome starts after t0.
FEATURE_LAG_MONTHS = 1            # "use month t-1" rule (feature catalogue, monthly_lag_1)
FEATURE_LOOKBACK_MONTHS = 6       # worst-arrears lookback, module-2-plan stage 7
FEATURE_LOOKBACK_MONTHS_LONG = 12  # worst-12-months / 12-month payment pattern, stage 7
PERFORMANCE_WINDOW_MONTHS = 12    # default within the next 12 months (M2-9)
PERFORMANCE_WINDOW_MONTHS_LONG = 24  # long-horizon outcome (re-default, M2-9/forbearance)

# ── Loan eligibility ───────────────────────────────────────────────────────────────────────
SEASONING_MIN_MOB = 6             # months on book before first observation; masked-balance months
SNAPSHOT_MONTH = 12               # book_snapshot is taken every December (M2-12)
MIN_DATA_YEARS = 5                # retail PD data needs >= 5 years (Article 180(2)(e))

# ── Default and probation (move to regulatory_parameters.py at Module 2 sign-off) ──────────
DPD_DEFAULT_MONTHS = 3            # 3 months behind = 90-119 DPD; M2-3 (Article 178(1)(b))
PROBATION_ARREARS_MONTHS = 3      # clean months after an arrears default; M2-5 (178(5)(a))
PROBATION_RESTRUCTURING_MONTHS = 12  # clean months after distressed restructuring; M2-5 (178(5A))

# ── Forward horizons used for projection and re-default ───────────────────────────────────
PROJECTION_HORIZONS_MONTHS = [6, 12, 24, 36]   # roll-rate projection (stage 3)
RE_DEFAULT_WINDOWS_MONTHS = [12, 24]           # re-default after modification/deferral (stage 9)

# ── Out-of-time split (M2-13): Module 3 may choose another split ──────────────────────────
OUT_OF_TIME_FROM = "2022-12"
OUT_OF_TIME_TO = "2024-12"

# ── Vocabulary table used by 05_observation_windows.ipynb ─────────────────────────────────
# One row per window: name, direction, definition, value in this project, source.
WINDOW_VOCABULARY = [
    {
        "window": "Snapshot date (t0)",
        "direction": "point",
        "definition": "The month a model freezes its features and scores the loan.",
        "value": "Every December 2000-2025 (book_snapshot); monthly for roll rates.",
        "source": "M2-12, M2-13",
    },
    {
        "window": "Observation / feature window",
        "direction": "backward",
        "definition": "Months before t0 whose values become features. Ends at t0-1.",
        "value": f"lookback {FEATURE_LOOKBACK_MONTHS} months (and {FEATURE_LOOKBACK_MONTHS_LONG} for worst-12/payment pattern); lag {FEATURE_LAG_MONTHS} month",
        "source": "feature catalogue; stage 7",
    },
    {
        "window": "Performance / outcome window",
        "direction": "forward",
        "definition": "Months after t0 over which the label is measured. A feature taken from here is leakage.",
        "value": f"{PERFORMANCE_WINDOW_MONTHS} months (default); {PERFORMANCE_WINDOW_MONTHS_LONG} for re-default",
        "source": "M2-9; stage 9",
    },
    {
        "window": "Sample coverage window",
        "direction": "global",
        "definition": "The calendar span of the whole panel, independent of any single loan.",
        "value": "2000Q1-2025Q4 (104 acquisition quarters), data to 2025-12",
        "source": "loaded_quarters_table",
    },
    {
        "window": "Seasoning window",
        "direction": "backward",
        "definition": "Minimum months on book before a loan is eligible for a sample.",
        "value": f"{SEASONING_MIN_MOB} months (masked-balance months)",
        "source": "M2 data facts",
    },
    {
        "window": "Maturity / censoring window",
        "direction": "forward",
        "definition": "How much of the performance window a loan has actually realized before it exits or the data ends.",
        "value": "measured per vintage in 05_observation_windows.ipynb",
        "source": "05_observation_windows.ipynb",
    },
    {
        "window": "Cure / probation window",
        "direction": "forward",
        "definition": "Clean months after default before a loan re-enters performing.",
        "value": f"{PROBATION_ARREARS_MONTHS} months arrears default; {PROBATION_RESTRUCTURING_MONTHS} months restructuring",
        "source": "M2-5 (178(5)(a), 178(5A))",
    },
    {
        "window": "Projection horizon",
        "direction": "forward",
        "definition": "Forward periods for roll-rate / PD projection, holding monthly rates fixed.",
        "value": f"{PROJECTION_HORIZONS_MONTHS} months",
        "source": "stage 3",
    },
    {
        "window": "Emergence lag",
        "direction": "forward",
        "definition": "Time from first missed payment to recognition as default.",
        "value": f"{DPD_DEFAULT_MONTHS} months behind (90-119 DPD)",
        "source": "M2-3 (178(1)(b))",
    },
]
