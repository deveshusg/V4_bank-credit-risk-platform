"""Default rate history, book snapshots and the out-of-time split

Module 2 (02_portfolio_analytics). Not built yet.

What it will do: 12-month default rate at each month-end and for each December book snapshot,
plus the dev/validation/out-of-time split that Module 3 reads. This is where the observation
and performance windows from residential_mortgage/windows.py are applied: t0 is a December
snapshot, features come from the observation window ending at t0-1, and the label is a default
starting inside the 12-month performance window.
Needs first: 05_current_ltv.py (per docs/module_2/module-2-plan.md stages 5 and 6).
Built only after the Module 2 design is signed off (docs/module_2/).
"""
import sys
from pathlib import Path

# Window vocabulary: single source in residential_mortgage/windows.py (05_observation_windows.ipynb).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows  # noqa: F401  (SNAPSHOT_MONTH, PERFORMANCE_WINDOW_MONTHS, OUT_OF_TIME_*)

sys.exit("Not built yet: 02_portfolio_analytics/06_default_rate_history.py. Waits for the Module 2 design sign-off.")
