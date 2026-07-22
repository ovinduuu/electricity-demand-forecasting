import datetime as dt

import pandas as pd

from electricity_demand.models.baseline import naive_forecast, seasonal_naive_forecast


def _make_history(days: int = 14) -> pd.DataFrame:
    start = dt.date(2024, 1, 1)
    rows = []
    for ba_code in ["PJM", "CISO"]:
        for i in range(days):
            rows.append(
                {
                    "date": pd.Timestamp(start + dt.timedelta(days=i)),
                    "ba_code": ba_code,
                    "demand_mwh": float(i % 7),
                }
            )
    return pd.DataFrame(rows)


def test_naive_forecast_repeats_last_value():
    history = _make_history()
    forecast = naive_forecast(history, horizon=3)

    assert len(forecast) == 2 * 3  # 2 BAs x 3-day horizon
    last_actual = history.sort_values("date").groupby("ba_code").tail(1)
    for _, row in last_actual.iterrows():
        series_forecast = forecast[forecast.ba_code == row.ba_code]
        assert (series_forecast["demand_mwh"] == row.demand_mwh).all()


def test_naive_forecast_dates_continue_from_history():
    history = _make_history()
    forecast = naive_forecast(history, horizon=2)
    last_date = history["date"].max()
    expected_dates = {last_date + pd.Timedelta(days=1), last_date + pd.Timedelta(days=2)}
    assert set(forecast["date"]) == expected_dates


def test_seasonal_naive_forecast_cycles_through_season():
    history = _make_history(days=14)
    forecast = seasonal_naive_forecast(history, horizon=7, season_length=7)

    one_series = forecast[forecast.ba_code == "PJM"].sort_values("date")
    # last 7 days of history are demand values [0,1,2,3,4,5,6] (day 7..13 % 7)
    assert list(one_series["demand_mwh"]) == [0, 1, 2, 3, 4, 5, 6]


def test_seasonal_naive_handles_short_history():
    history = _make_history(days=2)
    forecast = seasonal_naive_forecast(history, horizon=3, season_length=7)
    assert len(forecast) == 2 * 3
    assert (forecast["demand_mwh"] >= 0).all()
