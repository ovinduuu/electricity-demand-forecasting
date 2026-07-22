select
    date,
    dayofweek,
    is_weekend,
    month,
    year,
    holiday_name,
    is_holiday
from {{ ref('stg_calendar') }}
