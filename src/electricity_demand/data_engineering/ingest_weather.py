"""Daily weather ingest: re-pulls a trailing window of actual daily
temperature (see weather_client.py) for every tracked balancing authority and
upserts it, keyed on (ba_code, date) - same trailing-window-upsert shape as
ingest_eia.py, since Open-Meteo's reanalysis archive can also revise very
recent days as more observations come in.

Meant to run as a scheduled Cloud Run Job alongside ingest_eia.py, and last
in that pair (see infra/terraform's schedule) - once both raw sources have
landed, this also re-runs dbt so the marts (fct_demand) reflect today's data
before drift-check/batch-predict/retrain-trigger run.

Local dev (no --project-id): pass --local-out to upsert into a local CSV
instead of BigQuery.

Usage:
    uv run --env-file .env python -m electricity_demand.data_engineering.ingest_weather \\
        --project-id "$GCP_PROJECT_ID"
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

from electricity_demand.data_engineering.balancing_authorities import BALANCING_AUTHORITIES
from electricity_demand.data_engineering.bigquery_merge import merge_into_bigquery
from electricity_demand.data_engineering.local_store import upsert_local_csv
from electricity_demand.data_engineering.weather_client import fetch_weather_actuals_for_all

DEFAULT_WINDOW_DAYS = 14
KEY_COLUMNS = ["ba_code", "date"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=None, help="Required unless --local-out is set.")
    parser.add_argument("--raw-dataset", default="electricity_demand_raw")
    parser.add_argument("--raw-table", default="weather_raw")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--start-date",
        default=None,
        help="Backfill mode: explicit start date (overrides --window-days).",
    )
    parser.add_argument("--end-date", default=None, help="Backfill mode: explicit end date.")
    parser.add_argument("--local-out", default=None, help="Local CSV path - dev mode without GCP.")
    parser.add_argument("--bq-location", default="US")
    parser.add_argument(
        "--skip-dbt",
        action="store_true",
        help="Skip the dbt run after merging - useful for a standalone backfill.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    default_end = dt.datetime.now(dt.timezone.utc).date()

    if args.start_date:
        start_date = dt.date.fromisoformat(args.start_date)
        end_date = dt.date.fromisoformat(args.end_date) if args.end_date else default_end
    else:
        end_date = default_end
        start_date = end_date - dt.timedelta(days=args.window_days)

    rows = fetch_weather_actuals_for_all(BALANCING_AUTHORITIES, start_date, end_date)
    if rows.empty:
        print(f"No rows returned for {start_date}..{end_date}.")
        return
    # A real Timestamp dtype (not an ISO string) so BigQuery's autodetect on
    # the staging-table load (bigquery_merge.py) picks TIMESTAMP, matching
    # the weather_raw schema Terraform defines.
    rows["ingested_at"] = pd.Timestamp.now(tz="UTC")

    if args.local_out:
        combined = upsert_local_csv(Path(args.local_out), rows, KEY_COLUMNS, "ingested_at")
        print(
            f"Upserted {len(rows)} row(s) for {start_date}..{end_date} into "
            f"{args.local_out} ({len(combined)} total rows)."
        )
        return

    if not args.project_id:
        raise SystemExit("--project-id is required unless --local-out is set.")
    merge_into_bigquery(args.project_id, args.raw_dataset, args.raw_table, rows, KEY_COLUMNS)
    print(
        f"Merged {len(rows)} row(s) for {start_date}..{end_date} into "
        f"{args.project_id}.{args.raw_dataset}.{args.raw_table}."
    )

    if not args.skip_dbt:
        from electricity_demand.data_engineering.dbt_runner import run_dbt

        run_dbt(args.project_id, args.bq_location)
        print("dbt run complete.")


if __name__ == "__main__":
    main()
