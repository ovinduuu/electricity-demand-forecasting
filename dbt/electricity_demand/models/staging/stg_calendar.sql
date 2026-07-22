-- calendar_dates is a dbt seed (data_engineering/build_seeds.py generates
-- it from a Python source of truth - see that module's docstring), so this
-- is a straight passthrough, same shape as stg_weather.
select
    date,
    dayofweek,
    is_weekend,
    month,
    year,
    holiday_name,
    is_holiday
from {{ ref('calendar_dates') }}
