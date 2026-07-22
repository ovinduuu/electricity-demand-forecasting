import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from electricity_demand.serving.backfill_predictions import (  # noqa: E402
    backfill_targets,
    run_backfill,
)


def test_backfill_targets_returns_last_n_days_ending_at_latest():
    targets = backfill_targets(dt.date(2026, 7, 14), backfill_days=14)

    assert len(targets) == 14
    assert targets[0] == dt.date(2026, 7, 1)
    assert targets[-1] == dt.date(2026, 7, 14)
    assert targets == sorted(targets)


def _make_history(days: int = 90) -> pd.DataFrame:
    rng = np.random.default_rng(3)
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


def test_run_backfill_predicts_each_target_using_only_prior_history():
    history = _make_history()
    n_bas = history["ba_code"].nunique()

    from electricity_demand.models.train import run_training

    model, _, _, _ = run_training(history, valid_days=14)

    last_14_dates = sorted(history["date"].dt.date.unique())[-14:]
    predictions = run_backfill(history, last_14_dates, model)

    assert len(predictions) == n_bas * 14
    assert set(predictions["date"].dt.date) == set(last_14_dates)
    assert (predictions["predicted_demand_mwh"] >= 0).all()


def test_run_backfill_skips_targets_with_no_prior_history():
    history = _make_history()
    too_early = dt.date(2020, 1, 1)  # long before any history exists

    from electricity_demand.models.train import run_training

    model, _, _, _ = run_training(history, valid_days=14)
    predictions = run_backfill(history, [too_early], model)

    assert predictions.empty
