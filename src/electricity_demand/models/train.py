"""Train a LightGBM model to forecast daily electricity demand (MWh) by
balancing authority.

Reads a wide-format CSV (date, ba_code, demand_mwh, + optional
demand_forecast_mwh/temp_mean_c/calendar columns matching `fct_demand`),
builds features (see features.py), holds out the most recent `--valid-days`
as a time-based validation window, trains, evaluates (MAPE/RMSE pooled and
per-BA, plus EIA's own day-ahead forecast as a benchmark - see evaluate.py),
and writes the model + a run-metrics record.

Usage:
    uv run python -m electricity_demand.models.train --data data/raw/fct_demand.csv
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from electricity_demand.models.evaluate import evaluate_eia_day_ahead_forecast, evaluate_predictions
from electricity_demand.models.features import ID_COLUMNS, build_features, feature_columns

DEFAULT_VALID_DAYS = 28

DEFAULT_LGB_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 20,
    "verbosity": -1,
}


def time_based_split(
    df: pd.DataFrame, valid_days: int = DEFAULT_VALID_DAYS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out the most recent `valid_days` as validation, everything else as train."""
    cutoff = df["date"].max() - pd.Timedelta(days=valid_days)
    train = df[df["date"] <= cutoff]
    valid = df[df["date"] > cutoff]
    return train, valid


def cast_categoricals(
    train_df: pd.DataFrame, valid_df: pd.DataFrame, categorical_features: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cast categorical feature columns on train/valid to the same dtype + category set.

    Returns new frames the caller should reuse for *both* training and
    prediction — LightGBM requires the categories seen at predict time to
    match training exactly, so this must not be redone independently on
    each side.
    """
    train_df = train_df.copy()
    valid_df = valid_df.copy()
    for col in categorical_features:
        train_df[col] = train_df[col].astype("category")
        valid_df[col] = valid_df[col].astype(
            pd.CategoricalDtype(categories=train_df[col].cat.categories)
        )
    return train_df, valid_df


def train_lightgbm(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    features: list[str],
    categorical_features: list[str],
    target: str = "demand_mwh",
    params: dict | None = None,
    num_boost_round: int = 500,
):
    """Train on `train_df`/`valid_df` as given — callers must already have run
    `cast_categoricals` on them so training and later prediction agree.
    """
    import lightgbm as lgb

    train_set = lgb.Dataset(
        train_df[features], label=train_df[target], categorical_feature=categorical_features
    )
    valid_set = lgb.Dataset(
        valid_df[features],
        label=valid_df[target],
        categorical_feature=categorical_features,
        reference=train_set,
    )

    model = lgb.train(
        params or DEFAULT_LGB_PARAMS,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)],
    )
    return model


def run_training(
    df: pd.DataFrame, valid_days: int = DEFAULT_VALID_DAYS
) -> tuple[object, dict, pd.DataFrame, list[str]]:
    """Feature-build, split, train, and evaluate. Returns (model, metrics, valid_df, features)."""
    featured = build_features(df)
    features, categorical = feature_columns(featured)

    train_df, valid_df = time_based_split(featured, valid_days)
    train_df = train_df.dropna(subset=features)
    valid_df = valid_df.dropna(subset=features)
    train_df, valid_df = cast_categoricals(train_df, valid_df, categorical)

    model = train_lightgbm(train_df, valid_df, features, categorical)

    preds = model.predict(valid_df[features])
    pred_df = valid_df[["date", *ID_COLUMNS]].assign(demand_mwh=preds.clip(min=0))
    actual_df = valid_df[["date", *ID_COLUMNS, "demand_mwh"]]

    metrics = evaluate_predictions(actual_df, pred_df)
    metrics["best_iteration"] = model.best_iteration
    metrics["n_train_rows"] = len(train_df)
    metrics["n_valid_rows"] = len(valid_df)

    eia_baseline = evaluate_eia_day_ahead_forecast(valid_df)
    metrics["eia_day_ahead_mape"] = eia_baseline["mape"]
    metrics["eia_day_ahead_rmse"] = eia_baseline["rmse"]

    return model, metrics, valid_df, features


def _append_run_log(run_log_path: Path, record: dict) -> None:
    run_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(run_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", required=True, help="Path to a wide-format demand CSV (fct_demand columns)."
    )
    parser.add_argument("--valid-days", type=int, default=DEFAULT_VALID_DAYS)
    parser.add_argument("--model-out", default="artifacts/lightgbm_model.txt")
    parser.add_argument("--run-log", default="artifacts/runs.jsonl")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    df = pd.read_csv(args.data, parse_dates=["date"])

    model, metrics, _, features = run_training(df, args.valid_days)

    model_out = Path(args.model_out)
    model_out.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_out))

    record = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "data": str(args.data),
        "valid_days": args.valid_days,
        "features": features,
        "metrics": metrics,
        "model_out": str(model_out),
    }
    _append_run_log(Path(args.run_log), record)

    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
