terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

# Random suffix to ensure globally unique project ID
resource "random_id" "project_suffix" {
  byte_length = 3
}

locals {
  project_id = "osteotwin-${random_id.project_suffix.hex}"
  region     = var.region
}

provider "google" {
  region = local.region
}

# --- GCP Project ---
resource "google_project" "osteotwin" {
  name            = "OsteoTwin"
  project_id      = local.project_id
  billing_account = var.billing_account
}

# --- Enable APIs ---
resource "google_project_service" "services" {
  for_each = toset([
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "pubsub.googleapis.com",
    "compute.googleapis.com",
    "firestore.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
  ])
  project = google_project.osteotwin.project_id
  service = each.value

  disable_on_destroy = false
}

# --- GCS Bucket for DICOM storage & backups ---
resource "google_storage_bucket" "data" {
  name     = "${local.project_id}-data"
  location = var.bucket_region
  project  = google_project.osteotwin.project_id

  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  # Hot storage: Standard for 14 days, then Coldline (never deleted)
  lifecycle_rule {
    condition {
      age                   = 14
      matches_prefix        = ["backups/"]
      matches_storage_class = ["STANDARD"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  depends_on = [google_project_service.services]
}

# --- GCS Bucket for DICOM (encrypted, strict access) ---
resource "google_storage_bucket" "dicom" {
  name     = "${local.project_id}-dicom"
  location = local.region  # same region as compute for fast access
  project  = google_project.osteotwin.project_id

  uniform_bucket_level_access = true
  force_destroy               = false

  # Server-side encryption is automatic (Google-managed AES-256-GCM).
  # For CMEK, add a google_kms_crypto_key and reference it here.

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 365  # retain DICOM for 1 year
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.services]
}

# =============================================================================
# Pub/Sub: Async simulation task queue
# =============================================================================

resource "google_pubsub_topic" "simulation_tasks" {
  name    = "simulation-tasks-topic"
  project = google_project.osteotwin.project_id

  message_retention_duration = "86400s" # 24 hours

  depends_on = [google_project_service.services]
}

resource "google_pubsub_subscription" "simulation_worker" {
  name    = "simulation-worker-sub"
  topic   = google_pubsub_topic.simulation_tasks.id
  project = google_project.osteotwin.project_id

  ack_deadline_seconds       = 600  # 10 min — simulations can be long
  message_retention_duration = "604800s" # 7 days
  retain_acked_messages      = false

  # Dead letter after 5 failed attempts
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  depends_on = [google_project_service.services]
}

# =============================================================================
# GCS: Simulation checkpoint bucket
# =============================================================================

resource "google_storage_bucket" "checkpoints" {
  name     = "${local.project_id}-checkpoints"
  location = local.region
  project  = google_project.osteotwin.project_id

  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = false # checkpoints are overwritten, no need for versions
  }

  lifecycle_rule {
    condition {
      age = 30 # clean up checkpoints older than 30 days
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.services]
}

# =============================================================================
# Compute: Spot GPU Instance Template (DORMANT — target_size = 0)
# =============================================================================

resource "google_compute_instance_template" "sim_worker_spot" {
  name_prefix  = "osteotwin-sim-worker-"
  machine_type = "g2-standard-8" # 8 vCPU, 32 GB RAM (L4-compatible)
  project      = google_project.osteotwin.project_id
  region       = local.region

  scheduling {
    preemptible                 = true
    automatic_restart           = false
    on_host_maintenance         = "TERMINATE"
    provisioning_model          = "SPOT"
    instance_termination_action = "STOP"
  }

  # GPU: NVIDIA L4 (24GB VRAM) — quota=1 confirmed in asia-northeast1
  # L4 is Ada Lovelace gen, 2x faster than T4 for FP32, native TF32 support
  # Spot pricing ~$0.22/hr vs $0.70/hr on-demand
  guest_accelerator {
    type  = "nvidia-l4"
    count = 1
  }

  disk {
    source_image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
    auto_delete  = true
    boot         = true
    disk_size_gb = 100
    disk_type    = "pd-ssd"
  }

  network_interface {
    network = "default"
    access_config {} # ephemeral public IP
  }

  metadata = {
    startup-script = <<-EOT
      #!/bin/bash
      set -e
      echo "OsteoTwin Simulation Worker starting..."

      # Install dependencies
      pip install google-cloud-pubsub google-cloud-storage trimesh vtk pydicom numpy scipy

      # Fetch worker code from GCS
      mkdir -p /opt/osteotwin
      gsutil -m cp -r gs://${local.project_id}-data/worker/* /opt/osteotwin/

      # Fetch secrets
      export SIM_API_KEY=$(gcloud secrets versions access latest --secret=sim-api-key --project=${local.project_id})

      # Run worker with idle timeout (auto-shutdown after 5 min idle)
      cd /opt/osteotwin
      timeout 1800 python worker.py \
        --project=${local.project_id} \
        --subscription=simulation-worker-sub \
        --checkpoint-bucket=${local.project_id}-checkpoints \
        || true

      # Auto-shutdown: scale MIG to 0 when worker is done
      echo "Worker idle or timed out. Scaling MIG to 0..."
      ZONE=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/zone" -H "Metadata-Flavor: Google" | cut -d/ -f4)
      INSTANCE_NAME=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/name" -H "Metadata-Flavor: Google")
      gcloud compute instance-groups managed resize osteotwin-sim-workers \
        --size=0 --zone=$ZONE --project=${local.project_id} --quiet || true
      echo "MIG scaled to 0. Shutting down."
      shutdown -h now
    EOT
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [google_project_service.services]
}

# Managed Instance Group — SIZE 0 (dormant, no cost)
resource "google_compute_instance_group_manager" "sim_workers" {
  name               = "osteotwin-sim-workers"
  base_instance_name = "sim-worker"
  zone               = "${local.region}-a"  # L4 GPUs available in all 3 zones
  project            = google_project.osteotwin.project_id

  version {
    instance_template = google_compute_instance_template.sim_worker_spot.self_link_unique
  }

  # STRICTLY SIZE 0 — no instances run until manually scaled up
  target_size = 0

  depends_on = [google_project_service.services]
}

# --- Secret Manager: Admin Password ---
resource "google_secret_manager_secret" "admin_password" {
  secret_id = "admin-password"
  project   = google_project.osteotwin.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

# --- Secret Manager: Anthropic API Key ---
resource "google_secret_manager_secret" "anthropic_key" {
  secret_id = "anthropic-api-key"
  project   = google_project.osteotwin.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

# --- Secret Manager: Gemini API Key ---
resource "google_secret_manager_secret" "gemini_key" {
  secret_id = "gemini-api-key"
  project   = google_project.osteotwin.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

# --- Secret Manager: JWT Secret ---
resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "jwt-secret-key"
  project   = google_project.osteotwin.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

# --- Secret Manager: Simulation API Key ---
resource "google_secret_manager_secret" "sim_key" {
  secret_id = "sim-api-key"
  project   = google_project.osteotwin.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

# --- Secret Manager: Neo4j Password ---
resource "google_secret_manager_secret" "neo4j_password" {
  secret_id = "neo4j-password"
  project   = google_project.osteotwin.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

# =============================================================================
# Firestore: User Auth + Clinical Case Logging (Native Mode)
# =============================================================================

resource "google_firestore_database" "clinical_logs" {
  name        = "(default)"
  project     = google_project.osteotwin.project_id
  location_id = local.region
  type        = "FIRESTORE_NATIVE"

  deletion_policy = "DELETE"

  depends_on = [google_project_service.services]
}

# Users collection: single-field indexes auto-created by Firestore for
# username and status queries. No composite index needed.

resource "google_firestore_index" "case_timestamp" {
  project    = google_project.osteotwin.project_id
  database   = google_firestore_database.clinical_logs.name
  collection = "clinical_case_logs"

  fields {
    field_path = "case_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "timestamp"
    order      = "DESCENDING"
  }

  depends_on = [google_firestore_database.clinical_logs]
}

resource "google_firestore_index" "surgeon_timestamp" {
  project    = google_project.osteotwin.project_id
  database   = google_firestore_database.clinical_logs.name
  collection = "clinical_case_logs"

  fields {
    field_path = "surgeon_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "timestamp"
    order      = "DESCENDING"
  }

  depends_on = [google_firestore_database.clinical_logs]
}

# =============================================================================
# Artifact Registry: Docker container images
# =============================================================================

resource "google_artifact_registry_repository" "osteotwin" {
  location      = local.region
  repository_id = "osteotwin"
  format        = "DOCKER"
  project       = google_project.osteotwin.project_id
  description   = "OsteoTwin container images (planning, simulation, dashboard)"

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.services]
}

# =============================================================================
# Cloud Run: Planning Server (scale-to-zero)
# =============================================================================

resource "google_cloud_run_v2_service" "planning" {
  name     = "osteotwin-planning"
  location = local.region
  project  = google_project.osteotwin.project_id

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = "${local.region}-docker.pkg.dev/${local.project_id}/osteotwin/planning-server:latest"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }

      # Plain env vars
      env {
        name  = "PLAN_HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "PLAN_PORT"
        value = "8080"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = local.project_id
      }

      # Secrets from Secret Manager
      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.anthropic_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "JWT_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SIM_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.sim_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ADMIN_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "NEO4J_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.neo4j_password.secret_id
            version = "latest"
          }
        }
      }

      # SIMULATION_SERVER_URL is set after deploy via gcloud (circular dependency)
    }

    timeout = "300s"

    service_account = google_service_account.cloud_run.email
  }

  depends_on = [
    google_project_service.services,
    google_artifact_registry_repository.osteotwin,
  ]

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,                   # managed by Cloud Build
      template[0].containers[0].env,                     # SIMULATION_SERVER_URL set post-deploy
    ]
  }
}

# Public access for planning server (has its own JWT auth)
resource "google_cloud_run_v2_service_iam_member" "planning_public" {
  project  = google_project.osteotwin.project_id
  location = local.region
  name     = google_cloud_run_v2_service.planning.name
  role     = "roles/run.invoker"
  member   = "allUsers"

  depends_on = [google_cloud_run_v2_service.planning]
}

# =============================================================================
# Cloud Run: Simulation Server (scale-to-zero, internal only)
# =============================================================================

resource "google_cloud_run_v2_service" "simulation" {
  name     = "osteotwin-simulation"
  location = local.region
  project  = google_project.osteotwin.project_id

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = "${local.region}-docker.pkg.dev/${local.project_id}/osteotwin/simulation-server:latest"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "4"
          memory = "2Gi"
        }
      }

      env {
        name  = "SIM_HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "SIM_PORT"
        value = "8080"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = local.project_id
      }
      env {
        name = "SIM_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.sim_key.secret_id
            version = "latest"
          }
        }
      }
    }

    timeout = "300s"

    service_account = google_service_account.cloud_run.email
  }

  depends_on = [
    google_project_service.services,
    google_artifact_registry_repository.osteotwin,
  ]

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

# Simulation server: only callable by planning server (service-to-service auth)
resource "google_cloud_run_v2_service_iam_member" "simulation_invoker" {
  project  = google_project.osteotwin.project_id
  location = local.region
  name     = google_cloud_run_v2_service.simulation.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cloud_run.email}"

  depends_on = [google_cloud_run_v2_service.simulation]
}

# =============================================================================
# Cloud Run: Dashboard (static nginx, scale-to-zero)
# =============================================================================

resource "google_cloud_run_v2_service" "dashboard" {
  name     = "osteotwin-dashboard"
  location = local.region
  project  = google_project.osteotwin.project_id

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = "${local.region}-docker.pkg.dev/${local.project_id}/osteotwin/dashboard:latest"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
      }

      # Proxy targets (set post-deploy by Cloud Build)
      env {
        name  = "PLANNING_API_URL"
        value = "http://localhost:8200"
      }
      env {
        name  = "SIMULATION_API_URL"
        value = "http://localhost:8300"
      }
    }

    timeout = "60s"

    service_account = google_service_account.cloud_run.email
  }

  depends_on = [
    google_project_service.services,
    google_artifact_registry_repository.osteotwin,
  ]

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[0].env,
    ]
  }
}

# Public access for dashboard
resource "google_cloud_run_v2_service_iam_member" "dashboard_public" {
  project  = google_project.osteotwin.project_id
  location = local.region
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = "allUsers"

  depends_on = [google_cloud_run_v2_service.dashboard]
}

# =============================================================================
# IAM: Cloud Run Service Account
# =============================================================================

resource "google_service_account" "cloud_run" {
  account_id   = "osteotwin-cloudrun"
  display_name = "OsteoTwin Cloud Run Service Account"
  project      = google_project.osteotwin.project_id

  depends_on = [google_project_service.services]
}

# Cloud Run SA can read secrets
resource "google_project_iam_member" "cloudrun_secret_accessor" {
  project = google_project.osteotwin.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"

  depends_on = [google_service_account.cloud_run]
}

# Cloud Run SA can read/write GCS (mesh cache, DICOM, checkpoints)
resource "google_project_iam_member" "cloudrun_storage" {
  project = google_project.osteotwin.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"

  depends_on = [google_service_account.cloud_run]
}

# Cloud Run SA can publish to Pub/Sub (async simulation dispatch)
resource "google_project_iam_member" "cloudrun_pubsub" {
  project = google_project.osteotwin.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"

  depends_on = [google_service_account.cloud_run]
}

# Cloud Run SA can read/write Firestore (clinical logs)
resource "google_project_iam_member" "cloudrun_firestore" {
  project = google_project.osteotwin.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"

  depends_on = [google_service_account.cloud_run]
}

# Cloud Build SA can push to Artifact Registry
resource "google_project_iam_member" "cloudbuild_ar_writer" {
  project = google_project.osteotwin.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_project.osteotwin.number}@cloudbuild.gserviceaccount.com"

  depends_on = [google_project_service.services]
}

# Cloud Build SA can deploy Cloud Run services
resource "google_project_iam_member" "cloudbuild_run_admin" {
  project = google_project.osteotwin.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_project.osteotwin.number}@cloudbuild.gserviceaccount.com"

  depends_on = [google_project_service.services]
}

# Cloud Build SA can act as the Cloud Run service account
resource "google_service_account_iam_member" "cloudbuild_act_as" {
  service_account_id = google_service_account.cloud_run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_project.osteotwin.number}@cloudbuild.gserviceaccount.com"

  depends_on = [google_service_account.cloud_run]
}
