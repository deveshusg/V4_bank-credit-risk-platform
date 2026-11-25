"""Application scorecard

Module 3 (03_rating_and_pd). Not built yet.

What it will do: Scorecard built only from what was known when the loan was made.
Needs first: Module 2: 02_default_engine.py.
Built only after the Module 3 design is signed off (docs/module_3/).
"""
import sys
from pathlib import Path

# Window vocabulary: single source in residential_mortgage/windows.py
# (05_observation_windows.ipynb draws it). Observation window = features at t0-1 and earlier;
# performance window = outcome after t0. Imported so every Module 3 builder shares the constants.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import windows  # noqa: F401

sys.exit("Not built yet: 03_rating_and_pd/01_application_scorecard.py. Waits for the Module 3 design sign-off.")
