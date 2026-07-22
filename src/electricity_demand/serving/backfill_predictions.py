"""Backfill one-step-ahead predictions for the last N days, so
fct_prediction_accuracy has real accuracy history immediately instead of
waiting N days for it to accumulate day by day as batch_predict.py runs.

Reuses batch_predict's feature-building - for each of the last `--days`
dates (which already have real actuals in fct_demand), slices the loaded
history to strictly before that date and predicts it, exactly as if
batch_predict.py had run on that day. This is a real backtest against real
prior history and the currently-trained model - not fabricated data -
though it does use today's model rather than whatever model existed on each
historical day (no daily model snapshots are kept), a reasonable
simplification for filling in accuracy history.

One-off script, not part of the scheduled daily loop (see infra/terraform
for that) - run manually:
    uv run python -m electricity_demand.serving.backfill_predictions \\
        --project-id my-project --model-path gs://.../lightgbm_model.txt
"""

import argparse
import datetime as dt

import numpy as np
import pandas as pd

from electricity_demand.models.features import RAW_SOURCE_COLUMNS, build_features, feature_columns
from electricity_demand.serving.batch_predict import resolve_model_path

DEFAULT_BACKFILL_DAYS = 90
DEFAULT_LOOKBACK_DAYS = 60


def backfill_targets(latest_actual_date: dt.date, backfill_days: int) -> list[dt.date]:
    """The last `backfill_days` dates up to and including `latest_actual_date`,
    oldest first."""
    return [latest_actual_date - dt.timedelta(days=i) for i in range(backfill_days - 1, -1, -1)]


def run_backfill(history: pd.DataFrame, targets: list[dt.date], model) -> pd.DataFrame:
    """Predict each date in `targets`, using only prior-day data for that
    date's features.

    Every target date already has real data in `history` (this is a
    backtest, not a live forecast of an unknown day) - build_features()'s
    lag/rolling columns are shift-based (backward-only, see its docstring),
    so featuring the whole history once and then selecting each target
    date's row is equivalent to, but far cheaper than, rebuilding features
    from scratch per target date.
    """
    featured = build_features(history)
    features, categorical = feature_columns(featured)
    for col in categorical:
        featured[col] = featured[col].astype("category")

    target_dates = pd.to_datetime(pd.Series(targets, dtype="object")).dt.normalize()
    target_rows = featured[featured["date"].isin(target_dates)].copy()
    if target_rows.empty:
        return pd.DataFrame(columns=["date", "ba_code", "predicted_demand_mwh"])

    preds = model.predict(target_rows[features])
    return target_rows[["date", "ba_code"]].assign(predicted_demand_mwh=np.clip(preds, 0, None))


def _latest_actual_date(project_id: str, dataset: str, table: str) -> dt.date:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    row = list(client.query(f"SELECT MAX(date) AS max_date FROM `{dataset}.{table}`").result())[0]
    return row["max_date"]


def _load_window(
    project_id: str, dataset: str, table: str, start_date: dt.date, end_date: dt.date
) -> pd.DataFrame:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    columns = ", ".join(RAW_SOURCE_COLUMNS)
    query = (
        f"SELECT {columns} FROM `{dataset}.{table}` "
        f"WHERE date BETWEEN '{start_date}' AND '{end_date}' "
        "ORDER BY ba_code, date"
    )
    result = client.query(query).to_dataframe()
    result["date"] = pd.to_datetime(result["date"])
    return result


def _delete_existing_predictions(
    project_id: str, dataset: str, table: str, start_date: dt.date, end_date: dt.date
) -> None:
    """Idempotency: safe to re-run without duplicating rows for the same
    target range."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    client.query(
        f"DELETE FROM `{dataset}.{table}` WHERE date BETWEEN '{start_date}' AND '{end_date}'"
    ).result()


def _write_predictions(
    project_id: str, dataset: str, table: str, predictions: pd.DataFrame
) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND)
    job = client.load_table_from_dataframe(predictions, table_id, job_config=job_config)
    job.result()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--source-dataset", default="electricity_demand_marts")
    parser.add_argument("--source-table", default="fct_demand")
    parser.add_argument("--predictions-dataset", default="electricity_demand_marts")
    parser.add_argument("--predictions-table", default="fct_demand_predictions")
    parser.add_argument("--days", type=int, default=DEFAULT_BACKFILL_DAYS)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    return parser.parse_args()


def main() -> None:
    import lightgbm as lgb

    args = _parse_args()
    latest_actual_date = _latest_actual_date(
        args.project_id, args.source_dataset, args.source_table
    )
    targets = backfill_targets(latest_actual_date, args.days)
    window_start = targets[0] - dt.timedelta(days=args.lookback_days)

    history = _load_window(
        args.project_id, args.source_dataset, args.source_table, window_start, latest_actual_date
    )
    model = lgb.Booster(model_file=resolve_model_path(args.model_path))
    predictions = run_backfill(history, targets, model)

    if predictions.empty:
        print("No predictions generated - not enough history.")
        return

    _delete_existing_predictions(
        args.project_id, args.predictions_dataset, args.predictions_table, targets[0], targets[-1]
    )
    _write_predictions(
        args.project_id, args.predictions_dataset, args.predictions_table, predictions
    )
    print(f"Wrote {len(predictions)} predictions for {targets[0]} .. {targets[-1]}")


if __name__ == "__main__":
    main()
