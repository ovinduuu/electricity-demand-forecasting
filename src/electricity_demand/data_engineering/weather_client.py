"""Thin client for Open-Meteo (https://open-meteo.com) - free, no API key,
used for per-balancing-authority daily temperature (see
balancing_authorities.py for the one representative lat/lon per BA).

Two endpoints, deliberately kept separate rather than merged behind one
"get weather" function: the archive endpoint (reanalysis, stays accurate as
new days pass) is for historical/backfill use, and the forecast endpoint
(actual forecast, will disagree with the eventual archive value) is for
predicting demand on dates that haven't happened yet - conflating them would
silently let training data quietly include "forecast" values that later
turned out wrong.
"""

from __future__ import annotations

import datetime as dt
import time

import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"]
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

RAW_COLUMNS = ["date", "temp_max_c", "temp_min_c", "temp_mean_c"]
_RENAME = {
    "time": "date",
    "temperature_2m_max": "temp_max_c",
    "temperature_2m_min": "temp_min_c",
    "temperature_2m_mean": "temp_mean_c",
}


def _get(url: str, params: dict) -> dict:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError(f"Open-Meteo request failed after {MAX_RETRIES} attempts: {last_error}")


def _daily_frame(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame(payload["daily"]).rename(columns=_RENAME)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[RAW_COLUMNS]


def fetch_weather_actuals(
    lat: float, lon: float, iana_tz: str, start_date: dt.date, end_date: dt.date
) -> pd.DataFrame:
    """Historical daily temperature for [start_date, end_date] from the
    reanalysis archive - a multi-year range is one call, no pagination needed
    (confirmed: a ~7.5-year single-BA request returns in well under a second).
    """
    payload = _get(
        ARCHIVE_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join(DAILY_VARS),
            "timezone": iana_tz,
        },
    )
    return _daily_frame(payload)


def fetch_weather_forecast(
    lat: float, lon: float, iana_tz: str, forecast_days: int = 7
) -> pd.DataFrame:
    """Next `forecast_days` days of forecast daily temperature - for
    predicting demand on dates that haven't happened yet (see module
    docstring for why this is a separate call from fetch_weather_actuals).
    """
    payload = _get(
        FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(DAILY_VARS),
            "timezone": iana_tz,
            "forecast_days": forecast_days,
        },
    )
    return _daily_frame(payload)


def fetch_weather_actuals_for_all(
    balancing_authorities, start_date: dt.date, end_date: dt.date
) -> pd.DataFrame:
    """fetch_weather_actuals() for each BA in `balancing_authorities`
    (data_engineering.balancing_authorities.BALANCING_AUTHORITIES), concatenated
    with a `ba_code` column added.
    """
    frames = []
    for ba in balancing_authorities:
        df = fetch_weather_actuals(
            ba.weather_lat, ba.weather_lon, ba.weather_iana_tz, start_date, end_date
        )
        df["ba_code"] = ba.ba_code
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["ba_code", *RAW_COLUMNS])
    return pd.concat(frames, ignore_index=True)
