"""KFP v2 components for the training pipeline: dbt transform, training-data
extraction from BigQuery, LightGBM training, and conditional registration to
Vertex AI Model Registry.

All four run inside PIPELINE_IMAGE (see ../../../Dockerfile), which bundles
this package (gcp + ml extras) and dbt-bigquery so every step shares one
image instead of juggling several. PIPELINE_IMAGE defaults to a plain public
Python image so the pipeline can still be *compiled* locally without that
custom image existing yet (see tests/test_training_pipeline.py); set the
PIPELINE_IMAGE env var to the real Artifact Registry URI (provisioned by
infra/terraform) before compiling for an actual Vertex AI run.
"""

import os
from typing import NamedTuple

from kfp import dsl

PLACEHOLDER_PIPELINE_IMAGE = "python:3.11-slim"
PIPELINE_IMAGE = os.environ.get("PIPELINE_IMAGE", PLACEHOLDER_PIPELINE_IMAGE)


@dsl.component(base_image=PIPELINE_IMAGE)
def run_dbt_transform(project_id: str, bq_location: str = "US") -> str:
    """Run the dbt project (staging -> marts) against BigQuery.

    One orchestrator, not two: this keeps the dbt transform inside the same
    Vertex AI Pipeline as the ML steps below instead of standing up a
    separate always-on orchestrator (e.g. Cloud Composer) just for this.
    """
    from electricity_demand.data_engineering.dbt_runner import run_dbt

    run_dbt(project_id, bq_location)
    return "ok"


@dsl.component(base_image=PIPELINE_IMAGE)
def extract_training_data(
    project_id: str,
    start_date: str,
    end_date: str,
    training_data: dsl.Output[dsl.Dataset],
    dataset: str = "electricity_demand_marts",
    table: str = "fct_demand",
) -> None:
    """Query fct_demand for [start_date, end_date] and write it out as CSV."""
    from google.cloud import bigquery

    from electricity_demand.pipelines.queries import build_extract_query

    client = bigquery.Client(project=project_id)
    query = build_extract_query(dataset, table, start_date, end_date)
    df = client.query(query).to_dataframe()
    df.to_csv(training_data.path, index=False)


@dsl.component(base_image=PIPELINE_IMAGE)
def train_model(
    training_data: dsl.Input[dsl.Dataset],
    model: dsl.Output[dsl.Model],
    project_id: str,
    valid_days: int = 28,
    monitoring_dataset: str = "electricity_demand_marts",
    runs_table: str = "model_runs",
) -> NamedTuple("Metrics", [("mape_per_ba_mean", float), ("mape", float), ("rmse", float)]):
    """Feature-build + train a LightGBM model on the extracted data, saving it
    to `model` and logging its metrics to BigQuery.

    The BigQuery row is what retrain_trigger.py reads to find the latest
    mape_per_ba_mean (train.py's local JSONL run log isn't reachable from a
    separate scheduled job) and what a monitoring dashboard would plot over
    time.
    """
    import datetime as dt
    from collections import namedtuple

    import pandas as pd
    from google.cloud import bigquery

    from electricity_demand.models.train import run_training

    df = pd.read_csv(training_data.path, parse_dates=["date"])
    trained_model, metrics, _, _ = run_training(df, valid_days=valid_days)
    trained_model.save_model(model.path)

    run_row = pd.DataFrame(
        [
            {
                "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "mape_per_ba_mean": metrics["mape_per_ba_mean"],
                "mape": metrics["mape"],
                "rmse": metrics["rmse"],
                "eia_day_ahead_mape": metrics["eia_day_ahead_mape"],
                "n_train_rows": metrics["n_train_rows"],
                "n_valid_rows": metrics["n_valid_rows"],
            }
        ]
    )
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{monitoring_dataset}.{runs_table}"
    job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND)
    client.load_table_from_dataframe(run_row, table_id, job_config=job_config).result()

    result = namedtuple("Metrics", ["mape_per_ba_mean", "mape", "rmse"])
    return result(metrics["mape_per_ba_mean"], metrics["mape"], metrics["rmse"])


@dsl.component(base_image=PIPELINE_IMAGE)
def register_model(
    model: dsl.Input[dsl.Model],
    project_id: str,
    region: str,
    serving_container_image_uri: str,
    serving_model_gcs_path: str,
    display_name: str = "electricity-demand-lightgbm",
) -> str:
    """Upload the trained model to Vertex AI Model Registry, and copy it to
    a fixed GCS path for serving to consume.

    Vertex's own artifact path (model.uri) is versioned/dynamic per pipeline
    run, which is fine for the registry but not for a simple fixed-path
    reader - src/electricity_demand/serving/batch_predict.py's Cloud Run Job
    always reads from `serving_model_gcs_path`, so this component publishes
    each newly-registered model there too.
    """
    from google.cloud import aiplatform, storage

    aiplatform.init(project=project_id, location=region)
    artifact_dir = model.uri.rsplit("/", 1)[0]

    uploaded = aiplatform.Model.upload(
        display_name=display_name,
        artifact_uri=artifact_dir,
        serving_container_image_uri=serving_container_image_uri,
    )

    storage_client = storage.Client(project=project_id)
    src_bucket_name, _, src_blob_path = model.uri[len("gs://") :].partition("/")
    dst_bucket_name, _, dst_blob_path = serving_model_gcs_path[len("gs://") :].partition("/")
    src_blob = storage_client.bucket(src_bucket_name).blob(src_blob_path)
    dst_blob = storage_client.bucket(dst_bucket_name).blob(dst_blob_path)
    dst_blob.rewrite(src_blob)

    return uploaded.resource_name
