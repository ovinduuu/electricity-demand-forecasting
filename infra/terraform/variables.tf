variable "project_id" {
  description = "GCP project ID to deploy into."
  type        = string
}

variable "region" {
  description = "Default GCP region."
  type        = string
  default     = "us-central1"
}

variable "bq_location" {
  description = "BigQuery dataset location. Use a multi-region (e.g. US) to stay in the free tier for storage/queries."
  type        = string
  default     = "US"
}

variable "raw_bucket_name" {
  description = "GCS bucket name for raw data landing. Must be globally unique."
  type        = string
}

variable "bq_dataset_raw" {
  type    = string
  default = "electricity_demand_raw"
}

variable "bq_dataset_staging" {
  type    = string
  default = "electricity_demand_staging"
}

variable "bq_dataset_marts" {
  type    = string
  default = "electricity_demand_marts"
}

variable "training_sa_name" {
  description = "Service account used by training/pipeline/ingest jobs."
  type        = string
  default     = "electricity-demand-pipeline"
}

variable "artifact_repo_name" {
  description = "Artifact Registry Docker repo for pipeline/serving images."
  type        = string
  default     = "electricity-demand"
}

variable "github_owner" {
  description = "GitHub owner/org that hosts this repo, for the Cloud Build trigger."
  type        = string
  default     = "ovinduuu"
}

variable "github_repo_name" {
  description = "GitHub repository name, for the Cloud Build trigger."
  type        = string
  default     = "electricity-demand-forecasting"
}

variable "pipeline_image_uri" {
  description = <<-EOT
    Pipeline image URI (see ../../Dockerfile) - used for KFP components and
    the ingest/batch-predict/monitoring Cloud Run Jobs. Leave as "" to apply
    the base infra (bucket/BigQuery/Artifact Registry/Cloud Build trigger)
    before the image exists; those jobs and their schedulers are only
    created once this is set to a real pushed image.
  EOT
  type    = string
  default = ""
}

variable "serving_image_uri" {
  description = <<-EOT
    Serving image URI (see ../../docker/serving.Dockerfile) - used for the
    live-request serving API. Leave as "" until it's built and pushed; the
    Cloud Run service is only created once this is set.
  EOT
  type    = string
  default = ""
}

variable "frontend_origin" {
  description = <<-EOT
    Origin (scheme + host, e.g. https://your-app.vercel.app) the serving
    Cloud Run service's CORS policy allows. Leave as "" to allow all
    origins ("*"), fine for a personal demo but worth tightening once the
    frontend has a real deployed URL.
  EOT
  type    = string
  default = ""
}
