import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from electricity_demand.serving.batch_predict import (  # noqa: E402
    build_next_day_frame,
    predict_next_day,
    resolve_model_path,
)


def test_resolve_model_path_passes_through_local_paths():
    assert resolve_model_path("artifacts/lightgbm_model.txt") == "artifacts/lightgbm_model.txt"


def _make_history(days: int = 90) -> pd.DataFrame:
    rng = np.random.default_rng(1)
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
                    "dayofweek": date.weekday(),
                    "is_weekend": int(date.weekday() >= 5),
                    "month": date.month,
                    "is_holiday": 0,
                    "holiday_name": None,
                }
            )
    return pd.DataFrame(rows)


def test_build_next_day_frame_adds_one_stub_row_per_ba():
    history = _make_history()
    n_bas = history["ba_code"].nunique()

    augmented, next_day = build_next_day_frame(history)

    assert next_day == history["date"].max() + pd.Timedelta(days=1)
    assert len(augmented) == len(history) + n_bas
    stub_rows = augmented[augmented["date"] == next_day]
    assert len(stub_rows) == n_bas
    assert stub_rows["demand_mwh"].isna().all()


def test_build_next_day_frame_fills_temp_via_persistence():
    history = _make_history()
    history = history.copy()
    # Give each BA a distinctive, easy-to-check last known temp.
    history.loc[history.ba_code == "PJM", "temp_mean_c"] = 20.0
    history.loc[history.ba_code == "CISO", "temp_mean_c"] = 25.0
    last_pjm_row = history[history.ba_code == "PJM"]["date"].idxmax()
    history.loc[last_pjm_row, "temp_mean_c"] = 22.5

    augmented, next_day = build_next_day_frame(history)

    stub_rows = augmented[augmented["date"] == next_day].set_index("ba_code")
    assert stub_rows.loc["PJM", "temp_mean_c"] == 22.5
    assert stub_rows.loc["CISO", "temp_mean_c"] == 25.0


def test_build_next_day_frame_fills_calendar_columns_for_the_stub_row():
    history = _make_history()
    augmented, next_day = build_next_day_frame(history)

    stub_rows = augmented[augmented["date"] == next_day]
    assert stub_rows["dayofweek"].iloc[0] == next_day.weekday()
    assert stub_rows["is_weekend"].notna().all()
    assert stub_rows["month"].iloc[0] == next_day.month


def test_predict_next_day_returns_one_nonnegative_row_per_ba():
    history = _make_history()
    n_bas = history["ba_code"].nunique()

    from electricity_demand.models.train import run_training

    model, _, _, _ = run_training(history, valid_days=14)
    predictions = predict_next_day(history, model)

    assert len(predictions) == n_bas
    assert (predictions["predicted_demand_mwh"] >= 0).all()
    assert (predictions["date"] == history["date"].max() + pd.Timedelta(days=1)).all()
    assert set(predictions.columns) == {"date", "ba_code", "predicted_demand_mwh"}
