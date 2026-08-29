output "api_service_url" {
  value       = google_cloud_run_v2_service.api.uri
  description = "Public HTTPS URI for ResearchMind API Gateway"
}

output "artifacts_bucket_name" {
  value       = google_storage_bucket.artifacts.name
  description = "GCS bucket name for durable research artifacts"
}

output "tasks_topic_id" {
  value       = google_pubsub_topic.agent_tasks.id
  description = "Cloud Pub/Sub topic ID for agent task queue"
}

output "tasks_subscription_id" {
  value       = google_pubsub_subscription.agent_tasks_sub.id
  description = "Cloud Pub/Sub subscription ID for worker consumers"
}

output "api_service_account" {
  value       = google_service_account.api_sa.email
  description = "Service Account email for API Gateway"
}

output "worker_service_account" {
  value       = google_service_account.worker_sa.email
  description = "Service Account email for Worker service"
}
