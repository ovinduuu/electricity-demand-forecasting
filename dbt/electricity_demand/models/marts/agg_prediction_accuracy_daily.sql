-- One row per date, aggregated from fct_prediction_accuracy - cheap for the
-- serving API to read for a "model accuracy over time" chart, instead of
-- aggregating across all 10 BAs on every request.
select
    date,
    count(*) as n_predictions,
    avg(abs_error) as mae,
    avg(pct_error) as mape,
    sqrt(avg(power(predicted_demand_mwh - actual_demand_mwh, 2))) as rmse
from {{ ref('fct_prediction_accuracy') }}
group by date
order by date
