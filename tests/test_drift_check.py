import numpy as np
import pandas as pd

from electricity_demand.monitoring.drift_check import (
    check_feature_drift,
    population_stability_index,
)


def test_psi_is_near_zero_for_identical_distributions():
    rng = np.random.default_rng(0)
    reference = rng.normal(loc=10, scale=2, size=2000)
    current = rng.normal(loc=10, scale=2, size=2000)

    psi = population_stability_index(reference, current)

    assert psi < 0.05


def test_psi_is_large_for_a_clearly_shifted_distribution():
    rng = np.random.default_rng(0)
    reference = rng.normal(loc=10, scale=2, size=2000)
    current = rng.normal(loc=25, scale=2, size=2000)

    psi = population_stability_index(reference, current)

    assert psi > 0.2


def test_psi_handles_empty_input():
    assert population_stability_index(np.array([]), np.array([1.0, 2.0])) == 0.0
    assert population_stability_index(np.array([1.0, 2.0]), np.array([])) == 0.0


def test_psi_handles_constant_reference():
    reference = np.full(100, 5.0)
    current = np.full(100, 5.0)
    assert population_stability_index(reference, current) == 0.0


def test_check_feature_drift_flags_only_columns_over_threshold():
    rng = np.random.default_rng(1)
    reference_df = pd.DataFrame(
        {
            "stable": rng.normal(loc=0, scale=1, size=1000),
            "shifted": rng.normal(loc=0, scale=1, size=1000),
            "ba_code": rng.choice(["PJM", "CISO"], size=1000),
        }
    )
    current_df = pd.DataFrame(
        {
            "stable": rng.normal(loc=0, scale=1, size=1000),
            "shifted": rng.normal(loc=15, scale=1, size=1000),
            "ba_code": rng.choice(["PJM", "CISO"], size=1000),
        }
    )

    results = check_feature_drift(
        reference_df, current_df, ["stable", "shifted", "ba_code"], threshold=0.2
    )

    assert set(results["feature"]) == {"stable", "shifted"}  # ba_code skipped (non-numeric)
    stable_row = results[results.feature == "stable"].iloc[0]
    shifted_row = results[results.feature == "shifted"].iloc[0]
    assert not stable_row["drifted"]
    assert shifted_row["drifted"]
