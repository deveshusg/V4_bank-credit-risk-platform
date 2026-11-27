# Module 07 — Stress Testing

> [!NOTE]
> **Status: Stub.** Implementation begins after Module 06 sign-off. This README documents planned operations and the concept behind each planned script.

Projects mortgage credit losses, ECL provisions, and capital under severe macroeconomic stress scenarios.
Consumes `portfolio_rates_quarterly_mart`, `economy_correlations_mart`, `macro_downturn_mart`,
`cycle_mart`, and `book_snapshot` from Module 02; PD/LGD/EAD from Modules 03–04; capital from Module 06.

---

## Operations (Planned)

### Prerequisites

- Modules 02 through 06 complete.
- Python 3.11+ `.venv` with `scipy`, `numpy`.

### Planned run order

```powershell
# Adverse and severely adverse macro scenario construction
.venv\Scripts\python.exe residential_mortgage\07_stress_testing\scripts\01_scenario_construction.py [--full]

# Loss projection under stress PD/LGD paths
.venv\Scripts\python.exe residential_mortgage\07_stress_testing\scripts\02_loss_projection.py [--full]

# ECL and capital impact under stress
.venv\Scripts\python.exe residential_mortgage\07_stress_testing\scripts\03_capital_impact.py [--full]
```

### Planned outputs

| Output | Description |
|---|---|
| `stress_scenarios_mart` | Macro path (unemployment, HPI, GDP) for base, adverse, severely adverse |
| `stress_loss_mart` | Projected annual credit losses by year × scenario × segment |
| `stress_capital_mart` | CET1 drawdown and minimum capital headroom under each scenario |

---

## Concepts

### `01_scenario_construction.py` — Macro Stress Scenarios

**Purpose:** Define the macroeconomic paths for each stress scenario (adverse: 1-in-25 event; severely adverse: 1-in-100 event) and derive stressed PD/LGD inputs.

**Mathematical output:** Stressed unemployment $U_s(t)$, stressed HPI $H_s(t)$. Stressed PD: $\Phi^{-1}(\text{PD}_s) = \Phi^{-1}(\text{PD}_{\text{TTC}}) + \gamma_U \Delta U_s + \gamma_H \Delta H_s$ where $\gamma_U, \gamma_H$ are from `economy_correlations_mart`. Stressed LGD: re-index collateral at stressed $H_s(t)$ using the downturn HPI haircut method from Module 04.

**Concept:** Stress testing scenarios are calibrated to historical analogues rather than invented from scratch. The 2007–2009 financial crisis provides the severely adverse template: unemployment peaked at 10%, national HPI fell 20%, credit losses on prime mortgages peaked at 2–3% annualised. The macro conditioning coefficients from `economy_correlations_mart` translate these macro shocks into stressed PD paths in a mathematically consistent way.

---

### `02_loss_projection.py` — Stress Loss Projection

**Purpose:** Apply stressed PD/LGD to the December 2025 book to project annual credit losses over a 3-year horizon.

**Mathematical output:** Projected loss$_{\text{yr}}$ = $\sum_i \text{EAD}_i \times \text{PD}_{s,i,\text{yr}} \times \text{LGD}_{s,i,\text{yr}}$ for each stress year. Seasonality adjustment from `seasonality_mart`. Vintage curve acceleration: stressed cohorts age faster through the APC table from `apc_mart`.

**Concept:** The projection must be dynamic — stressed conditions reduce prepayments (rate-incentive disappears when rates spike) and accelerate defaults. Using a static book (applying stress PD to the starting balance without updating the book) understates losses in year 2 and 3 because the surviving book becomes riskier as the best borrowers refinance or pay off in normal times but cannot do so under stress.

---

### `03_capital_impact.py` — Capital Adequacy Under Stress

**Purpose:** Translate stressed credit losses and stressed ECL provisions into a CET1 capital ratio drawdown over the 3-year stress horizon.

**Mathematical output:** CET1 ratio depletion: $\text{CET1}_{\text{yr}} = \text{CET1}_0 - \text{Loss}_{\text{yr}} + \text{Operating profit adjustment} - \Delta\text{ECL}_{\text{yr}}$. Minimum capital headroom = CET1 ratio at trough minus regulatory minimum (4.5% Pillar 1 + firm-specific Pillar 2A).

**Concept:** The capital impact has three layers: (1) immediate ECL provision increase (day-1 P&L hit), (2) actual credit losses as loans are written off in later years, and (3) RWA inflation as LTVs rise and ratings migrate downgrade. The BoE DFAST/PRA stress test framework (concurrent stress test for major UK banks) uses this same structure. For IRB banks, the capital floor from Module 06 may become binding under stress — stressed SA capital can exceed stressed IRB capital due to the floor rule.
