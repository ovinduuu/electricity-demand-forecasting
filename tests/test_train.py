import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from electricity_demand.models.train import run_training, time_based_split  # noqa: E402


def _make_history(days: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    start = dt.date(2024, 1, 1)
    weekday_multiplier = np.array([1.0, 0.9, 0.9, 1.0, 1.1, 1.4, 1.3])
    rows = []
    for ba_code in ["PJM", "CISO"]:
        base = rng.uniform(500_000, 2_000_000)
        for i in range(days):
            date = start + dt.timedelta(days=i)
            seasonal = base * weekday_multiplier[date.weekday()]
            noise = rng.normal(loc=1.0, scale=0.05)
            demand = max(0.0, seasonal * noise)
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "ba_code": ba_code,
                    "demand_mwh": demand,
                    "demand_forecast_mwh": demand * rng.normal(loc=1.0, scale=0.03),
                    "temp_mean_c": 15.0 + 10.0 * np.sin(i / 30),
                    "dayofweek": date.weekday(),
                    "is_weekend": int(date.weekday() >= 5),
                    "month": date.month,
                    "is_holiday": 0,
                    "holiday_name": None,
                }
            )
    return pd.DataFrame(rows)


def test_time_based_split_holds_out_recent_days():
    history = _make_history()
    train, valid = time_based_split(history, valid_days=14)

    assert train["date"].max() == valid["date"].min() - pd.Timedelta(days=1)
    assert (valid["date"] > train["date"].max()).all()


def test_run_training_produces_model_and_metrics():
    history = _make_history()
    model, metrics, valid_df, features = run_training(history, valid_days=14)

    assert model.num_trees() > 0
    expected_keys = {
        "mape",
        "mape_per_ba_mean",
        "rmse",
        "n",
        "n_ba",
        "best_iteration",
        "n_train_rows",
        "n_valid_rows",
        "eia_day_ahead_mape",
        "eia_day_ahead_rmse",
    }
    assert expected_keys.issubset(metrics)
    assert metrics["n"] > 0
    assert len(features) > 0
    assert not valid_df.empty
