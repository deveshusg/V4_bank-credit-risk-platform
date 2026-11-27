# Module 05 — IFRS 9 ECL

> [!NOTE]
> **Status: Stub.** Scripts are empty placeholders; implementation begins after Module 04 sign-off. This README documents planned operations and the concept behind each script.

Computes IFRS 9 Expected Credit Loss (ECL) across three stages, runs multi-scenario PD term
structures, and produces the allowance waterfall from opening to closing provision.
Consumes `roll_30day_evidence_mart`, `vintage_curves_mart`, `default_outcomes_mart`,
`forbearance_mart`, `redefault_mart`, and `cycle_mart` from Module 02; PD from Module 03; LGD/EAD from Module 04.

---

## Operations (Planned)

### Prerequisites

- Modules 02, 03, and 04 complete.
- Python 3.11+ `.venv` with `scipy`.

### Planned run order

```powershell
.venv\Scripts\python.exe residential_mortgage\05_ifrs9_ecl\scripts\01_staging_sicr.py [--full]
.venv\Scripts\python.exe residential_mortgage\05_ifrs9_ecl\scripts\02_pd_term_structure.py [--full]
.venv\Scripts\python.exe residential_mortgage\05_ifrs9_ecl\scripts\03_lifetime_lgd_ead.py [--full]
.venv\Scripts\python.exe residential_mortgage\05_ifrs9_ecl\scripts\04_scenario_ecl.py [--full]
.venv\Scripts\python.exe residential_mortgage\05_ifrs9_ecl\scripts\05_movement_waterfall.py [--full]
```

### Planned outputs

| Output | Description |
|---|---|
| `staging_mart` | Per-loan stage assignments (1/2/3) and SICR flags at each December snapshot |
| `pd_term_structure_mart` | Conditional PD$(t, t+h)$ for $h = 1\ldots360$ months per grade and segment |
| `lifetime_lgd_ead_mart` | Expected LGD and EAD for each future period |
| `ecl_mart` | 12m ECL (Stage 1), Lifetime ECL (Stage 2/3), scenario-weighted allowance |
| `movement_waterfall_mart` | Opening → stage transfers → new originations → payoffs → closing provision |

---

## Concepts

### `01_staging_sicr.py` — IFRS 9 Stage Assignment

**Purpose:** Classify each loan into Stage 1 (no significant increase in credit risk), Stage 2 (SICR but not in default), or Stage 3 (in default or credit-impaired) at each December snapshot date.

**Mathematical output:** SICR trigger: behavioural score has fallen by more than a calibrated threshold since origination, OR current DPD ≥ 30 days (rebuttable 30-day backstop — see `roll_30day_evidence_mart`). Stage 3: `in_default = TRUE` from `default_status_monthly`.

**Concept:** IFRS 9.5.5 requires ECL to be measured over 12 months (Stage 1) or the full remaining life (Stage 2/3). The SICR assessment must be forward-looking — not just reactive to delinquency. The 30-day backstop is a regulatory presumption: any loan more than 30 days past due is automatically Stage 2 unless there is "reasonable and supportable information" that the increase in credit risk is not significant (using `roll_30day_evidence_mart` as the rebuttable evidence).

---

### `02_pd_term_structure.py` — Forward PD Curve

**Purpose:** Project the conditional PD from each snapshot month forward over the remaining term, by grade, using the Aalen-Johansen default CIF from `vintage_curves_mart` and macro conditioning.

**Mathematical output:** Conditional forward PD: $\text{PD}(t, t+h) = \text{P(default in } (t, t+h] \mid \text{alive at } t)$ derived from the vintage curves re-indexed to current MOB. Scenario-weighted across base, upside, and downside macro paths from `macro_downturn_mart`.

**Concept:** PD term structure is the core IFRS 9 engineering challenge. Stage 1 loans need 12-month conditional PD; Stage 2 loans need lifetime conditional PD for every remaining month. The vintage curves provide the age-based hazard rates; macro conditioning overlays the economic cycle. The three-scenario probability-weighted approach (IFRS 9.B5.5.42) is required because macroeconomic scenarios are not normally distributed.

---

### `03_lifetime_lgd_ead.py` — Lifetime LGD and EAD

**Purpose:** Compute expected collateral value, discounted recovery, and outstanding balance at each future default point for ECL integration.

**Mathematical output:** Forward LGD($t$): collateral indexed by projected HPI forward path with downturn haircut. EAD($t$) = `scheduled_upb_sql` at time $t$. ECL integration:
$$\text{ECL} = \sum_{h=1}^{T} \text{PD}(t, t+h) \times \text{LGD}(t+h) \times \text{EAD}(t+h) \times (1+r_d)^{-h/12}$$

**Concept:** Lifetime ECL must account for the fact that if a loan defaults in year 5, the collateral value will reflect HPI at year 5, not today. This requires projecting both the PD and the collateral value forward simultaneously. IFRS 9 requires discounting at the original effective interest rate (EIR) — here approximated by the loan's note rate (IFRS 9.B5.5.44).

---

### `04_scenario_ecl.py` — Scenario Weighting

**Purpose:** Compute ECL under base, upside, and downside macro scenarios and produce the probability-weighted allowance.

**Mathematical output:** $\text{ECL}_{\text{weighted}} = p_{\text{base}} \cdot \text{ECL}_{\text{base}} + p_{\text{up}} \cdot \text{ECL}_{\text{up}} + p_{\text{down}} \cdot \text{ECL}_{\text{down}}$. Scenario probabilities set in `_settings/regulatory_parameters.py` (pending Module 5 design sign-off).

**Concept:** Non-linearity of credit losses requires scenario averaging rather than a single best estimate. The relationship between macro conditions and default rate is convex — a 2× worse recession produces more than 2× the defaults. IFRS 9 §B5.5.42 explicitly requires this probability-weighted approach.

---

### `05_movement_waterfall.py` — Allowance Waterfall

**Purpose:** Reconcile the opening ECL allowance to the closing allowance through explicit accounting movements.

**Mathematical output:** Waterfall: `opening_allowance + new_originations_ecl + stage_2_transfers_in − stage_1_transfers_in − payoffs_ecl − write_offs + credit_quality_deterioration ± model_methodology_changes = closing_allowance`.

**Concept:** The waterfall is the CFO's view of ECL — it explains why the provision changed. Auditors and regulators require this reconciliation to verify that changes in ECL are driven by genuine portfolio changes (new originations, macro deterioration), not by model changes disguised as credit quality movements. The movements map directly to IFRS 7 disclosure requirements.
