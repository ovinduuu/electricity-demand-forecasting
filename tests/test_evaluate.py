import pandas as pd

from electricity_demand.models.evaluate import (
    evaluate_eia_day_ahead_forecast,
    evaluate_predictions,
    mape,
    per_ba_mape,
    rmse,
)


def _series(ba_code, dates, demand):
    return pd.DataFrame({"date": dates, "ba_code": ba_code, "demand_mwh": demand})


def test_mape_and_rmse_zero_for_perfect_forecast():
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    actual = _series("PJM", dates, [1000.0, 2000.0, 3000.0])
    assert mape(actual["demand_mwh"], actual["demand_mwh"]) == 0.0
    assert rmse(actual["demand_mwh"], actual["demand_mwh"]) == 0.0


def test_per_ba_mape_is_per_ba_not_pooled():
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    actual = pd.concat(
        [_series("PJM", dates, [100.0, 100.0]), _series("CISO", dates, [100.0, 100.0])]
    )
    # PJM forecast off by 10%, CISO forecast off by 50%.
    forecast = pd.concat(
        [_series("PJM", dates, [90.0, 90.0]), _series("CISO", dates, [50.0, 50.0])]
    )

    result = per_ba_mape(actual, forecast)

    pjm_mape = result.loc[result.ba_code == "PJM", "mape"].iloc[0]
    ciso_mape = result.loc[result.ba_code == "CISO", "mape"].iloc[0]
    assert round(pjm_mape, 2) == 0.10
    assert round(ciso_mape, 2) == 0.50


def test_evaluate_predictions_averages_per_ba_unweighted():
    dates = pd.date_range("2024-01-01", periods=1, freq="D")
    # PJM is 100x CISO's demand - mape_per_ba_mean should still weight them
    # equally (unlike a pooled MAPE, which a high-demand BA could dominate).
    actual = pd.concat([_series("PJM", dates, [100000.0]), _series("CISO", dates, [1000.0])])
    forecast = pd.concat([_series("PJM", dates, [90000.0]), _series("CISO", dates, [500.0])])

    result = evaluate_predictions(actual, forecast)

    assert result["n"] == 2
    assert result["n_ba"] == 2
    # (0.10 + 0.50) / 2 = 0.30, unweighted mean of the two per-BA MAPEs.
    assert round(result["mape_per_ba_mean"], 2) == 0.30


def test_evaluate_eia_day_ahead_forecast_scores_df_column():
    df = pd.DataFrame(
        {
            "demand_mwh": [1000.0, 2000.0, None],
            "demand_forecast_mwh": [900.0, 2000.0, 500.0],
        }
    )
    result = evaluate_eia_day_ahead_forecast(df)
    # the null-demand row is dropped, so only 2 rows scored.
    assert result["n"] == 2
    assert result["mape"] > 0


def test_evaluate_eia_day_ahead_forecast_handles_missing_column():
    # demand_forecast_mwh is optional (see features.py) - a caller without
    # it must not KeyError.
    df = pd.DataFrame({"demand_mwh": [1000.0, 2000.0]})
    result = evaluate_eia_day_ahead_forecast(df)
    assert result == {"mape": None, "rmse": None, "n": 0}
