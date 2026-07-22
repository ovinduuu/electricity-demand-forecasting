-- One row per prediction that has a matching actual. Inner join means a
-- prediction only shows up here once that date's real demand has landed
-- (via data_engineering/ingest_eia.py) - naturally lags predictions by
-- however long that takes, rather than needing an explicit "is this ready
-- yet" check.
with predictions as (
    select date, ba_code, predicted_demand_mwh
    from {{ source('marts_raw', 'fct_demand_predictions') }}
),

actuals as (
    select date, ba_code, demand_mwh
    from {{ ref('fct_demand') }}
)

select
    predictions.date,
    predictions.ba_code,
    predictions.predicted_demand_mwh,
    actuals.demand_mwh as actual_demand_mwh,
    abs(predictions.predicted_demand_mwh - actuals.demand_mwh) as abs_error,
    case
        when actuals.demand_mwh > 0
            then abs(predictions.predicted_demand_mwh - actuals.demand_mwh) / actuals.demand_mwh
    end as pct_error
from predictions
inner join actuals
    on predictions.date = actuals.date
    and predictions.ba_code = actuals.ba_code
