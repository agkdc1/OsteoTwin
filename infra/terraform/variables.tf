variable "billing_account" {
  description = "GCP billing account ID (required — run: gcloud billing accounts list)"
  type        = string
  # No default — each contributor provides their own billing account
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "asia-northeast1"
}

variable "bucket_region" {
  description = "GCS bucket region (us-west1 for free tier)"
  type        = string
  default     = "us-west1"
}
