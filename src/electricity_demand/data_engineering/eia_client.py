"""Thin client for the EIA Open Data API v2 `electricity/rto/daily-region-data`
route (Form EIA-930): daily demand ("D") and day-ahead demand forecast ("DF")
by balancing authority.

Requires EIA_API_KEY (free signup at https://www.eia.gov/opendata/) in the
environment - see .env.example.

Usage:
    from electricity_demand.data_engineering.eia_client import fetch_demand
    df = fetch_demand("PJM", "Eastern", date(2024, 1, 1), date(2024, 1, 31))
"""

from __future__ import annotations

import datetime as dt
import os
import time

import pandas as pd
import requests

BASE_URL = "https://api.eia.gov/v2/electricity/rto/daily-region-data/data/"
DEFAULT_TYPES = ["D", "DF"]
MAX_PAGE_LENGTH = 5000
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

RAW_COLUMNS = ["period", "respondent", "type", "value"]


def _api_key() -> str:
    key = os.environ.get("EIA_API_KEY")
    if not key:
        raise RuntimeError("EIA_API_KEY is not set - see .env.example.")
    return key


def _get_page(params: dict) -> dict:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError(f"EIA API request failed after {MAX_RETRIES} attempts: {last_error}")


def fetch_demand(
    ba_code: str,
    eia_timezone: str,
    start_date: dt.date,
    end_date: dt.date,
    types: list[str] | None = None,
) -> pd.DataFrame:
    """One balancing authority's daily demand/forecast rows for
    [start_date, end_date] (inclusive), paginated past the API's 5,000-row cap.

    `eia_timezone` must be one of the route's undocumented timezone facet
    values (Arizona/Central/Eastern/Mountain/Pacific) - see
    balancing_authorities.py's module docstring for why this is required
    rather than optional.

    Returns columns [period, respondent, type, value] - period as a
    datetime.date, value as float64 (NaN for any unparseable value rather
    than raising, since EIA's raw data is documented to include
    irregularities/missing values that are this project's actual point of
    interest, not something to fail loudly on at ingest time).
    """
    types = types or DEFAULT_TYPES
    params = {
        "api_key": _api_key(),
        "frequency": "daily",
        "data[]": "value",
        "facets[respondent][]": ba_code,
        "facets[type][]": types,
        "facets[timezone][]": eia_timezone,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": MAX_PAGE_LENGTH,
        "offset": 0,
    }

    rows: list[dict] = []
    while True:
        payload = _get_page(params)
        page_rows = payload["response"]["data"]
        rows.extend(page_rows)
        total = int(payload["response"]["total"])
        if len(rows) >= total or not page_rows:
            break
        params["offset"] += MAX_PAGE_LENGTH

    if not rows:
        return pd.DataFrame(columns=RAW_COLUMNS)

    df = pd.DataFrame(rows)[RAW_COLUMNS]
    df["period"] = pd.to_datetime(df["period"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def fetch_demand_for_all(
    balancing_authorities,
    start_date: dt.date,
    end_date: dt.date,
    types: list[str] | None = None,
) -> pd.DataFrame:
    """fetch_demand() for each BA in `balancing_authorities`
    (data_engineering.balancing_authorities.BALANCING_AUTHORITIES), concatenated.
    """
    frames = [
        fetch_demand(ba.ba_code, ba.eia_timezone, start_date, end_date, types)
        for ba in balancing_authorities
    ]
    if not frames:
        return pd.DataFrame(columns=RAW_COLUMNS)
    return pd.concat(frames, ignore_index=True)
