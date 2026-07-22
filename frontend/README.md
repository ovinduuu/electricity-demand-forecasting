# Electricity Demand Forecast — frontend

An interactive demo: pick a US grid region (balancing authority), see its
recent electricity demand and the model's one-step-ahead forecast on a
chart, benchmarked against the grid operator's own published day-ahead
forecast. Calls the serving API in `../src/electricity_demand/serving/app.py`
(`/series`, `/history/{ba_code}`, `/forecast/{ba_code}`).

## Local development

The backend needs to be running somewhere reachable. There's a real
deployed instance already:

```
NEXT_PUBLIC_API_BASE_URL=https://electricity-demand-serving-vi7c6rjegq-uc.a.run.app
```

or run one locally:

```bash
# from the repo root, with a trained model at artifacts/lightgbm_model.txt
# and a local sample CSV (see ../data/README.md for how to make one) —
# LOCAL_DATA_CSV avoids needing real BigQuery/GCP credentials for local dev
MODEL_PATH=artifacts/lightgbm_model.txt LOCAL_DATA_CSV=path/to/history.csv \
  uv run uvicorn electricity_demand.serving.app:app --port 8080
```

Then, in this directory:

```bash
cp .env.example .env.local   # set NEXT_PUBLIC_API_BASE_URL to either option above
npm install
npm run dev
```

Open http://localhost:3000.

If the backend isn't reachable, the page shows a clear "Backend not
reachable" message instead of failing silently.

## Deploying to Vercel

1. Push this repo to GitHub (already done — see the root README).
2. On [vercel.com](https://vercel.com), "Add New Project" → import this
   repo → set **Root Directory** to `frontend`.
3. Add an environment variable: `NEXT_PUBLIC_API_BASE_URL` = the deployed
   serving API's Cloud Run URL (Terraform output `serving_url`;
   currently `https://electricity-demand-serving-vi7c6rjegq-uc.a.run.app`).
4. Deploy. Vercel auto-detects Next.js — no build config needed.

Once the frontend has a real Vercel URL, tighten the backend's CORS policy
by re-applying Terraform with `-var="frontend_origin=https://your-app.vercel.app"`
instead of the default `*`.

## Stack

Next.js 16 (App Router) + TypeScript + Tailwind CSS v4. The chart in
`components/ForecastChart.tsx` is hand-built SVG (no charting library) —
axes, gridlines, hover crosshair + tooltip, a legend, and a table-view
toggle for accessibility.
