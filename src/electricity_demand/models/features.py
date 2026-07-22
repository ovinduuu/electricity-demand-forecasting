"""Feature engineering on top of the project's core demand schema (date,
ba_code, demand_mwh), plus whatever optional `fct_demand` columns
(demand_forecast_mwh, temp_mean_c, dayofweek, is_weekend, month, is_holiday,
holiday_name) happen to be present.

All lag/rolling features are computed from data strictly before the target
date (rolling stats are taken over a series shifted by one day first), so
none of them leak the current day's own demand into its own features - same
invariant as the old retail project's features.py.

Calendar columns (dayofweek/is_weekend/month/is_holiday/holiday_name) come
pre-computed from dbt's fct_demand (joined from dim_calendar), unlike the old
project which re-derived them from a raw date column - no need to redo that
here, they're already correct, deterministic calendar facts.
"""

from __future__ import annotations

import pandas as pd

LAGS = [1, 2, 3, 7, 14, 28]
ROLLING_WINDOWS = [7, 28]
# Heating/cooling degree days use 18C (65F) as the reference indoor
# temperature - the standard base in HDD/CDD calculations, below which
# heating demand kicks in and above which cooling demand kicks in.
DEGREE_DAY_BASE_C = 18.0

# Raw columns build_features()/feature_columns() can make use of - every
# caller that queries fct_demand for feature-building (pipelines/queries.py,
# serving/app.py, serving/batch_predict.py) must select all of these, or the
# resulting feature set silently comes up short and trained-vs-serving
# feature counts diverge (same failure mode the old project's
# RAW_SOURCE_COLUMNS comment warns about).
RAW_SOURCE_COLUMNS = [
    "date",
    "ba_code",
    "demand_mwh",
    "demand_forecast_mwh",
    "temp_mean_c",
    "dayofweek",
    "is_weekend",
    "month",
    "is_holiday",
    "holiday_name",
]

ID_COLUMNS = ["ba_code"]
BASE_NUMERIC_FEATURES = (
    [f"demand_lag_{lag}" for lag in LAGS]
    + [f"demand_roll_mean_{window}" for window in ROLLING_WINDOWS]
    + [f"demand_roll_std_{window}" for window in ROLLING_WINDOWS]
    + ["dayofweek", "is_weekend", "month", "is_holiday"]
)
# demand_forecast_mwh is deliberately NOT a model input feature, even though
# it's a strong predictor and present in every training row: under this
# project's ingest design (see ingest_eia.py), EIA's day-ahead forecast for
# a not-yet-happened date is never actually available at real serving time
# (batch_predict.py's stub row can't populate it) - training on it anyway is
# training/serving skew, and a model trained with it silently produces
# garbage predictions the moment it's missing (found via a real end-to-end
# smoke test: PJM's live forecast came out ~4x too low). It's kept as an
# evaluation *benchmark* in evaluate.py instead - a genuine "did our model
# (with no privileged information) beat EIA's own forecast" comparison.
#
# temp_mean_c kept optional (same pattern as the old project's sell_price/
# snap_flag) - batch_predict.py's stub row fills it via persistence
# (yesterday's actual) rather than leaving it NaN, since the model always
# sees it populated in training and has no learned behavior for missing it.
OPTIONAL_NUMERIC_FEATURES = ["temp_mean_c", "heating_degree_days", "cooling_degree_days"]
# holiday_name gives the model finer-grained signal than is_holiday alone -
# July 4th and Thanksgiving have very different demand shapes, not just
# "holiday vs. not."
CATEGORICAL_FEATURES = ID_COLUMNS + ["holiday_name"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add lag, rolling, and degree-day features to a long-format demand frame.

    Rows without enough history for a given lag/rolling window get NaN in
    that column (the caller is expected to drop or impute before training).
    """
    df = df.sort_values(ID_COLUMNS + ["date"]).reset_index(drop=True)

    for lag in LAGS:
        df[f"demand_lag_{lag}"] = df.groupby(ID_COLUMNS)["demand_mwh"].shift(lag)

    shifted = df.groupby(ID_COLUMNS)["demand_mwh"].shift(1)
    grouped_shifted = shifted.groupby(df["ba_code"])
    for window in ROLLING_WINDOWS:
        df[f"demand_roll_mean_{window}"] = grouped_shifted.transform(
            lambda s: s.rolling(window, min_periods=1).mean()
        )
        # Volatility, not just level: two BAs can share a rolling mean while
        # one is steady and the other is spiky - min_periods=2 since std of a
        # single point is undefined (NaN), same as any other
        # not-enough-history feature (dropped/imputed by the caller).
        df[f"demand_roll_std_{window}"] = grouped_shifted.transform(
            lambda s: s.rolling(window, min_periods=2).std()
        )

    if "temp_mean_c" in df.columns:
        df["heating_degree_days"] = (DEGREE_DAY_BASE_C - df["temp_mean_c"]).clip(lower=0)
        df["cooling_degree_days"] = (df["temp_mean_c"] - DEGREE_DAY_BASE_C).clip(lower=0)

    if "holiday_name" in df.columns:
        # holiday_name is null on the ~99% of days with no holiday - callers
        # (run_training, in particular) drop any row with a null feature
        # value, so leaving real nulls here would silently discard almost
        # the entire dataset once this became a feature column. "none" is
        # an explicit no-holiday category instead.
        df["holiday_name"] = df["holiday_name"].fillna("none")

    return df


def feature_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Return (all_feature_columns, categorical_feature_columns) present in `df`."""
    numeric = [c for c in BASE_NUMERIC_FEATURES if c in df.columns]
    numeric += [c for c in OPTIONAL_NUMERIC_FEATURES if c in df.columns]
    categorical = [c for c in CATEGORICAL_FEATURES if c in df.columns]
    return numeric + categorical, categorical
