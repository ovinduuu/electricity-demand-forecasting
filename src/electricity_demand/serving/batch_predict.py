"""One-step-ahead batch scoring: pulls recent history from BigQuery's
fct_demand mart, forecasts tomorrow's demand for every balancing authority,
and writes the results to a predictions table.

This is the project's primary serving path - a scheduled script (Cloud
Scheduler -> Cloud Run Job, see infra/terraform) is far cheaper than
standing up a Vertex AI Batch Prediction job with a custom serving
container, and matches how grid demand forecasts actually get used (a daily
refresh, not per-request). app.py's FastAPI service is the alternative/
optional live-request path.

--model-path accepts either a local path or a gs:// URI (downloaded to a
temp file first) - the latter is what the Cloud Run Job in infra/terraform
uses, since it's simpler and more portable than relying on a GCS FUSE volume
mount.

Usage:
    uv run python -m electricity_demand.serving.batch_predict \\
        --project-id my-project --model-path artifacts/lightgbm_model.txt
"""

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from electricity_demand.data_engineering.build_seeds import build_calendar_dates
from electricity_demand.models.features import build_features, feature_columns

# Comfortably covers the largest lag/rolling window (28 days) plus margin.
DEFAULT_LOOKBACK_DAYS = 60


def build_next_day_frame(history: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Append one stub next-day row per BA (demand_mwh=NaN).

    Calendar columns (dayofweek/is_weekend/month/is_holiday/holiday_name)
    are fully knowable in advance, so they're filled in for real via
    build_calendar_dates rather than left NaN. temp_mean_c uses persistence
    (each BA's last known actual) as a naive next-day estimate - the model
    always sees this column populated in training (see features.py), so an
    actual live weather-forecast fetch would be more accurate but isn't
    required; leaving it NaN, on the other hand, produces badly wrong
    predictions (found via a real end-to-end smoke test - the model has no
    learned behavior for a feature it never saw missing during training).
    demand_forecast_mwh is not a model feature at all (see features.py) so
    it's left as whatever the concat naturally produces (NaN).
    """
    as_of = history["date"].max()
    next_day = as_of + pd.Timedelta(days=1)
    calendar_row = build_calendar_dates(next_day.date(), next_day.date())

    stub_rows = history[["ba_code"]].drop_duplicates().assign(date=next_day, demand_mwh=np.nan)
    if "temp_mean_c" in history.columns:
        last_temp = history.sort_values("date").groupby("ba_code")["temp_mean_c"].last()
        stub_rows["temp_mean_c"] = stub_rows["ba_code"].map(last_temp)
    for col in ["dayofweek", "is_weekend", "month", "is_holiday", "holiday_name"]:
        stub_rows[col] = calendar_row[col].iloc[0]

    augmented = pd.concat([history, stub_rows], ignore_index=True)
    return augmented, next_day


def predict_next_day(history: pd.DataFrame, model) -> pd.DataFrame:
    """One-step-ahead forecast for every BA present in `history`."""
    augmented, next_day = build_next_day_frame(history)
    featured = build_features(augmented)
    features, categorical = feature_columns(featured)

    target_rows = featured[featured["date"] == next_day].copy()
    for col in categorical:
        target_rows[col] = target_rows[col].astype("category")

    preds = model.predict(target_rows[features])
    return target_rows[["date", "ba_code"]].assign(predicted_demand_mwh=np.clip(preds, 0, None))


def _load_history_from_bigquery(
    project_id: str, dataset: str, table: str, lookback_days: int
) -> pd.DataFrame:
    """Must select the same columns as pipelines/queries.py's
    build_extract_query() (see features.RAW_SOURCE_COLUMNS) - otherwise
    build_features() produces fewer feature columns here than the model was
    trained on, and LightGBM errors out on the mismatch at predict time.
    """
    from google.cloud import bigquery

    from electricity_demand.models.features import RAW_SOURCE_COLUMNS

    client = bigquery.Client(project=project_id)
    columns = ", ".join(RAW_SOURCE_COLUMNS)
    query = (
        f"SELECT {columns} "
        f"FROM `{dataset}.{table}` "
        f"WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY) "
        "ORDER BY ba_code, date"
    )
    return client.query(query).to_dataframe()


def _write_predictions_to_bigquery(
    project_id: str, dataset: str, table: str, predictions: pd.DataFrame
) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND)
    job = client.load_table_from_dataframe(predictions, table_id, job_config=job_config)
    job.result()


def resolve_model_path(model_path: str) -> str:
    """Return a local path to the model file, downloading it first if `model_path`
    is a gs:// URI."""
    if not model_path.startswith("gs://"):
        return model_path

    from google.cloud import storage

    bucket_name, _, blob_path = model_path[len("gs://") :].partition("/")
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_path)

    local_path = Path(tempfile.gettempdir()) / "lightgbm_model.txt"
    blob.download_to_filename(str(local_path))
    return str(local_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--source-dataset", default="electricity_demand_marts")
    parser.add_argument("--source-table", default="fct_demand")
    parser.add_argument("--predictions-dataset", default="electricity_demand_marts")
    parser.add_argument("--predictions-table", default="fct_demand_predictions")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    return parser.parse_args()


def main() -> None:
    import lightgbm as lgb

    args = _parse_args()
    history = _load_history_from_bigquery(
        args.project_id, args.source_dataset, args.source_table, args.lookback_days
    )
    model = lgb.Booster(model_file=resolve_model_path(args.model_path))
    predictions = predict_next_day(history, model)
    _write_predictions_to_bigquery(
        args.project_id, args.predictions_dataset, args.predictions_table, predictions
    )
    print(f"Wrote {len(predictions)} predictions for {predictions['date'].iloc[0]}")


if __name__ == "__main__":
    main()
