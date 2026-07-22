import datetime as dt

from electricity_demand.data_engineering.balancing_authorities import BALANCING_AUTHORITIES
from electricity_demand.data_engineering.build_seeds import (
    build_balancing_authorities,
    build_calendar_dates,
)


def test_build_calendar_dates_flags_known_holidays():
    df = build_calendar_dates(dt.date(2024, 1, 1), dt.date(2024, 1, 31))
    new_years = df[df["date"] == dt.date(2024, 1, 1)].iloc[0]
    mlk_day = df[df["date"] == dt.date(2024, 1, 15)].iloc[0]
    regular_day = df[df["date"] == dt.date(2024, 1, 2)].iloc[0]

    assert new_years["is_holiday"] == 1
    assert new_years["holiday_name"] == "New Year's Day"
    assert mlk_day["is_holiday"] == 1
    assert regular_day["is_holiday"] == 0
    assert regular_day["holiday_name"] == "none"


def test_build_calendar_dates_weekend_flag():
    df = build_calendar_dates(dt.date(2024, 1, 1), dt.date(2024, 1, 7))
    saturday = df[df["date"] == dt.date(2024, 1, 6)].iloc[0]
    monday = df[df["date"] == dt.date(2024, 1, 1)].iloc[0]

    assert saturday["is_weekend"] == 1
    assert monday["is_weekend"] == 0


def test_build_balancing_authorities_covers_all_tracked_bas():
    df = build_balancing_authorities()
    assert len(df) == len(BALANCING_AUTHORITIES)
    assert set(df["ba_code"]) == {ba.ba_code for ba in BALANCING_AUTHORITIES}
    assert df["ba_code"].is_unique
