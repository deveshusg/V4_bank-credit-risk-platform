# Module 08 — Model Risk Management

> [!NOTE]
> **Status: Stub.** Implementation begins after Module 07 sign-off. This README documents planned operations and the concept behind each planned script.

Model governance under PRA SS1/23: a register of every model used in the platform, their assumptions
and limitations, independent validation test results, and ongoing monitoring dashboards.
Consumes `balance_rollforward_mart`, `data_plausibility_mart`, `representativeness_mart`,
`data_limits_mart`, and `survivorship_mart` from Module 02; validation metrics from Modules 03–07.

---

## Operations (Planned)

### Prerequisites

- All upstream modules (00–07) complete.
- Python 3.11+ `.venv`.

### Planned run order

```powershell
# Model register — catalogue all models and their metadata
.venv\Scripts\python.exe residential_mortgage\08_model_risk_mgmt\scripts\01_model_register.py

# Ongoing monitoring — PSI, DR drift, Gini decay
.venv\Scripts\python.exe residential_mortgage\08_model_risk_mgmt\scripts\02_ongoing_monitoring.py [--full]

# Assumption documentation — freeze all assumptions with supporting evidence
.venv\Scripts\python.exe residential_mortgage\08_model_risk_mgmt\scripts\03_assumption_log.py

# Validation summary report — aggregate all validation findings
.venv\Scripts\python.exe residential_mortgage\08_model_risk_mgmt\scripts\04_validation_report.py
```

### Planned outputs

| Output | Description |
|---|---|
| `model_register_mart` | Per-model: name, type, owner, validator, version, approval date, review date |
| `monitoring_mart` | Monthly PSI, DR vs predicted, Gini trend, population drift flags |
| `assumption_log_mart` | Per-assumption: source, value, uncertainty, review trigger |
| `validation_findings_mart` | Per-finding: severity (Critical/Major/Minor), status, remediation date |
| `08_model_risk_report.md` | Auto-generated governance summary |

---

## Concepts

### `01_model_register.py` — Model Inventory

**Purpose:** Create the definitive register of all models used in the platform with metadata required by PRA SS1/23.

**Mathematical output:** `model_register_mart`: per model — `model_id`, `model_name` (e.g. application_scorecard), `model_type` (PD / LGD / EAD / staging / capital), `owner`, `independent_validator`, `version`, `development_data_period`, `reference_data_set`, `approval_date`, `next_review_date`, `material_model_flag`.

**Concept:** PRA SS1/23 §6 requires all firms using internal models to maintain a model inventory that is comprehensive, accurate, and regularly reviewed. The inventory is the entry point for all model risk management activities — a model that is not in the register does not exist from a governance perspective and cannot be used in regulatory capital calculations.

---

### `02_ongoing_monitoring.py` — Model Performance Monitoring

**Purpose:** Monthly monitoring of model performance against the development baseline using PSI (population stability), Gini drift, and default rate back-testing.

**Mathematical output:**
- PSI from `representativeness_mart` frozen December 2025 baseline shares vs current month shares. PSI > 0.10 = monitoring trigger; PSI > 0.25 = model review required.
- Gini coefficient: rolling 12-month discrimination. Gini decay > 10 percentage points from development triggers review.
- DR back-test: compare grade-level predicted PD vs observed 12m default rate using traffic-light system (green: within 20%, amber: 20–50%, red: > 50% deviation).

**Concept:** A model that performed well in development will degrade over time as the lending population shifts and economic conditions change. SS1/23 §9 requires ongoing performance monitoring with pre-defined triggers for review. The PSI from `representativeness_mart` (computed in Module 02) is the standard industry metric for detecting population shift — the same metric used to monitor whether the model's assumptions still hold.

---

### `03_assumption_log.py` — Model Assumption Documentation

**Purpose:** Create a machine-readable log of every model assumption with its source, value, range of uncertainty, and the trigger that would require the assumption to be reviewed.

**Mathematical output:** `assumption_log_mart`: per assumption — `model_id`, `assumption_name` (e.g. `irb_residential_correlation = 0.15`), `source` (e.g. `CRR Art. 154(3)`), `value`, `uncertainty_range`, `review_trigger` (e.g. `implied_rho > 0.25 for 2 consecutive Decembers`), `last_reviewed`.

**Concept:** Every model is a system of assumptions. Some assumptions are set by regulation (ρ = 0.15) and cannot change; others are project choices (DPD_DEFAULT_MONTHS = 3, COVID hold window) that reflect departures from UK rules applied to US data. All must be documented. The `regulatory_parameters.py` file is the code-level implementation of this assumption log; `03_assumption_log.py` extracts its contents into the monitoring DB and links each assumption to its review evidence.

---

### `04_validation_report.py` — Validation Summary

**Purpose:** Aggregate all validation findings from Modules 03–07 into a single governance report, tracking finding severity and remediation status.

**Mathematical output:** `validation_findings_mart`: structured findings log. `08_model_risk_report.md`: auto-generated markdown including model inventory summary, monitoring dashboard (green/amber/red table), open validation findings, and assumption review status.

**Concept:** Independent model validation (IMV) is the third line of defence in model risk governance. IMV tests the model's conceptual soundness, the statistical validity of the development process, the appropriateness of the reference data, the adequacy of ongoing monitoring, and the accuracy of documentation. PRA SS1/23 §13 requires IMV to be independent of model development and to report directly to senior management. This module simulates IMV output for portfolio purposes — real IMV is conducted by a separate team.
