# Terraform — GCP infra

Provisions the shared infra: raw GCS bucket, BigQuery datasets
(raw/staging/marts), an Artifact Registry Docker repo, a service account for
pipeline/ingest/training jobs, and a Cloud Build trigger that builds the
pipeline image and submits a Vertex AI training run on push to `master`.

Several resource groups are conditional on an image already existing, so the
base infra (bucket/BigQuery/Artifact Registry/service account/Cloud Build
trigger) can be applied before any images are built:

- `google_cloud_run_v2_job.ingest_eia` / `ingest_weather` + their schedulers
  — the daily ingest jobs (see `src/electricity_demand/data_engineering/`),
  created once `pipeline_image_uri` is set.
- `google_cloud_run_v2_service.serving` — the live-request serving API,
  created only once `serving_image_uri` is set.
- `google_cloud_run_v2_job.batch_predict` + its scheduler — the daily
  batch-scoring path, created once `pipeline_image_uri` is set.
- `google_cloud_run_v2_job.drift_check` + its scheduler — daily feature
  drift check, logged to BigQuery, created once `pipeline_image_uri` is set.
- `google_cloud_run_v2_job.retrain_trigger` + its scheduler — reads the
  latest drift/metrics and submits a new training pipeline run, created
  once both `pipeline_image_uri` and `serving_image_uri` are set (a
  triggered retrain needs a serving image to register against).

## Prerequisites

1. A GCP project with billing enabled — done: `electricity-demand-191067`
   (see repo root `.env`).
2. [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5 —
   installed (`terraform -version`).
3. [gcloud CLI](https://cloud.google.com/sdk/docs/install), authenticated as
   the account that owns the project above:
   ```bash
   gcloud auth application-default login
   ```
4. For the Cloud Build trigger only: install the "Google Cloud Build"
   GitHub App on this repo once, manually, via the Cloud Build console
   (Triggers -> Connect Repository -> GitHub). Terraform can create the
   trigger resource itself, but the initial GitHub OAuth connection is a
   one-time console step it can't do for you. Until that's done, the
   `google_cloudbuild_trigger.training_pipeline` resource will fail to
   apply — `-target` around it (see below) if you haven't connected the App
   yet.

## Usage

```bash
cd infra/terraform
terraform init
terraform plan \
  -var="project_id=electricity-demand-191067" \
  -var="raw_bucket_name=electricity-demand-191067-raw"
terraform apply \
  -var="project_id=electricity-demand-191067" \
  -var="raw_bucket_name=electricity-demand-191067-raw"
```

Or copy the variables into a `terraform.tfvars` file (gitignored) instead of
passing `-var` flags each time. `github_owner`/`github_repo_name` default to
this repo's own GitHub location, so you only need to override them if you've
forked it elsewhere.

To trigger a build manually without waiting for a push (useful while
testing):

```bash
gcloud builds submit --config cloudbuild.yaml --project electricity-demand-191067
```

Once both images exist (built by the Cloud Build trigger above, or manually
via `docker build`/`docker push`), re-apply with the image variables set to
create the ingest/batch-predict/monitoring Cloud Run Jobs + their
schedulers, and the serving Cloud Run service:

```bash
terraform apply \
  -var="project_id=electricity-demand-191067" \
  -var="raw_bucket_name=electricity-demand-191067-raw" \
  -var="pipeline_image_uri=us-central1-docker.pkg.dev/electricity-demand-191067/electricity-demand/pipeline:latest" \
  -var="serving_image_uri=us-central1-docker.pkg.dev/electricity-demand-191067/electricity-demand/serving:latest"
```

## Cost notes

- The serving Cloud Run service grants `roles/run.invoker` to `allUsers`
  once `serving_image_uri` is set (so the Vercel frontend can call it
  directly from visitors' browsers) but keeps `min_instance_count = 0`, so
  idle traffic still costs nothing.
- The raw GCS bucket auto-deletes objects after 30 days (BigQuery, not GCS,
  is the source of truth once loaded).
- Run `terraform destroy` when you're done experimenting to avoid any
  lingering storage cost.
