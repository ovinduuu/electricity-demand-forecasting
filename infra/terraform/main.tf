terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  # Fixed paths shared by the batch-predict, register_model, and
  # retrain_trigger jobs - keeping these in one place avoids the literal
  # gs:// strings drifting out of sync across resources.
  serving_model_gcs_path = "gs://${var.raw_bucket_name}/models/lightgbm_model.txt"
  pipeline_root          = "gs://${var.raw_bucket_name}/pipeline-root"
}

# --- Enable the APIs this project needs -------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudfunctions.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Raw data landing zone ---------------------------------------------------
resource "google_storage_bucket" "raw" {
  depends_on = [google_project_service.apis]

  name                        = var.raw_bucket_name
  location                    = var.region
  project                     = var.project_id
  uniform_bucket_level_access = true
  force_destroy               = false

  # Keep storage cost near zero for a portfolio project: auto-delete raw
  # objects after 30 days since BigQuery, not GCS, is the source of truth
  # once loaded.
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

# --- BigQuery datasets: raw -> staging -> marts ------------------------------
resource "google_bigquery_dataset" "raw" {
  depends_on = [google_project_service.apis]

  dataset_id = var.bq_dataset_raw
  project    = var.project_id
  location   = var.bq_location
}

resource "google_bigquery_dataset" "staging" {
  depends_on = [google_project_service.apis]

  dataset_id = var.bq_dataset_staging
  project    = var.project_id
  location   = var.bq_location
}

# Explicit schema/partitioning rather than relying on ingest_eia.py's first
# load to autodetect one - the MERGE it runs on every subsequent call
# assumes this table already exists (see bigquery_merge.py), same as the
# old retail project's raw tables.
resource "google_bigquery_table" "eia_demand_raw" {
  depends_on = [google_bigquery_dataset.raw]

  dataset_id           = google_bigquery_dataset.raw.dataset_id
  table_id             = "eia_demand_raw"
  project              = var.project_id
  deletion_protection  = false

  time_partitioning {
    type  = "DAY"
    field = "period"
  }

  schema = jsonencode([
    { name = "period", type = "DATE", mode = "REQUIRED" },
    { name = "respondent", type = "STRING", mode = "REQUIRED" },
    { name = "type", type = "STRING", mode = "REQUIRED" },
    { name = "value", type = "FLOAT64", mode = "NULLABLE" },
    { name = "ingested_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "weather_raw" {
  depends_on = [google_bigquery_dataset.raw]

  dataset_id           = google_bigquery_dataset.raw.dataset_id
  table_id             = "weather_raw"
  project              = var.project_id
  deletion_protection  = false

  time_partitioning {
    type  = "DAY"
    field = "date"
  }

  schema = jsonencode([
    { name = "date", type = "DATE", mode = "REQUIRED" },
    { name = "ba_code", type = "STRING", mode = "REQUIRED" },
    { name = "temp_max_c", type = "FLOAT64", mode = "NULLABLE" },
    { name = "temp_min_c", type = "FLOAT64", mode = "NULLABLE" },
    { name = "temp_mean_c", type = "FLOAT64", mode = "NULLABLE" },
    { name = "ingested_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_dataset" "marts" {
  depends_on = [google_project_service.apis]

  dataset_id = var.bq_dataset_marts
  project    = var.project_id
  location   = var.bq_location
}

# --- Artifact Registry for pipeline/serving container images ----------------
resource "google_artifact_registry_repository" "images" {
  depends_on = [google_project_service.apis]

  repository_id = var.artifact_repo_name
  project       = var.project_id
  location      = var.region
  format        = "DOCKER"
}

# --- Service account used by Vertex AI Pipelines / training / ingest jobs ---
resource "google_service_account" "pipeline" {
  account_id   = var.training_sa_name
  project      = var.project_id
  display_name = "Electricity demand forecasting pipeline runner"
}

resource "google_project_iam_member" "pipeline_bq" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_gcs" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

# storage.objectAdmin covers object reads/writes but not bucket-level
# metadata calls (storage.buckets.get/list) - Vertex AI's PipelineJob.submit()
# does a bucket-existence check before creating the run and 403s without this.
# legacyBucketReader is bucket-scoped only - not assignable at project level.
resource "google_storage_bucket_iam_member" "pipeline_gcs_bucket_reader" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.legacyBucketReader"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}

# Vertex AI's PipelineJob.submit(service_account=...) requires the caller to
# have iam.serviceAccountUser on the SA it's telling Vertex to run steps as -
# including "on itself" when the caller already runs as that SA (e.g. the
# retrain-trigger Cloud Run Job's own identity).
resource "google_service_account_iam_member" "pipeline_self_act_as" {
  service_account_id = google_service_account.pipeline.name
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_project_iam_member" "pipeline_logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

# --- CI/CD: build the pipeline image and submit a training run on push ------
# Requires a one-time manual step before this trigger can be created: install
# the "Google Cloud Build" GitHub App on this repo (Cloud Build console ->
# Triggers -> Connect Repository). See infra/terraform/README.md.
resource "google_cloudbuild_trigger" "training_pipeline" {
  depends_on = [google_project_service.apis]

  project     = var.project_id
  name        = "electricity-demand-training-pipeline"
  description = "Build the pipeline image and submit a Vertex AI training run on push to master."
  filename    = "cloudbuild.yaml"

  github {
    owner = var.github_owner
    name  = var.github_repo_name
    push {
      branch = "^master$"
    }
  }

  included_files = [
    "src/electricity_demand/**",
    "dbt/**",
    "Dockerfile",
    "cloudbuild.yaml",
  ]

  service_account = google_service_account.pipeline.id
}

# --- Live-request serving API (Cloud Run service) ---------------------------
# Created only once var.serving_image_uri is set to a real, pushed image -
# the base infra above can be applied without it.
resource "google_cloud_run_v2_service" "serving" {
  depends_on = [google_project_service.apis]

  count    = var.serving_image_uri != "" ? 1 : 0
  name     = "electricity-demand-serving"
  project  = var.project_id
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.pipeline.email
    scaling {
      min_instance_count = 0 # scale to zero: no idle cost
      max_instance_count = 2
    }
    containers {
      image = var.serving_image_uri
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET_MARTS"
        value = var.bq_dataset_marts
      }
      env {
        name  = "MODEL_PATH"
        value = local.serving_model_gcs_path
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = var.frontend_origin != "" ? var.frontend_origin : "*"
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
}

# Public read access: the serving API is read-only forecast data with no
# PII, and the Vercel frontend calls it directly from visitors' browsers
# (no server-side proxy that could hold a service-account token instead).
resource "google_cloud_run_v2_service_iam_member" "serving_public" {
  count    = var.serving_image_uri != "" ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.serving[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Scheduler identity, shared by every scheduled job below ----------------
resource "google_service_account" "scheduler" {
  count        = var.pipeline_image_uri != "" ? 1 : 0
  account_id   = "electricity-demand-scheduler"
  project      = var.project_id
  display_name = "Invokes the scheduled Cloud Run Jobs on a schedule"
}

resource "google_project_iam_member" "scheduler_run_developer" {
  count   = var.pipeline_image_uri != "" ? 1 : 0
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.scheduler[0].email}"
}

# --- Daily EIA ingest: scheduled Cloud Run Job + Cloud Scheduler trigger ----
# Created only once var.pipeline_image_uri is set. First in the daily chain
# (10:00 UTC - after EIA has had overnight to publish) so drift-check/
# batch-predict/retrain-trigger all see today's revisions.
resource "google_cloud_run_v2_job" "ingest_eia" {
  depends_on = [google_project_service.apis]

  count    = var.pipeline_image_uri != "" ? 1 : 0
  name     = "electricity-demand-ingest-eia"
  project  = var.project_id
  location = var.region

  template {
    template {
      service_account = google_service_account.pipeline.email
      containers {
        image   = var.pipeline_image_uri
        command = ["python", "-m", "electricity_demand.data_engineering.ingest_eia"]
        args    = ["--project-id", var.project_id]
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
      max_retries = 1
      timeout     = "600s"
    }
  }
}

resource "google_cloud_scheduler_job" "ingest_eia_daily" {
  depends_on = [google_project_service.apis]

  count     = var.pipeline_image_uri != "" ? 1 : 0
  name      = "electricity-demand-ingest-eia-daily"
  project   = var.project_id
  region    = var.region
  schedule  = "0 10 * * *" # 10:00 UTC daily
  time_zone = "UTC"

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.ingest_eia[0].name}:run"
    http_method = "POST"
    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
    }
  }
}

# --- Daily weather ingest: scheduled Cloud Run Job + Cloud Scheduler trigger
resource "google_cloud_run_v2_job" "ingest_weather" {
  depends_on = [google_project_service.apis]

  count    = var.pipeline_image_uri != "" ? 1 : 0
  name     = "electricity-demand-ingest-weather"
  project  = var.project_id
  location = var.region

  template {
    template {
      service_account = google_service_account.pipeline.email
      containers {
        image   = var.pipeline_image_uri
        command = ["python", "-m", "electricity_demand.data_engineering.ingest_weather"]
        args    = ["--project-id", var.project_id]
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
      max_retries = 1
      timeout     = "600s"
    }
  }
}

resource "google_cloud_scheduler_job" "ingest_weather_daily" {
  depends_on = [google_project_service.apis]

  count     = var.pipeline_image_uri != "" ? 1 : 0
  name      = "electricity-demand-ingest-weather-daily"
  project   = var.project_id
  region    = var.region
  schedule  = "10 10 * * *" # 10:10 UTC daily, shortly after the EIA ingest
  time_zone = "UTC"

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.ingest_weather[0].name}:run"
    http_method = "POST"
    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
    }
  }
}

# --- Batch prediction: scheduled Cloud Run Job + Cloud Scheduler trigger ---
resource "google_cloud_run_v2_job" "batch_predict" {
  depends_on = [google_project_service.apis]

  count    = var.pipeline_image_uri != "" ? 1 : 0
  name     = "electricity-demand-batch-predict"
  project  = var.project_id
  location = var.region

  template {
    template {
      service_account = google_service_account.pipeline.email
      containers {
        image   = var.pipeline_image_uri
        command = ["python", "-m", "electricity_demand.serving.batch_predict"]
        args = [
          "--project-id", var.project_id,
          "--model-path", local.serving_model_gcs_path,
        ]
        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
      max_retries = 1
      timeout     = "600s"
    }
  }
}

resource "google_cloud_scheduler_job" "batch_predict_daily" {
  depends_on = [google_project_service.apis]

  count     = var.pipeline_image_uri != "" ? 1 : 0
  name      = "electricity-demand-batch-predict-daily"
  project   = var.project_id
  region    = var.region
  schedule  = "15 11 * * *" # 11:15 UTC daily
  time_zone = "UTC"

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.batch_predict[0].name}:run"
    http_method = "POST"
    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
    }
  }
}

# --- Monitoring: scheduled drift check + retrain trigger --------------------
resource "google_cloud_run_v2_job" "drift_check" {
  depends_on = [google_project_service.apis]

  count    = var.pipeline_image_uri != "" ? 1 : 0
  name     = "electricity-demand-drift-check"
  project  = var.project_id
  location = var.region

  template {
    template {
      service_account = google_service_account.pipeline.email
      containers {
        image   = var.pipeline_image_uri
        command = ["python", "-m", "electricity_demand.monitoring.drift_check"]
        args    = ["--project-id", var.project_id]
        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
      max_retries = 1
      timeout     = "600s"
    }
  }
}

resource "google_cloud_scheduler_job" "drift_check_daily" {
  depends_on = [google_project_service.apis]

  count     = var.pipeline_image_uri != "" ? 1 : 0
  name      = "electricity-demand-drift-check-daily"
  project   = var.project_id
  region    = var.region
  schedule  = "0 11 * * *" # 11:00 UTC daily, ahead of batch-predict/retrain-trigger
  time_zone = "UTC"

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.drift_check[0].name}:run"
    http_method = "POST"
    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
    }
  }
}

resource "google_cloud_run_v2_job" "retrain_trigger" {
  depends_on = [google_project_service.apis]

  count    = var.pipeline_image_uri != "" && var.serving_image_uri != "" ? 1 : 0
  name     = "electricity-demand-retrain-trigger"
  project  = var.project_id
  location = var.region

  template {
    template {
      service_account = google_service_account.pipeline.email
      containers {
        image   = var.pipeline_image_uri
        command = ["python", "-m", "electricity_demand.monitoring.retrain_trigger"]
        args = [
          "--project-id", var.project_id,
          "--region", var.region,
          "--pipeline-root", local.pipeline_root,
          "--serving-container-image-uri", var.serving_image_uri,
          "--serving-model-gcs-path", local.serving_model_gcs_path,
          "--force", # retrain daily regardless of drift/metric regression - see retrain_trigger.py
        ]
        env {
          name  = "PIPELINE_IMAGE"
          value = var.pipeline_image_uri
        }
      }
      max_retries = 1
    }
  }
}

resource "google_cloud_scheduler_job" "retrain_trigger_daily" {
  depends_on = [google_project_service.apis]

  count     = var.pipeline_image_uri != "" && var.serving_image_uri != "" ? 1 : 0
  name      = "electricity-demand-retrain-trigger-daily"
  project   = var.project_id
  region    = var.region
  schedule  = "45 11 * * *" # 11:45 UTC daily, after drift-check + batch-predict
  time_zone = "UTC"

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.retrain_trigger[0].name}:run"
    http_method = "POST"
    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
    }
  }
}
