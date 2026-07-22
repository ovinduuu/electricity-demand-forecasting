import datetime as dt

import pandas as pd

from electricity_demand.models.features import build_features, feature_columns


def _make_history(days: int = 40) -> pd.DataFrame:
    # dayofweek/is_weekend/month are pre-computed pass-through columns from
    # dbt's fct_demand (see features.py's module docstring) - build_features()
    # doesn't derive them, so the fixture must already carry them.
    start = dt.date(2024, 1, 1)
    rows = []
    for ba_code in ["PJM", "CISO"]:
        for i in range(days):
            date = start + dt.timedelta(days=i)
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "ba_code": ba_code,
                    "demand_mwh": float(1000 + i % 7),
                    "dayofweek": date.weekday(),
                    "is_weekend": int(date.weekday() >= 5),
                    "month": date.month,
                }
            )
    return pd.DataFrame(rows)


def test_build_features_adds_expected_columns():
    df = build_features(_make_history())
    for col in [
        "demand_lag_1",
        "demand_lag_2",
        "demand_lag_3",
        "demand_lag_7",
        "demand_lag_14",
        "demand_lag_28",
        "demand_roll_mean_7",
        "demand_roll_mean_28",
        "demand_roll_std_7",
        "demand_roll_std_28",
        "dayofweek",
        "is_weekend",
        "month",
    ]:
        assert col in df.columns


def test_lag_feature_does_not_leak_current_day():
    df = build_features(_make_history())
    one_series = df[df.ba_code == "PJM"].sort_values("date")
    shifted_expected = one_series["demand_mwh"].shift(7)
    pd.testing.assert_series_equal(
        one_series["demand_lag_7"].reset_index(drop=True),
        shifted_expected.reset_index(drop=True),
        check_names=False,
    )


def test_rolling_mean_excludes_current_day():
    # A constant-then-jump series makes leakage obvious: if today's value
    # leaked into its own rolling mean, the mean at the jump day would move.
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {"date": dates, "ba_code": ["PJM"] * 10, "demand_mwh": [500.0] * 9 + [50000.0]}
    )
    featured = build_features(df)
    last_row = featured.iloc[-1]
    assert last_row["demand_roll_mean_7"] == 500.0


def test_rolling_std_excludes_current_day():
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {"date": dates, "ba_code": ["PJM"] * 10, "demand_mwh": [500.0] * 9 + [50000.0]}
    )
    featured = build_features(df)
    last_row = featured.iloc[-1]
    assert last_row["demand_roll_std_7"] == 0.0  # the constant 500.0 run, not the jump


def test_degree_days_computed_from_temp_mean():
    df = _make_history(days=5)
    df["temp_mean_c"] = [10.0, 18.0, 25.0, 10.0, 18.0] * 2

    featured = build_features(df)

    assert featured.loc[featured["temp_mean_c"] == 10.0, "heating_degree_days"].iloc[0] == 8.0
    assert featured.loc[featured["temp_mean_c"] == 10.0, "cooling_degree_days"].iloc[0] == 0.0
    assert featured.loc[featured["temp_mean_c"] == 25.0, "cooling_degree_days"].iloc[0] == 7.0
    assert featured.loc[featured["temp_mean_c"] == 25.0, "heating_degree_days"].iloc[0] == 0.0
    assert featured.loc[featured["temp_mean_c"] == 18.0, "heating_degree_days"].iloc[0] == 0.0
    assert featured.loc[featured["temp_mean_c"] == 18.0, "cooling_degree_days"].iloc[0] == 0.0


def test_optional_columns_produce_extra_features():
    df = _make_history(days=10)
    df["temp_mean_c"] = 15.0
    df["demand_forecast_mwh"] = 1000.0
    # one series (2 BAs x 10 days, ordered BA-then-day): holiday on the last
    # day of each series.
    df["holiday_name"] = ([None] * 9 + ["Independence Day"]) * 2

    featured = build_features(df)
    numeric_and_cat, categorical = feature_columns(featured)

    assert "temp_mean_c" in numeric_and_cat
    assert "demand_forecast_mwh" in numeric_and_cat
    assert "heating_degree_days" in numeric_and_cat
    assert categorical == ["ba_code", "holiday_name"]
    assert (featured["holiday_name"] == "Independence Day").sum() == 2


def test_feature_columns_omits_missing_optional_columns():
    df = build_features(_make_history(days=5))
    numeric_and_cat, categorical = feature_columns(df)
    assert "temp_mean_c" not in numeric_and_cat
    assert "demand_forecast_mwh" not in numeric_and_cat
    assert categorical == ["ba_code"]
