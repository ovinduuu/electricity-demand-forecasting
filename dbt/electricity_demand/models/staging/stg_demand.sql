-- Pivots the raw long format (one row per respondent/type/period) into one
-- row per (date, ba_code) with demand_mwh/demand_forecast_mwh as columns -
-- eia_demand_raw is already deduplicated to one row per
-- (respondent, type, period) by ingest_eia.py's MERGE, so no dedup needed
-- here, just the pivot and a rename to this project's grain columns.
select
    period as date,
    respondent as ba_code,
    max(if(type = 'D', value, null)) as demand_mwh,
    max(if(type = 'DF', value, null)) as demand_forecast_mwh
from {{ source('raw', 'eia_demand_raw') }}
group by date, ba_code
