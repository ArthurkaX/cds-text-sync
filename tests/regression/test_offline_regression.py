"""Pytest entry point for the offline engine regression scenarios.

The scenario bodies remain deliberately close to the original fixtures, but
pytest now owns isolation, reporting, and failure tracebacks.
"""

import importlib.util
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).with_name("offline_regression.py")
_SPEC = importlib.util.spec_from_file_location("offline_regression", _MODULE_PATH)
_REGRESSION = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_REGRESSION)


_SCENARIOS = [
    name
    for name in dir(_REGRESSION)
    if name.startswith("_scenario_")
]


@pytest.mark.parametrize("scenario_name", _SCENARIOS)
def test_offline_scenario(scenario_name, tmp_path):
    scenario = getattr(_REGRESSION, scenario_name)
    scenario(str(tmp_path))
