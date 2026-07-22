"""FastAPI serving app.

Two roles:

1. Vertex AI's custom-container prediction protocol (GET /health, POST
   /predict with {"instances": [...]} -> {"predictions": [...]}) - the
   `serving_container_image_uri` register_model needs, and the image for
   the optional Cloud Run live-request demo (see infra/terraform).
2. A small read/forecast API (GET /series, GET /history/{ba_code},
   GET /forecast/{ba_code}, GET /accuracy, GET /accuracy/{ba_code}) for the
   Next.js frontend (frontend/) - lists tracked balancing authorities,
   returns recent history, a one-step-ahead forecast, and model accuracy
   (predicted vs. actual, once batch_predict.py's predictions have a
   matching actual - see dbt's fct_prediction_accuracy/
   agg_prediction_accuracy_daily marts).

Data source for (2) is BigQuery's fct_demand mart by default (set
GCP_PROJECT_ID). For local development without GCP credentials, set
LOCAL_DATA_CSV to a wide-format CSV (date, ba_code, demand_mwh, ...) instead.

Usage:
    MODEL_PATH=artifacts/lightgbm_model.txt GCP_PROJECT_ID=my-project \\
        uv run uvicorn electricity_demand.serving.app:app --host 0.0.0.0 --port 8080
"""

import os
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from electricity_demand.data_engineering.balancing_authorities import BALANCING_AUTHORITIES
from electricity_demand.serving.batch_predict import predict_next_day

DEFAULT_MODEL_PATH = "artifacts/lightgbm_model.txt"
DEFAULT_HISTORY_DAYS = 90
RECENT_ACCURACY_DAYS = 90
CATEGORICAL_COLUMNS = ["ba_code", "holiday_name"]

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")

app = FastAPI(title="electricity-demand-serving")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allowed_origins == "*" else _allowed_origins.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_model_cache: dict[str, Any] = {}


def get_model() -> Any:
    """Load (and cache) the LightGBM booster at the path in MODEL_PATH.

    MODEL_PATH may be a gs:// URI (downloaded first via batch_predict.py's
    resolve_model_path) - the fixed path register_model publishes to.
    Cached by resolved path rather than as a single global, so tests can
    point MODEL_PATH at a fresh temp model without cross-test pollution.
    """
    import lightgbm as lgb

    from electricity_demand.serving.batch_predict import resolve_model_path

    model_path = os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH)
    if model_path not in _model_cache:
        _model_cache[model_path] = lgb.Booster(model_file=resolve_model_path(model_path))
    return _model_cache[model_path]


def _bigquery_client_and_table():
    from google.cloud import bigquery

    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])
    dataset = os.environ.get("BQ_DATASET_MARTS", "electricity_demand_marts")
    table = os.environ.get("BQ_TABLE_DEMAND", "fct_demand")
    return client, f"{dataset}.{table}"


def _list_series() -> list[dict]:
    """The fixed set of tracked balancing authorities (see
    balancing_authorities.py) - unlike the old retail project's item
    catalog, BAs don't go dormant, so there's no "recent activity" filter
    needed, just the static list.
    """
    return [{"ba_code": ba.ba_code, "ba_name": ba.ba_name} for ba in BALANCING_AUTHORITIES]


def _query_series_history(ba_code: str) -> pd.DataFrame:
    """Full raw feature-source columns (see features.RAW_SOURCE_COLUMNS) for
    exactly one balancing authority.

    Must select the same columns queries.build_extract_query() uses for
    training, or predict_next_day's build_features() silently produces fewer
    feature columns than the model was trained on and LightGBM errors out.
    """
    local_csv = os.environ.get("LOCAL_DATA_CSV")
    if local_csv:
        history = pd.read_csv(local_csv, parse_dates=["date"])
        series = history[history.ba_code == ba_code]
        return series.sort_values("date")

    from google.cloud import bigquery

    from electricity_demand.models.features import RAW_SOURCE_COLUMNS

    client, table = _bigquery_client_and_table()
    columns = ", ".join(RAW_SOURCE_COLUMNS)
    query = f"SELECT {columns} FROM `{table}` WHERE ba_code = @ba_code ORDER BY date"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("ba_code", "STRING", ba_code)]
    )
    result = client.query(query, job_config=job_config).to_dataframe()
    # BigQuery's client returns DATE columns as plain datetime.date objects,
    # not pandas Timestamps (unlike the LOCAL_DATA_CSV/pd.read_csv path) -
    # normalize here so every downstream consumer sees the same dtype
    # regardless of which data source this came from.
    result["date"] = pd.to_datetime(result["date"])
    return result


def _local_prediction_accuracy() -> pd.DataFrame:
    """Predictions joined to actuals, computed in pandas from LOCAL_DATA_CSV
    + LOCAL_PREDICTIONS_CSV - mirrors dbt's fct_prediction_accuracy model so
    /accuracy* stay unit-testable without BigQuery.
    """
    history = pd.read_csv(os.environ["LOCAL_DATA_CSV"], parse_dates=["date"])
    predictions = pd.read_csv(os.environ["LOCAL_PREDICTIONS_CSV"], parse_dates=["date"])
    merged = predictions.merge(
        history[["date", "ba_code", "demand_mwh"]],
        on=["date", "ba_code"],
        how="inner",
    ).rename(columns={"demand_mwh": "actual_demand_mwh"})
    merged["abs_error"] = (merged["predicted_demand_mwh"] - merged["actual_demand_mwh"]).abs()
    merged["pct_error"] = merged.apply(
        lambda r: r["abs_error"] / r["actual_demand_mwh"] if r["actual_demand_mwh"] > 0 else None,
        axis=1,
    )
    return merged


def _query_accuracy_daily() -> pd.DataFrame:
    """Daily MAE/MAPE/RMSE, from BigQuery's agg_prediction_accuracy_daily
    mart (or computed locally in dev mode).
    """
    if os.environ.get("LOCAL_PREDICTIONS_CSV"):
        accuracy = _local_prediction_accuracy()
        return (
            accuracy.groupby("date")
            .agg(
                n_predictions=("abs_error", "count"),
                mae=("abs_error", "mean"),
                mape=("pct_error", "mean"),
                rmse=("abs_error", lambda s: float((s**2).mean() ** 0.5)),
            )
            .reset_index()
            .sort_values("date")
        )

    from google.cloud import bigquery

    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])
    dataset = os.environ.get("BQ_DATASET_MARTS", "electricity_demand_marts")
    query = (
        "SELECT date, n_predictions, mae, mape, rmse "
        f"FROM `{dataset}.agg_prediction_accuracy_daily` ORDER BY date"
    )
    result = client.query(query).to_dataframe()
    result["date"] = pd.to_datetime(result["date"])
    return result


def _query_series_accuracy(ba_code: str) -> pd.DataFrame:
    """Predicted-vs-actual points for one BA over the last
    RECENT_ACCURACY_DAYS days, from BigQuery's fct_prediction_accuracy mart
    (or computed locally in dev mode) - capped so this stays a "recent
    comparison" endpoint rather than growing unbounded as accuracy history
    accumulates daily.
    """
    if os.environ.get("LOCAL_PREDICTIONS_CSV"):
        accuracy = _local_prediction_accuracy()
        if not accuracy.empty:
            recent_start = accuracy["date"].max() - pd.Timedelta(days=RECENT_ACCURACY_DAYS)
            accuracy = accuracy[accuracy["date"] > recent_start]
        series = accuracy[accuracy.ba_code == ba_code]
        return series.sort_values("date")

    from google.cloud import bigquery

    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])
    dataset = os.environ.get("BQ_DATASET_MARTS", "electricity_demand_marts")
    query = (
        "SELECT date, predicted_demand_mwh, actual_demand_mwh "
        f"FROM `{dataset}.fct_prediction_accuracy` "
        "WHERE ba_code = @ba_code "
        f"AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL {RECENT_ACCURACY_DAYS} DAY) "
        "ORDER BY date"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("ba_code", "STRING", ba_code)]
    )
    result = client.query(query, job_config=job_config).to_dataframe()
    result["date"] = pd.to_datetime(result["date"])
    return result


def _query_latest_model_run() -> dict | None:
    """Most recent training run's metrics, from BigQuery's model_runs table
    (written by pipelines/components.py::train_model) - lets the frontend
    show which model is currently live and when it last retrained, instead
    of retraining being an invisible backend-only event.
    """
    local_json = os.environ.get("LOCAL_MODEL_RUN_JSON")
    if local_json:
        import json

        with open(local_json) as f:
            return json.load(f)

    from google.cloud import bigquery

    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])
    dataset = os.environ.get("BQ_DATASET_MARTS", "electricity_demand_marts")
    query = (
        "SELECT trained_at, mape_per_ba_mean, mape, rmse, eia_day_ahead_mape, n_train_rows "
        f"FROM `{dataset}.model_runs` ORDER BY trained_at DESC LIMIT 1"
    )
    rows = list(client.query(query).result())
    if not rows:
        return None
    row = rows[0]
    trained_at = row.trained_at
    trained_at_str = trained_at.isoformat() if hasattr(trained_at, "isoformat") else str(trained_at)
    return {
        "trained_at": trained_at_str,
        "mape_per_ba_mean": float(row.mape_per_ba_mean),
        "mape": float(row.mape),
        "rmse": float(row.rmse),
        "eia_day_ahead_mape": float(row.eia_day_ahead_mape),
        "n_train_rows": int(row.n_train_rows),
    }


class SeriesInfo(BaseModel):
    ba_code: str
    ba_name: str


class HistoryPoint(BaseModel):
    date: str
    demand_mwh: float


class ForecastPoint(BaseModel):
    date: str
    predicted_demand_mwh: float


class PredictRequest(BaseModel):
    instances: list[dict[str, Any]]


class PredictResponse(BaseModel):
    predictions: list[float]


class AccuracyDailyPoint(BaseModel):
    date: str
    n_predictions: int
    mae: float
    mape: float | None
    rmse: float


class SeriesAccuracyPoint(BaseModel):
    date: str
    predicted_demand_mwh: float
    actual_demand_mwh: float


class ModelInfo(BaseModel):
    trained_at: str
    mape_per_ba_mean: float
    mape: float
    rmse: float
    eia_day_ahead_mape: float
    n_train_rows: int


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/model-info", response_model=ModelInfo | None)
def get_model_info() -> ModelInfo | None:
    info = _query_latest_model_run()
    return ModelInfo(**info) if info else None


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    df = pd.DataFrame(request.instances)
    for col in CATEGORICAL_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype("category")

    model = get_model()
    feature_names = model.feature_name()
    preds = model.predict(df[feature_names])
    predictions = [max(0.0, float(p)) for p in preds]
    return PredictResponse(predictions=predictions)


@app.get("/series", response_model=list[SeriesInfo])
def list_series() -> list[SeriesInfo]:
    return [SeriesInfo(**s) for s in _list_series()]


@app.get("/history/{ba_code}", response_model=list[HistoryPoint])
def get_history(ba_code: str, days: int = DEFAULT_HISTORY_DAYS) -> list[HistoryPoint]:
    series = _query_series_history(ba_code)
    if series.empty:
        raise HTTPException(status_code=404, detail="Unknown ba_code")

    series = series.tail(days)
    return [
        HistoryPoint(date=row.date.date().isoformat(), demand_mwh=float(row.demand_mwh))
        for row in series.itertuples()
    ]


@app.get("/forecast/{ba_code}", response_model=ForecastPoint)
def get_forecast(ba_code: str) -> ForecastPoint:
    series = _query_series_history(ba_code)
    if series.empty:
        raise HTTPException(status_code=404, detail="Unknown ba_code")

    model = get_model()
    prediction = predict_next_day(series, model)
    row = prediction.iloc[0]
    return ForecastPoint(
        date=row.date.date().isoformat(), predicted_demand_mwh=float(row.predicted_demand_mwh)
    )


@app.get("/accuracy", response_model=list[AccuracyDailyPoint])
def get_accuracy_daily() -> list[AccuracyDailyPoint]:
    daily = _query_accuracy_daily()
    return [
        AccuracyDailyPoint(
            date=row.date.date().isoformat(),
            n_predictions=int(row.n_predictions),
            mae=float(row.mae),
            mape=float(row.mape) if pd.notna(row.mape) else None,
            rmse=float(row.rmse),
        )
        for row in daily.itertuples()
    ]


@app.get("/accuracy/{ba_code}", response_model=list[SeriesAccuracyPoint])
def get_series_accuracy(ba_code: str) -> list[SeriesAccuracyPoint]:
    series = _query_series_accuracy(ba_code)
    return [
        SeriesAccuracyPoint(
            date=row.date.date().isoformat(),
            predicted_demand_mwh=float(row.predicted_demand_mwh),
            actual_demand_mwh=float(row.actual_demand_mwh),
        )
        for row in series.itertuples()
    ]
