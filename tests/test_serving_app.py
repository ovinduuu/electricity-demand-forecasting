import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from electricity_demand.data_engineering.balancing_authorities import (
    BALANCING_AUTHORITIES,  # noqa: E402
)
from electricity_demand.serving.app import app  # noqa: E402


def _train_tiny_model(tmp_path) -> str:
    import lightgbm as lgb

    rng = np.random.default_rng(0)
    n = 100
    df = pd.DataFrame(
        {
            "x": rng.normal(size=n),
            "ba_code": rng.choice(["PJM", "CISO"], size=n),
        }
    )
    df["ba_code"] = df["ba_code"].astype("category")
    y = df["x"] + df["ba_code"].cat.codes.astype(float) * 3

    train_set = lgb.Dataset(df, label=y, categorical_feature=["ba_code"])
    model = lgb.train({"objective": "regression", "verbosity": -1}, train_set, num_boost_round=10)

    model_path = tmp_path / "model.txt"
    model.save_model(str(model_path))
    return str(model_path)


def _make_history(days: int = 90) -> pd.DataFrame:
    rng = np.random.default_rng(2)
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
                    "temp_mean_c": 15.0,
                    "dayofweek": date.weekday(),
                    "is_weekend": int(date.weekday() >= 5),
                    "month": date.month,
                    "is_holiday": 0,
                    "holiday_name": None,
                }
            )
    return pd.DataFrame(rows)


def _train_real_model(tmp_path, history: pd.DataFrame) -> str:
    from electricity_demand.models.train import run_training

    model, _, _, _ = run_training(history, valid_days=14)
    model_path = tmp_path / "real_model.txt"
    model.save_model(str(model_path))
    return str(model_path)


def test_health_returns_ok():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_predict_returns_nonnegative_predictions(tmp_path, monkeypatch):
    model_path = _train_tiny_model(tmp_path)
    monkeypatch.setenv("MODEL_PATH", model_path)

    client = TestClient(app)
    resp = client.post(
        "/predict",
        json={"instances": [{"x": 1.0, "ba_code": "PJM"}, {"x": -5.0, "ba_code": "CISO"}]},
    )

    assert resp.status_code == 200
    predictions = resp.json()["predictions"]
    assert len(predictions) == 2
    assert all(p >= 0 for p in predictions)


def test_predict_uses_only_the_models_own_feature_columns(tmp_path, monkeypatch):
    model_path = _train_tiny_model(tmp_path)
    monkeypatch.setenv("MODEL_PATH", model_path)

    client = TestClient(app)
    # Extra, unrelated fields in the instance should be ignored rather than error.
    resp = client.post(
        "/predict",
        json={"instances": [{"x": 0.0, "ba_code": "PJM", "unused_field": "ignored"}]},
    )
    assert resp.status_code == 200
    assert len(resp.json()["predictions"]) == 1


def _csv_backed_client(tmp_path, monkeypatch, history: pd.DataFrame) -> TestClient:
    csv_path = tmp_path / "history.csv"
    history.to_csv(csv_path, index=False)
    monkeypatch.setenv("LOCAL_DATA_CSV", str(csv_path))
    monkeypatch.setenv("MODEL_PATH", _train_real_model(tmp_path, history))
    return TestClient(app)


def test_series_lists_all_tracked_balancing_authorities(tmp_path, monkeypatch):
    history = _make_history()
    client = _csv_backed_client(tmp_path, monkeypatch, history)

    resp = client.get("/series")

    assert resp.status_code == 200
    codes = {s["ba_code"] for s in resp.json()}
    # /series is the static tracked-BA list, not data-driven - unlike M5's
    # item catalog, BAs don't go dormant, so it's independent of the CSV.
    assert codes == {ba.ba_code for ba in BALANCING_AUTHORITIES}


def test_history_returns_recent_points_for_known_ba(tmp_path, monkeypatch):
    history = _make_history()
    client = _csv_backed_client(tmp_path, monkeypatch, history)

    resp = client.get("/history/PJM", params={"days": 10})

    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 10
    assert points[-1]["date"] == history["date"].max().date().isoformat()


def test_history_404s_for_unknown_ba(tmp_path, monkeypatch):
    history = _make_history()
    client = _csv_backed_client(tmp_path, monkeypatch, history)

    resp = client.get("/history/UNKNOWN")
    assert resp.status_code == 404


def test_forecast_returns_one_nonnegative_point_for_known_ba(tmp_path, monkeypatch):
    history = _make_history()
    client = _csv_backed_client(tmp_path, monkeypatch, history)

    resp = client.get("/forecast/PJM")

    assert resp.status_code == 200
    body = resp.json()
    assert body["predicted_demand_mwh"] >= 0
    assert body["date"] == (history["date"].max() + pd.Timedelta(days=1)).date().isoformat()


def _make_predictions(history: pd.DataFrame) -> pd.DataFrame:
    """One prediction per BA for each of the last 3 days in `history`,
    offset from the actual by a small fixed amount so accuracy math is
    checkable.
    """
    rows = []
    for ba_code, series in history.groupby("ba_code"):
        for _, row in series.sort_values("date").tail(3).iterrows():
            rows.append(
                {
                    "date": row["date"],
                    "ba_code": ba_code,
                    "predicted_demand_mwh": row["demand_mwh"] + 2,
                }
            )
    return pd.DataFrame(rows)


def _predictions_backed_client(tmp_path, monkeypatch, history: pd.DataFrame) -> TestClient:
    client = _csv_backed_client(tmp_path, monkeypatch, history)
    predictions_path = tmp_path / "predictions.csv"
    _make_predictions(history).to_csv(predictions_path, index=False)
    monkeypatch.setenv("LOCAL_PREDICTIONS_CSV", str(predictions_path))
    return client


def test_accuracy_daily_returns_one_row_per_predicted_date_with_positive_error(
    tmp_path, monkeypatch
):
    history = _make_history()
    client = _predictions_backed_client(tmp_path, monkeypatch, history)

    resp = client.get("/accuracy")

    assert resp.status_code == 200
    days = resp.json()
    assert len(days) == 3
    for day in days:
        assert day["n_predictions"] == 2  # two BAs in _make_history
        assert day["mae"] == pytest.approx(2.0)
        assert day["rmse"] == pytest.approx(2.0)


def test_series_accuracy_returns_predicted_and_actual_for_one_ba(tmp_path, monkeypatch):
    history = _make_history()
    client = _predictions_backed_client(tmp_path, monkeypatch, history)

    resp = client.get("/accuracy/PJM")

    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 3
    for point in points:
        assert point["predicted_demand_mwh"] == pytest.approx(point["actual_demand_mwh"] + 2)


def test_series_accuracy_empty_for_ba_with_no_predictions(tmp_path, monkeypatch):
    history = _make_history()
    client = _predictions_backed_client(tmp_path, monkeypatch, history)

    resp = client.get("/accuracy/UNKNOWN")

    assert resp.status_code == 200
    assert resp.json() == []


def test_model_info_returns_the_latest_run(tmp_path, monkeypatch):
    import json

    run = {
        "trained_at": "2026-07-16T12:20:15+00:00",
        "mape_per_ba_mean": 0.0225,
        "mape": 0.0225,
        "rmse": 49314.7,
        "eia_day_ahead_mape": 0.0326,
        "n_train_rows": 26940,
    }
    run_path = tmp_path / "model_run.json"
    run_path.write_text(json.dumps(run))
    monkeypatch.setenv("LOCAL_MODEL_RUN_JSON", str(run_path))

    client = TestClient(app)
    resp = client.get("/model-info")

    assert resp.status_code == 200
    assert resp.json() == run
