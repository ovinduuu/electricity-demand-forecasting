"""Daily EIA ingest: re-pulls a trailing window of demand/day-ahead-forecast
data for every tracked balancing authority (see balancing_authorities.py) and
upserts it - so revisions EIA publishes after the fact (values are
provisional at first - see eia_client.py's module docstring) get picked up on
the next run instead of being locked in from a one-time append. There's no
synthetic generator here: EIA genuinely has new/changed rows every day, so
this replaces the old retail project's daily_ingest.py + download_m5.py +
synthetic_daily_feed.py entirely.

Meant to run as a scheduled Cloud Run Job (see infra/terraform), same
daily-chain position as the old project's daily_ingest.py: earliest in the
chain, before drift-check/batch-predict/retrain-trigger.

Local dev (no GCP project yet): pass --local-out to upsert into a local CSV
instead of BigQuery.

Usage:
    uv run --env-file .env python -m electricity_demand.data_engineering.ingest_eia \\
        --local-out data/raw/eia_demand.csv

    # One-time backfill:
    uv run --env-file .env python -m electricity_demand.data_engineering.ingest_eia \\
        --local-out data/raw/eia_demand.csv --start-date 2019-01-01
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

from electricity_demand.data_engineering.balancing_authorities import BALANCING_AUTHORITIES
from electricity_demand.data_engineering.bigquery_merge import merge_into_bigquery
from electricity_demand.data_engineering.eia_client import fetch_demand_for_all
from electricity_demand.data_engineering.local_store import upsert_local_csv

DEFAULT_WINDOW_DAYS = 14
# EIA-930 daily values for "today" generally aren't published yet - pulling
# through yesterday avoids every run seeing a spuriously "missing" latest day.
PUBLISH_LAG_DAYS = 1
KEY_COLUMNS = ["respondent", "type", "period"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=None, help="Required unless --local-out is set.")
    parser.add_argument("--raw-dataset", default="electricity_demand_raw")
    parser.add_argument("--raw-table", default="eia_demand_raw")
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help="Trailing days to re-pull and upsert on each run, to catch EIA revisions.",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Backfill mode: explicit start date (overrides --window-days).",
    )
    parser.add_argument("--end-date", default=None, help="Backfill mode: explicit end date.")
    parser.add_argument("--local-out", default=None, help="Local CSV path - dev mode without GCP.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    default_end = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=PUBLISH_LAG_DAYS)

    if args.start_date:
        start_date = dt.date.fromisoformat(args.start_date)
        end_date = dt.date.fromisoformat(args.end_date) if args.end_date else default_end
    else:
        end_date = default_end
        start_date = end_date - dt.timedelta(days=args.window_days)

    rows = fetch_demand_for_all(BALANCING_AUTHORITIES, start_date, end_date)
    if rows.empty:
        print(f"No rows returned for {start_date}..{end_date}.")
        return
    # A real Timestamp dtype (not an ISO string) so BigQuery's autodetect on
    # the staging-table load (bigquery_merge.py) picks TIMESTAMP, matching
    # the eia_demand_raw schema Terraform defines.
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


if __name__ == "__main__":
    main()
