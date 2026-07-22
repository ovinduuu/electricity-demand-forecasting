"""Naive and seasonal-naive forecast baselines - one of three bars a trained
model needs to clear, alongside EIA's own published day-ahead forecast (see
evaluate.py's evaluate_eia_day_ahead_forecast). Operates on the same
long-format schema used throughout the project: one row per
(date, ba_code, demand_mwh).
"""

from __future__ import annotations

import pandas as pd

SEASON_LENGTH_DEFAULT = 7  # weekly seasonality


def naive_forecast(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Repeat each BA's last observed demand for the next `horizon` days."""
    rows = []
    for ba_code, series in history.groupby("ba_code"):
        series = series.sort_values("date")
        last_date = series["date"].iloc[-1]
        last_value = series["demand_mwh"].iloc[-1]
        for step in range(1, horizon + 1):
            rows.append(
                {
                    "date": last_date + pd.Timedelta(days=step),
                    "ba_code": ba_code,
                    "demand_mwh": last_value,
                }
            )
    return pd.DataFrame(rows, columns=["date", "ba_code", "demand_mwh"])


def seasonal_naive_forecast(
    history: pd.DataFrame, horizon: int, season_length: int = SEASON_LENGTH_DEFAULT
) -> pd.DataFrame:
    """Repeat each BA's demand from `season_length` days ago, cycling forward."""
    rows = []
    for ba_code, series in history.groupby("ba_code"):
        series = series.sort_values("date")
        last_date = series["date"].iloc[-1]
        tail = series["demand_mwh"].tail(season_length).to_numpy()
        if tail.size == 0:
            continue
        for step in range(1, horizon + 1):
            value = tail[(step - 1) % tail.size]
            rows.append(
                {
                    "date": last_date + pd.Timedelta(days=step),
                    "ba_code": ba_code,
                    "demand_mwh": value,
                }
            )
    return pd.DataFrame(rows, columns=["date", "ba_code", "demand_mwh"])
