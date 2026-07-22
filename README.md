# Electricity Demand Forecasting

An MLOps portfolio project forecasting daily electricity demand for 10 US
grid regions (balancing authorities), built on the
[EIA Open Data API](https://www.eia.gov/opendata/) — genuinely live-updating
data (unlike a frozen Kaggle-style dataset), so the daily ingest/retrain/
monitoring loop reflects real new data every day instead of anything
fabricated.

Successor to [retail-demand-forecasting](https://github.com/ovinduuu/retail-demand-forecasting):
same MLOps shape (dbt on BigQuery, LightGBM on Vertex AI Pipelines, Cloud Run
serving + scheduled jobs, a Next.js frontend), rebuilt around a new domain
and a real live data source instead of a frozen, one-time-download dataset.

**Live and deployed, not just built:**

- Frontend: https://electricity-demand-forecasting-fawn.vercel.app
- Serving API: https://electricity-demand-serving-vi7c6rjegq-uc.a.run.app

The trained model achieves **3.1% MAPE**, beating the grid operators' own
published day-ahead demand forecasts (3.3% MAPE) on the same validation
window — a real benchmark this domain provides that retail forecasting had
no equivalent of. A 90-day backtest across all 10 regions puts it closer to
**2.5% MAPE**.

## Data source

[EIA Open Data API](https://www.eia.gov/opendata/) (Form EIA-930) — daily
electricity demand and each grid operator's own day-ahead demand forecast,
by balancing authority. Free, no cost, updates daily. Paired with
[Open-Meteo](https://open-meteo.com) for per-region daily temperature
(free, no API key) — electricity demand is heavily weather-driven, unlike
retail sales.

10 balancing authorities are tracked: PJM, CISO, ERCO, MISO, SWPP, ISNE,
NYIS, SOCO, FPL, TVA — chosen for climate/timezone diversity.

## Stack

| Layer | Tools |
|---|---|
| Data engineering | GCS, BigQuery, dbt |
| ML | LightGBM |
| Pipeline / MLOps | Vertex AI Pipelines (KFP v2), Vertex AI Model Registry |
| CI/CD | Cloud Build (image build + pipeline submit on push to `master`) |
| Serving | FastAPI on Cloud Run (public serving API), Cloud Run Job (scheduled batch predict) |
| Monitoring | Custom PSI drift checks + training metrics, both logged to BigQuery; Cloud Run Jobs on Cloud Scheduler |
| IaC | Terraform |
| Frontend | Next.js (App Router) + TypeScript + Tailwind, deployed to Vercel |

## Repo layout

```
src/electricity_demand/
  data_engineering/   # EIA + Open-Meteo clients, daily upsert ingest, dbt seed generator
  models/             # baselines, feature engineering, LightGBM training, evaluation
  pipelines/          # KFP v2 components + pipeline definition, compile/submit CLI
  serving/            # scheduled batch-predict script + FastAPI app
  monitoring/         # drift checks + retraining trigger
dbt/electricity_demand/  # BigQuery transforms: staging -> marts
infra/terraform/      # GCS, BigQuery, Artifact Registry, Cloud Build/Run/Scheduler
docker/                # serving image (root Dockerfile is the pipeline image)
frontend/              # Next.js forecast demo (see frontend/README.md)
data/                  # local, gitignored: raw CSV extracts for local dev
tests/                 # pytest unit tests, no cloud credentials needed
```

## Key design decisions vs. the old retail project

- **Ingestion is upsert, not append.** EIA revises provisional values over
  the following weeks; `ingest_eia.py`/`ingest_weather.py` re-pull a
  trailing window and `MERGE` on every run instead of blindly appending.
- **Weather features, not SNAP/event flags** — heating/cooling degree days
  and holiday features are the actual causal drivers of electricity demand.
- **No WRMSSE.** There's no item hierarchy here; the register-if-improved
  gate is unweighted mean per-region MAPE instead.
- **EIA's own day-ahead forecast is a benchmark, not a model input** — it's
  never actually available at real serving time (only in hindsight), so
  using it as a feature was training/serving skew, caught via a live
  end-to-end test where a real forecast came back ~4x too low.

## Getting started

```bash
uv sync --all-extras
uv run pytest -v
uv run ruff check .
```

To work with real data and cloud resources, follow, in order:

1. Sign up for a free [EIA API key](https://www.eia.gov/opendata/) and put
   it in `.env` (copy `.env.example`).
2. [`infra/terraform/README.md`](infra/terraform/README.md) — provision the
   base GCP infra (GCS, BigQuery, Artifact Registry, service accounts, the
   Cloud Build trigger).
3. Backfill data: `uv run --env-file .env python -m electricity_demand.data_engineering.ingest_eia --project-id <id> --start-date 2019-01-01`
   (and the equivalent for `ingest_weather`), then run the dbt project
   (`dbt/electricity_demand/`) to build the marts.
4. Build and push the two Docker images (root `Dockerfile` for the
   pipeline, `docker/serving.Dockerfile` for serving), then re-apply
   Terraform with `pipeline_image_uri`/`serving_image_uri` set to create the
   Cloud Run services/jobs and their schedulers.
5. [`frontend/README.md`](frontend/README.md) — run the demo locally
   against a local backend, or deploy it to Vercel pointed at the real
   Cloud Run serving URL from step 4.
