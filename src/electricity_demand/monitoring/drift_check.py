"""Feature drift checks between a reference window (training-time data) and
a current window (recent data), using the Population Stability Index (PSI)
- the standard industry metric for this, not something specific to Vertex
AI's managed Model Monitoring.

Vertex AI Model Monitoring watches request logs on a live Endpoint; this
project's primary serving path is a batch job with no standing Endpoint (see
serving/batch_predict.py), so that managed product doesn't apply here. This
module is the substitute: it runs as a scheduled Cloud Run Job, computes PSI
per numeric feature, and logs the results to BigQuery for a dashboard to
read from.

PSI rule of thumb (standard, not project-specific): < 0.1 no significant
change, 0.1-0.2 moderate shift, > 0.2 significant drift.

Usage:
    uv run python -m electricity_demand.monitoring.drift_check --project-id my-project
"""

import argparse
import datetime as dt

import numpy as np
import pandas as pd

from electricity_demand.models.features import build_features, feature_columns

DEFAULT_PSI_THRESHOLD = 0.2
DEFAULT_REFERENCE_DAYS = 365
DEFAULT_CURRENT_DAYS = 30
EPSILON = 1e-6


def population_stability_index(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """PSI between a reference and current sample of one numeric feature.

    Bin edges come from the reference sample's quantiles, so each reference
    bin holds ~1/bins of the reference data by construction; the current
    sample is then binned against those same edges.
    """
    reference = np.asarray(reference, dtype=float)
    reference = reference[~np.isnan(reference)]
    current = np.asarray(current, dtype=float)
    current = current[~np.isnan(current)]

    if reference.size == 0 or current.size == 0:
        return 0.0

    quantiles = np.linspace(0, 1, bins + 1)
    edges = np.unique(np.quantile(reference, quantiles))
    if edges.size < 3:
        # Reference has too little spread to bin meaningfully.
        return 0.0
    edges[0] = -np.inf
    edges[-1] = np.inf

    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)

    ref_pct = ref_counts / ref_counts.sum() + EPSILON
    cur_pct = cur_counts / cur_counts.sum() + EPSILON

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def check_feature_drift(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    feature_cols: list[str],
    bins: int = 10,
    threshold: float = DEFAULT_PSI_THRESHOLD,
) -> pd.DataFrame:
    """PSI per numeric feature in `feature_cols`, flagged against `threshold`.

    Categorical features (ba_code, holiday_name) are skipped - PSI is a
    numeric-distribution metric; checking categorical drift would need a
    different test (e.g. chi-square on category frequencies), not
    implemented here.
    """
    rows = []
    for col in feature_cols:
        if col not in reference_df.columns or not pd.api.types.is_numeric_dtype(reference_df[col]):
            continue
        psi = population_stability_index(
            reference_df[col].to_numpy(), current_df[col].to_numpy(), bins=bins
        )
        rows.append({"feature": col, "psi": psi, "drifted": psi > threshold})
    return pd.DataFrame(rows, columns=["feature", "psi", "drifted"])


def _load_fct_demand_window(
    project_id: str, dataset: str, table: str, start_date: str, end_date: str
) -> pd.DataFrame:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    query = (
        "SELECT date, ba_code, demand_mwh, temp_mean_c, dayofweek, is_weekend, "
        "month, is_holiday, holiday_name "
        f"FROM `{dataset}.{table}` "
        f"WHERE date BETWEEN '{start_date}' AND '{end_date}' "
        "ORDER BY ba_code, date"
    )
    return client.query(query).to_dataframe()


def _write_drift_results_to_bigquery(
    project_id: str, dataset: str, table: str, results: pd.DataFrame, checked_at: str
) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    to_write = results.assign(checked_at=checked_at)
    job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND)
    job = client.load_table_from_dataframe(to_write, table_id, job_config=job_config)
    job.result()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-dataset", default="electricity_demand_marts")
    parser.add_argument("--source-table", default="fct_demand")
    parser.add_argument("--monitoring-dataset", default="electricity_demand_marts")
    parser.add_argument("--monitoring-table", default="model_monitoring")
    parser.add_argument("--reference-days", type=int, default=DEFAULT_REFERENCE_DAYS)
    parser.add_argument("--current-days", type=int, default=DEFAULT_CURRENT_DAYS)
    parser.add_argument("--psi-threshold", type=float, default=DEFAULT_PSI_THRESHOLD)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    today = dt.datetime.now(dt.timezone.utc).date()
    current_start = today - dt.timedelta(days=args.current_days)
    reference_start = current_start - dt.timedelta(days=args.reference_days)

    reference_raw = _load_fct_demand_window(
        args.project_id,
        args.source_dataset,
        args.source_table,
        reference_start.isoformat(),
        current_start.isoformat(),
    )
    current_raw = _load_fct_demand_window(
        args.project_id,
        args.source_dataset,
        args.source_table,
        current_start.isoformat(),
        today.isoformat(),
    )

    reference_features = build_features(reference_raw)
    current_features = build_features(current_raw)
    feature_cols, _ = feature_columns(reference_features)

    results = check_feature_drift(
        reference_features, current_features, feature_cols, threshold=args.psi_threshold
    )
    _write_drift_results_to_bigquery(
        args.project_id,
        args.monitoring_dataset,
        args.monitoring_table,
        results,
        checked_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    print(results.to_string(index=False))


if __name__ == "__main__":
    main()
