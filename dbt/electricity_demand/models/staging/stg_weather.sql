-- weather_raw is already one row per (ba_code, date) via ingest_weather.py's
-- MERGE, so this is a passthrough/rename - no dedup or pivot needed.
select
    date,
    ba_code,
    temp_max_c,
    temp_min_c,
    temp_mean_c
from {{ source('raw', 'weather_raw') }}
