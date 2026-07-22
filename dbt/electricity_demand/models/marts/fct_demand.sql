-- One row per (date, ba_code): EIA demand + day-ahead forecast, weather, and
-- calendar context all in one table - the new project's fct_sales, read
-- directly by models/features.py the same way the old project read
-- fct_sales, instead of the feature code having to join staging models itself.
with demand as (
    select * from {{ ref('stg_demand') }}
),

weather as (
    select * from {{ ref('stg_weather') }}
),

calendar as (
    select * from {{ ref('stg_calendar') }}
)

select
    demand.date,
    demand.ba_code,
    demand.demand_mwh,
    demand.demand_forecast_mwh,
    weather.temp_max_c,
    weather.temp_min_c,
    weather.temp_mean_c,
    calendar.dayofweek,
    calendar.is_weekend,
    calendar.month,
    calendar.is_holiday,
    calendar.holiday_name
from demand
left join weather
    on demand.date = weather.date
    and demand.ba_code = weather.ba_code
left join calendar
    on demand.date = calendar.date
