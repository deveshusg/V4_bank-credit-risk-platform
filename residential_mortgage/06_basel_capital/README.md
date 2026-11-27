# Module 06 — Basel 3.1 Capital

> [!NOTE]
> **Status: Stub.** Implementation begins after Module 05 sign-off. This README documents planned operations and the concept behind each planned script.

Computes Pillar 1 regulatory capital under the UK Basel 3.1 Standardised Approach (SA) and
Internal Ratings-Based (IRB) Approach for the residential mortgage book.
Consumes `book_snapshot`, `current_ltv_mart`, `portfolio_mix_mart`, `concentration_mart`,
`implied_correlation_mart`, and `loan_origination_value_mart` from Module 02; PD from Module 03; LGD/EAD from Module 04.

---

## Operations (Planned)

### Prerequisites

- Modules 02, 03, and 04 complete.
- Python 3.11+ `.venv`.

### Planned scripts (to be scoped at Module 06 design sign-off)

```powershell
# SA risk weights: LTV-band × occupancy → risk weight per PS9/24
.venv\Scripts\python.exe residential_mortgage\06_basel_capital\scripts\01_sa_risk_weights.py [--full]

# IRB formula: Vasicek ASRF → K → RWA per loan
.venv\Scripts\python.exe residential_mortgage\06_basel_capital\scripts\02_irb_risk_weights.py [--full]

# Capital floor: max(SA floor × 72.5%, IRB) per output floor rules
.venv\Scripts\python.exe residential_mortgage\06_basel_capital\scripts\03_capital_floor.py [--full]
```

### Planned outputs

| Output | Description |
|---|---|
| `sa_rwa_mart` | SA risk weight and RWA per LTV band and loan segment |
| `irb_rwa_mart` | IRB K, RWA, and CET1 per loan and grade |
| `capital_floor_mart` | Binding capital floor comparison (SA floor vs IRB) per segment |

---

## Concepts

### SA Risk Weights — Art. 124D (PS9/24)

**Purpose:** Apply the Basel 3.1 Standardised Approach risk weights to the mortgage book using LTV bands and occupancy type.

**Mathematical output:** SA risk weight from PS9/24 tables:
- Owner-occupied (P), LTV ≤ 50%: 20%; LTV 50–60%: 25%; LTV 60–80%: 30%; LTV 80–90%: 40%; LTV 90–100%: 50%; LTV > 100%: 70%.
- Investment property (I/S): same schedule but higher weights for LTV > 80%.
- Income-producing real estate (IPRE): different schedule.

LTV used = `downward-only LTV` from `current_ltv_mart` (conservative per Art. 124D — collateral can never be assumed to have appreciated for SA purposes).

**Concept:** The SA assigns a fixed risk weight based on the LTV at origination (using downward-only indexation), without considering borrower creditworthiness. This is intentionally conservative: it over-capitalises good borrowers and under-capitalises bad ones, creating a strong incentive for banks to adopt the IRB approach for large mortgage books.

---

### IRB Formula — CRR Art. 154

**Purpose:** Apply the ASRF (Asymptotic Single Risk Factor) Basel formula to compute K (capital requirement) for each loan using the IRB PD, LGD, and the fixed residential mortgage asset correlation ρ = 0.15.

**Mathematical output:** IRB capital requirement per loan:
$$K = \left[\text{LGD} \cdot \Phi\!\left(\sqrt{\frac{1}{1-\rho}}\Phi^{-1}(\text{PD}) + \sqrt{\frac{\rho}{1-\rho}}\Phi^{-1}(0.999)\right) - \text{PD} \cdot \text{LGD}\right] \times M_{\text{adj}}$$
where $\rho = 0.15$ (Art. 154(3)), $\Phi^{-1}(0.999)$ is the 99.9th percentile standard normal (the 1-in-1000 year systemic shock), and $M_{\text{adj}}$ is the maturity adjustment.

RWA = $K \times 12.5 \times \text{EAD}$.

**Concept:** The ASRF formula assumes all defaults are driven by a single systemic factor (the economy). At the 99.9th percentile confidence level (the PRA's regulatory standard), the formula computes the unexpected loss beyond the expected loss already covered by provisions. The fixed $\rho = 0.15$ is set by regulation for retail mortgages; Module 02's implied correlation estimate is a cross-validation, not an override.

---

### Capital Output Floor — CRR Art. 92a (Basel 3.1 Finalisation)

**Purpose:** Apply the 72.5% capital floor — IRB capital must be at least 72.5% of SA capital. Where IRB RWA is lower than 72.5% × SA RWA, the floor applies and IRB capital is floored up.

**Mathematical output:** Per loan: `binding_capital = max(irb_rwa, 0.725 × sa_rwa)`. Aggregate floor impact = sum of `max(0, 0.725 × sa_rwa − irb_rwa)` across all loans.

**Concept:** The Basel 3.1 output floor was introduced to prevent excessive divergence between SA and IRB capital. Banks with sophisticated IRB models had computed RWAs as low as 20–30% of SA for prime mortgages. The 72.5% floor puts a lower bound on this benefit, increasing capital for IRB banks in transition. Full implementation in the UK by 2030 (PRA PS17/23).
