# Module 04 — LGD & EAD Estimation

> [!NOTE]
> **Status: Stub.** Scripts are empty placeholders; implementation begins after Module 03 sign-off. This README documents planned operations and the concept behind each script.

Estimates Loss Given Default (LGD) and Exposure at Default (EAD) from observed workout outcomes.
Consumes `default_outcomes_mart`, `loss_development_mart`, `recovery_summary_mart`,
`workout_exit_cashflows_mart`, and `state_hpi_peaktotrough_mart` from Module 02.

---

## Operations (Planned)

### Prerequisites

- Module 02 complete with `default_outcomes_mart` and `workout_exit_cashflows_mart` populated.
- Module 03 complete with `master_rating_scale_mart` (for grade-level LGD segmentation).
- Python 3.11+ `.venv` with `scipy`, `scikit-learn`.

### Planned run order

```powershell
.venv\Scripts\python.exe residential_mortgage\04_lgd_ead\scripts\01_workout_lgd.py [--full]
.venv\Scripts\python.exe residential_mortgage\04_lgd_ead\scripts\02_component_lgd.py [--full]
.venv\Scripts\python.exe residential_mortgage\04_lgd_ead\scripts\03_expected_loss.py [--full]
```

### Planned outputs

| Output | Description |
|---|---|
| `workout_lgd_mart` | Realised LGD per default event (discounted, with tail factor) |
| `component_lgd_mart` | Cure rate × Cure LGD + (1 − cure rate) × Workout LGD per segment |
| `expected_loss_mart` | EL = PD × LGD × EAD per loan and grade |

---

## Concepts

### `01_workout_lgd.py` — Realised LGD

**Purpose:** Compute observed (realised) LGD for every resolved default episode using discounted cash flows from `workout_exit_cashflows_mart`.

**Mathematical output:**
$$\text{LGD}_i = 1 - \frac{\sum_{t=1}^{T} \text{CF}_{i,t} / (1 + r_d)^{t/12}}{\text{EAD}_i}$$
where $r_d$ is the LGD discount rate from `macro_economic_mart` (FEDFUNDS + 500 bps, floored at max(9%, long-run rate), per D-025), $T$ = workout duration in months, $\text{EAD}_i$ = `balance_at_default`.

Tail factor for incomplete workouts: estimated via chain-ladder on `loss_development_mart` development triangle.

**Concept:** Workout LGD is the IRB-required method for mortgage LGD estimation (PRA SS4/24 §6). The PRA requires discounting at an opportunity cost rate (not risk-free) to reflect the economic cost of capital tied up during workout. The 25% minimum downturn HPI decline (`LGD_HOUSE_PRICE_FALL_MIN_PCT`) and 40% reference downturn (`LGD_HOUSE_PRICE_FALL_REF_PCT`) from `state_hpi_peaktotrough_mart` apply as floors on the collateral haircut in the downturn LGD calculation.

---

### `02_component_lgd.py` — Segment-Level and Downturn LGD

**Purpose:** Decompose LGD into cure and workout components per LTV band and occupancy segment, and apply the regulatory downturn floor.

**Mathematical output:**
$$\text{LGD}_{\text{seg}} = p_{\text{cure}} \times \text{LGD}_{\text{cure}} + (1 - p_{\text{cure}}) \times \text{LGD}_{\text{workout}}$$
Downturn LGD: collateral values re-indexed using the 25–40% stressed HPI decline from `state_hpi_peaktotrough_mart`. Resulting LGD must be ≥ long-run average LGD (Art. 181(1)(b)).

**Concept:** LGD varies strongly by LTV — a loan with 50% LTV at default has ample collateral cushion; a loan with 120% LTV (negative equity) will produce near-100% loss. The cure component (loans that cure before property liquidation) has near-zero LGD. PRA requires the LGD estimate to reflect the worst observed HPI downturn, not just the average — this is what causes UK LGD estimates to be materially higher than US counterparts.

---

### `03_expected_loss.py` — EL Validation

**Purpose:** Compute EL = PD × LGD × EAD at loan and grade level, then back-test against historical observed net losses from `default_outcomes_mart`.

**Mathematical output:** Per-loan and per-grade EL. Back-test: if $|\text{EL}_{\text{model}} - \text{observed\_loss\_rate}| > 20\%$ for any grade, flag as a calibration issue requiring MoC adjustment.

**Concept:** EL is both a capital floor (Pillar 1 expected loss must be covered by provisions or specific capital) and a sanity check: if the model's PD × LGD prediction is systematically lower than observed losses, the model is underpowered and will under-provision. This comparison is a core IRB model validation test.
