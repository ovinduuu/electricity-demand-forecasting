"""Decide whether to kick off a new training pipeline run, based on the
latest drift-check results and/or the latest recorded evaluation metric, and
submit one via submit_pipeline.py if so.

Meant to run as a scheduled Cloud Run Job right after drift_check.py (see
infra/terraform), reading both from BigQuery's model_monitoring table.

Usage:
    uv run python -m electricity_demand.monitoring.retrain_trigger \\
        --project-id my-project \\
        --pipeline-root gs://my-project-electricity-demand-raw/pipeline-root \\
        --serving-container-image-uri \\
        us-central1-docker.pkg.dev/my-project/electricity-demand/serving:latest \\
        --serving-model-gcs-path gs://my-project-electricity-demand-raw/models/lightgbm_model.txt
"""

import argparse

import pandas as pd

from electricity_demand.pipelines.submit_pipeline import (
    DEFAULT_MAPE_THRESHOLD,
    build_parameter_values,
    check_pipeline_image_is_real,
    compile_pipeline,
    submit_pipeline_job,
)

DEFAULT_MIN_DRIFTED_FEATURES = 1


def should_retrain_from_drift(
    drift_results: pd.DataFrame, min_drifted_features: int = DEFAULT_MIN_DRIFTED_FEATURES
) -> bool:
    """True if at least `min_drifted_features` features were flagged as drifted."""
    if drift_results.empty or "drifted" not in drift_results.columns:
        return False
    return int(drift_results["drifted"].sum()) >= min_drifted_features


def should_retrain_from_metrics(
    latest_mape: float | None, threshold: float = DEFAULT_MAPE_THRESHOLD
) -> bool:
    """True if the last recorded mean per-BA MAPE is known and exceeds `threshold`."""
    if latest_mape is None:
        return False
    return latest_mape > threshold


def should_retrain(
    drift_results: pd.DataFrame,
    latest_mape: float | None,
    min_drifted_features: int = DEFAULT_MIN_DRIFTED_FEATURES,
    mape_threshold: float = DEFAULT_MAPE_THRESHOLD,
) -> bool:
    """Retrain if either drift was detected or the latest model's mean per-BA MAPE regressed."""
    return should_retrain_from_drift(
        drift_results, min_drifted_features
    ) or should_retrain_from_metrics(latest_mape, mape_threshold)


def _load_latest_drift_results(project_id: str, dataset: str, table: str) -> pd.DataFrame:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    query = (
        f"SELECT feature, psi, drifted FROM `{dataset}.{table}` "
        "WHERE checked_at = (SELECT MAX(checked_at) FROM `" + f"{dataset}.{table}`)"
    )
    return client.query(query).to_dataframe()


def _load_latest_mape(project_id: str, dataset: str, table: str) -> float | None:
    from google.cloud import bigquery
    from google.cloud.exceptions import NotFound

    client = bigquery.Client(project=project_id)
    query = f"SELECT mape_per_ba_mean FROM `{dataset}.{table}` ORDER BY trained_at DESC LIMIT 1"
    try:
        rows = list(client.query(query).result())
    except NotFound:
        return None
    return float(rows[0]["mape_per_ba_mean"]) if rows else None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--pipeline-root", required=True)
    parser.add_argument("--serving-container-image-uri", required=True)
    parser.add_argument("--serving-model-gcs-path", required=True)
    parser.add_argument("--monitoring-dataset", default="electricity_demand_marts")
    parser.add_argument("--drift-table", default="model_monitoring")
    parser.add_argument("--runs-table", default="model_runs")
    parser.add_argument("--min-drifted-features", type=int, default=DEFAULT_MIN_DRIFTED_FEATURES)
    parser.add_argument("--mape-threshold", type=float, default=DEFAULT_MAPE_THRESHOLD)
    parser.add_argument("--bq-location", default="US")
    parser.add_argument("--valid-days", type=int, default=28)
    parser.add_argument("--model-display-name", default="electricity-demand-lightgbm")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--compiled-path", default="artifacts/training_pipeline.yaml")
    parser.add_argument(
        "--service-account",
        default=None,
        help="Defaults to electricity-demand-pipeline@<project-id>.iam.gserviceaccount.com.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Submit a training run unconditionally, skipping the drift/MAPE "
            "gate. Used for daily scheduled retraining, where the point is a "
            "fresh model every day rather than only reacting to regressions."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not args.force:
        drift_results = _load_latest_drift_results(
            args.project_id, args.monitoring_dataset, args.drift_table
        )
        latest_mape = _load_latest_mape(args.project_id, args.monitoring_dataset, args.runs_table)
        if not should_retrain(
            drift_results, latest_mape, args.min_drifted_features, args.mape_threshold
        ):
            print("No retrain trigger: no significant drift and no metric regression.")
            return

    check_pipeline_image_is_real()
    compiled_path = compile_pipeline(args.compiled_path)
    parameter_values = build_parameter_values(args)
    job = submit_pipeline_job(
        compiled_path,
        parameter_values,
        project_id=args.project_id,
        region=args.region,
        pipeline_root=args.pipeline_root,
        service_account=args.service_account,
    )
    print(f"Retrain triggered: {job.resource_name}")


if __name__ == "__main__":
    main()
