"""Point-in-time PD

Module 3 (03_rating_and_pd). Not built yet.

What it will do: PD that moves with the economy. Used for IFRS 9.
Needs first: 01_application_scorecard.py.
Built only after the Module 3 design is signed off (docs/module_3/).
"""
import sys
from pathlib import Path

# Window vocabulary: single source in residential_mortgage/_settings/windows.py
# (05_observation_windows.ipynb draws it). Observation window = features at t0-1 and earlier;
# performance window = outcome after t0. Imported so every Module 3 builder shares the constants.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _settings import windows  # noqa: F401

sys.exit("Not built yet: 03_rating_and_pd/03_pit_pd.py. Waits for the Module 3 design sign-off.")
