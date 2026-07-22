"""Evaluation for electricity demand forecasts: MAPE/RMSE, both pooled and
averaged per balancing authority, plus a benchmark against EIA's own
published day-ahead demand forecast.

No WRMSSE here (unlike the old retail project): that metric is M5's
hierarchical weighted-RMSSE across the store/item tree, and there's no
equivalent hierarchy for a flat set of ~10 balancing authorities. The
register-if-improved gate this project uses instead is `mape_per_ba_mean`
(unweighted - with only 10 BAs, weighting by demand volume the way the old
project's compute_series_weights did isn't worth the complexity).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from electricity_demand.models.features import ID_COLUMNS


def mape(y_true, y_pred, epsilon: float = 1.0) -> float:
    """Mean absolute percentage error, with an epsilon floor to survive zero actuals."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(y_true - y_pred) / np.maximum(np.abs(y_true), epsilon)))


def rmse(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def per_ba_mape(actual: pd.DataFrame, forecast: pd.DataFrame) -> pd.DataFrame:
    """MAPE for each ba_code - averaged (unweighted) by evaluate_predictions
    for the register-if-improved gate, so one high-demand BA can't dominate
    a single pooled MAPE number.
    """
    merged = actual.merge(forecast, on=["date", *ID_COLUMNS], suffixes=("_actual", "_forecast"))
    rows = [
        {"ba_code": ba_code, "mape": mape(group["demand_mwh_actual"], group["demand_mwh_forecast"])}
        for ba_code, group in merged.groupby("ba_code")
    ]
    return pd.DataFrame(rows, columns=["ba_code", "mape"])


def evaluate_predictions(actual: pd.DataFrame, forecast: pd.DataFrame) -> dict:
    """MAPE/RMSE for a forecast against actuals, both pooled and averaged per BA."""
    merged = actual.merge(forecast, on=["date", *ID_COLUMNS], suffixes=("_actual", "_forecast"))
    per_ba = per_ba_mape(actual, forecast)
    return {
        "mape": mape(merged["demand_mwh_actual"], merged["demand_mwh_forecast"]),
        "mape_per_ba_mean": float(per_ba["mape"].mean()),
        "rmse": rmse(merged["demand_mwh_actual"], merged["demand_mwh_forecast"]),
        "n": len(merged),
        "n_ba": len(per_ba),
    }


def evaluate_eia_day_ahead_forecast(df: pd.DataFrame) -> dict:
    """Benchmark: how good is EIA's own published day-ahead demand forecast
    (demand_forecast_mwh) against the actual (demand_mwh)? A genuine "did our
    model beat the grid operator's own forecast" number, not a naive
    baseline - EIA already publishes one, unlike M5's retail data.
    """
    scored = df.dropna(subset=["demand_mwh", "demand_forecast_mwh"])
    return {
        "mape": mape(scored["demand_mwh"], scored["demand_forecast_mwh"]),
        "rmse": rmse(scored["demand_mwh"], scored["demand_forecast_mwh"]),
        "n": len(scored),
    }
