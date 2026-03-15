output "project_id" {
  description = "GCP project ID"
  value       = google_project.osteotwin.project_id
}

output "data_bucket" {
  description = "GCS data/DICOM bucket name"
  value       = google_storage_bucket.data.name
}

output "pubsub_topic" {
  description = "Pub/Sub topic for simulation tasks"
  value       = google_pubsub_topic.simulation_tasks.id
}

output "pubsub_subscription" {
  description = "Pub/Sub subscription for simulation workers"
  value       = google_pubsub_subscription.simulation_worker.id
}

output "checkpoint_bucket" {
  description = "GCS bucket for simulation checkpoints"
  value       = google_storage_bucket.checkpoints.name
}

output "spot_mig" {
  description = "Spot GPU MIG (target_size=0, dormant)"
  value       = google_compute_instance_group_manager.sim_workers.name
}

output "dicom_bucket" {
  description = "Encrypted GCS bucket for DICOM storage"
  value       = google_storage_bucket.dicom.name
}

output "secret_admin" {
  description = "Secret Manager ID for admin password"
  value       = google_secret_manager_secret.admin_password.secret_id
}

output "secret_anthropic" {
  description = "Secret Manager ID for Anthropic API key"
  value       = google_secret_manager_secret.anthropic_key.secret_id
}

output "secret_gemini" {
  description = "Secret Manager ID for Gemini API key"
  value       = google_secret_manager_secret.gemini_key.secret_id
}

output "secret_jwt" {
  description = "Secret Manager ID for JWT secret"
  value       = google_secret_manager_secret.jwt_secret.secret_id
}

output "secret_sim" {
  description = "Secret Manager ID for Simulation API key"
  value       = google_secret_manager_secret.sim_key.secret_id
}

output "secret_neo4j" {
  description = "Secret Manager ID for Neo4j password"
  value       = google_secret_manager_secret.neo4j_password.secret_id
}
