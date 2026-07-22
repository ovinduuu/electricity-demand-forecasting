"""Generates the dbt seed CSVs (dbt/electricity_demand/seeds/) from this
project's Python source of truth, so the seed data and the ingestion code
that reads the same BA list (eia_client.py, weather_client.py) never drift
apart. Re-run whenever balancing_authorities.py changes, or to extend the
calendar's date range.

No daily job needed for either seed - holidays and the BA list are static,
unlike eia_demand_raw/weather_raw which genuinely change every day.

Usage:
    uv run python -m electricity_demand.data_engineering.build_seeds
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from electricity_demand.config import REPO_ROOT
from electricity_demand.data_engineering.balancing_authorities import BALANCING_AUTHORITIES

DEFAULT_SEEDS_DIR = REPO_ROOT / "dbt" / "electricity_demand" / "seeds"
CALENDAR_START = dt.date(2015, 1, 1)  # comfortably before EIA-930 history starts (2019 for PJM)
CALENDAR_END = dt.date(2035, 12, 31)  # comfortably past any forecast horizon


def build_calendar_dates(
    start: dt.date = CALENDAR_START, end: dt.date = CALENDAR_END
) -> pd.DataFrame:
    dates = pd.date_range(start, end, freq="D")
    holiday_names = USFederalHolidayCalendar().holidays(start=start, end=end, return_name=True)
    holiday_by_date = pd.Series(holiday_names.values, index=holiday_names.index.date)

    df = pd.DataFrame({"date": dates.date})
    df["dayofweek"] = dates.dayofweek
    df["is_weekend"] = df["dayofweek"].isin([5, 6]).astype(int)
    df["month"] = dates.month
    df["year"] = dates.year
    df["holiday_name"] = df["date"].map(holiday_by_date)
    df["is_holiday"] = df["holiday_name"].notna().astype(int)
    df["holiday_name"] = df["holiday_name"].fillna("none")
    return df


def build_balancing_authorities() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ba_code": ba.ba_code,
            "ba_name": ba.ba_name,
            "eia_timezone": ba.eia_timezone,
            "weather_city": ba.weather_city,
            "weather_lat": ba.weather_lat,
            "weather_lon": ba.weather_lon,
            "weather_iana_tz": ba.weather_iana_tz,
        }
        for ba in BALANCING_AUTHORITIES
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds-dir", default=str(DEFAULT_SEEDS_DIR))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    seeds_dir = Path(args.seeds_dir)
    seeds_dir.mkdir(parents=True, exist_ok=True)

    calendar_path = seeds_dir / "calendar_dates.csv"
    build_calendar_dates().to_csv(calendar_path, index=False)
    print(f"Wrote {calendar_path}")

    ba_path = seeds_dir / "balancing_authorities.csv"
    build_balancing_authorities().to_csv(ba_path, index=False)
    print(f"Wrote {ba_path}")


if __name__ == "__main__":
    main()
