# Electricity Demand Forecasting

An MLOps portfolio project forecasting short-term electricity demand from the
US EIA's Open Data API — genuinely live-updating data (unlike a frozen
Kaggle-style dataset), so the daily retrain/monitoring loop reflects real new
data every day instead of anything fabricated.

Successor to [retail-demand-forecasting](https://github.com/ovinduuu/retail-demand-forecasting):
same MLOps shape (dbt on BigQuery, LightGBM on Vertex AI Pipelines, Cloud Run
serving + scheduled jobs, a Next.js frontend), new domain and a real live data
source.

Status: just started — see `ROADMAP.md` (once written) for the build plan.

## Data source

[EIA Open Data API](https://www.eia.gov/opendata/) — hourly/daily electricity
demand by balancing authority (regional grid operator). Free, no cost, updates
daily.

## Stack

- **Ingestion**: EIA API -> BigQuery
- **Transform**: dbt (staging -> marts)
- **Training**: LightGBM on Vertex AI Pipelines (KFP v2)
- **Serving**: FastAPI on Cloud Run
- **Frontend**: Next.js on Vercel
- **Infra**: Terraform (GCP)
