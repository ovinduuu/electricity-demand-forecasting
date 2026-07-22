select
    ba_code,
    ba_name,
    eia_timezone,
    weather_city,
    weather_lat,
    weather_lon,
    weather_iana_tz
from {{ ref('balancing_authorities') }}
