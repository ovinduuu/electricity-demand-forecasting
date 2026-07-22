"""Shared MERGE-into-BigQuery helper for the ingest jobs (ingest_eia.py,
ingest_weather.py) - both need the same "load new rows into a staging table,
then MERGE on a key" upsert, just against different tables/keys.
"""

from __future__ import annotations

import pandas as pd


def merge_into_bigquery(
    project_id: str, dataset: str, table: str, rows: pd.DataFrame, key_columns: list[str]
) -> None:
    """MERGE `rows` into `dataset.table`, matching on `key_columns`. Assumes
    the target table already exists (created by infra/terraform) - same
    assumption as the old retail project's `_write_feed_rows`.
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    staging_table_id = f"{table_id}_staging"

    job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    client.load_table_from_dataframe(rows, staging_table_id, job_config=job_config).result()

    update_cols = [c for c in rows.columns if c not in key_columns]
    key_match = " AND ".join(f"target.{c} = staging.{c}" for c in key_columns)
    update_set = ", ".join(f"{c} = staging.{c}" for c in update_cols)
    insert_cols = ", ".join(rows.columns)
    insert_vals = ", ".join(f"staging.{c}" for c in rows.columns)

    merge_sql = f"""
    MERGE `{table_id}` AS target
    USING `{staging_table_id}` AS staging
    ON {key_match}
    WHEN MATCHED THEN UPDATE SET {update_set}
    WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """
    client.query(merge_sql).result()
    client.delete_table(staging_table_id, not_found_ok=True)
