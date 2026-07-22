"""The ~10 balancing authorities this project tracks - the source of truth both
ingestion (data_engineering/ingest_eia.py, ingest_weather.py) and the dbt seed
generator (data_engineering/build_seeds.py) read from, so the BA list only
needs to change in one place.

Picked for climate/timezone diversity (PJM/ISNE/NYIS/FPL Eastern, SWPP/ERCO/TVA
Central, CISO Pacific) while keeping ingest volume small, matching the old
retail project's ~10-store scope.

`eia_timezone` pins the EIA daily-region-data route's undocumented timezone
facet (Arizona/Central/Eastern/Mountain/Pacific) - the API buckets the
underlying hourly series into a "day" using that timezone's midnight boundary
and returns 5x duplicate rows per day otherwise (confirmed live against the
real API - not documented on any EIA doc page found). Values below are a
best-effort mapping from each BA's headquarters/majority-footprint timezone;
getting one wrong only reallocates a few boundary hours between adjacent
days, not a correctness-critical choice for daily aggregates.

`weather_lat`/`weather_lon` are one representative city per BA for Open-Meteo
(data_engineering/weather_client.py) - a single point can't capture a whole
grid region's weather, but it's a reasonable proxy for a portfolio-scale
project, same spirit as fct_sales using per-store rather than per-customer data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BalancingAuthority:
    ba_code: str
    ba_name: str
    eia_timezone: str
    weather_city: str
    weather_lat: float
    weather_lon: float
    weather_iana_tz: str


BALANCING_AUTHORITIES: list[BalancingAuthority] = [
    BalancingAuthority(
        "PJM",
        "PJM Interconnection",
        "Eastern",
        "Philadelphia, PA",
        39.9526,
        -75.1652,
        "America/New_York",
    ),
    BalancingAuthority(
        "CISO",
        "California ISO",
        "Pacific",
        "Sacramento, CA",
        38.5816,
        -121.4944,
        "America/Los_Angeles",
    ),
    BalancingAuthority(
        "ERCO", "ERCOT", "Central", "Dallas, TX", 32.7767, -96.7970, "America/Chicago"
    ),
    BalancingAuthority(
        "MISO",
        "Midcontinent ISO",
        "Eastern",
        "Indianapolis, IN",
        39.7684,
        -86.1581,
        "America/Indiana/Indianapolis",
    ),
    BalancingAuthority(
        "SWPP",
        "Southwest Power Pool",
        "Central",
        "Kansas City, MO",
        39.0997,
        -94.5786,
        "America/Chicago",
    ),
    BalancingAuthority(
        "ISNE", "ISO New England", "Eastern", "Boston, MA", 42.3601, -71.0589, "America/New_York"
    ),
    BalancingAuthority(
        "NYIS", "New York ISO", "Eastern", "Albany, NY", 42.6526, -73.7562, "America/New_York"
    ),
    BalancingAuthority(
        "SOCO", "Southern Company", "Eastern", "Atlanta, GA", 33.7490, -84.3880, "America/New_York"
    ),
    BalancingAuthority(
        "FPL",
        "Florida Power & Light",
        "Eastern",
        "Miami, FL",
        25.7617,
        -80.1918,
        "America/New_York",
    ),
    BalancingAuthority(
        "TVA",
        "Tennessee Valley Authority",
        "Central",
        "Nashville, TN",
        36.1627,
        -86.7816,
        "America/Chicago",
    ),
]

BA_CODES: list[str] = [ba.ba_code for ba in BALANCING_AUTHORITIES]
