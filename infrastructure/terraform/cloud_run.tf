# -----------------------------------------------------------------------------
# Google Cloud Run (v2) — API Gateway Service
# -----------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name     = local.api_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api_sa.email

    scaling {
      min_instance_count = var.api_min_instances
      max_instance_count = var.api_max_instances
    }

    containers {
      image = var.api_image

      resources {
        limits = {
          cpu    = "2000m"
          memory = "2048Mi"
        }
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "APP_ENV"
        value = var.environment
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "PUBSUB_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "PUBSUB_TASKS_TOPIC"
        value = google_pubsub_topic.agent_tasks.name
      }
      env {
        name  = "PUBSUB_TASKS_SUBSCRIPTION"
        value = google_pubsub_subscription.agent_tasks_sub.name
      }
      env {
        name  = "PORT"
        value = "8080"
      }

      # Secrets
      env {
        name = "RESEARCHMIND_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.researchmind_api_key.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_project_iam_member.api_firestore,
    google_project_iam_member.api_pubsub,
    google_project_iam_member.api_storage_viewer,
  ]
}

# -----------------------------------------------------------------------------
# Google Cloud Run (v2) — Background Research Job Worker Service
# -----------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "worker" {
  name     = local.worker_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.worker_sa.email

    scaling {
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_max_instances
    }

    containers {
      image   = var.worker_image
      command = ["python", "-m", "app.jobs.main"]

      resources {
        limits = {
          cpu    = "4000m"
          memory = "4096Mi"
        }
      }

      env {
        name  = "APP_ENV"
        value = var.environment
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "PUBSUB_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "PUBSUB_TASKS_TOPIC"
        value = google_pubsub_topic.agent_tasks.name
      }
      env {
        name  = "PUBSUB_TASKS_SUBSCRIPTION"
        value = google_pubsub_subscription.agent_tasks_sub.name
      }
      env {
        name  = "WORKER_CONCURRENCY"
        value = tostring(var.worker_concurrency)
      }
      env {
        name  = "MAX_ORCHESTRATION_CONCURRENCY"
        value = tostring(var.max_orchestration_concurrency)
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "QDRANT_URL"
        value = var.qdrant_url
      }

      # Secrets
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TAVILY_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.tavily_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "QDRANT_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.qdrant_api_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_project_iam_member.worker_firestore,
    google_project_iam_member.worker_pubsub,
    google_project_iam_member.worker_storage,
  ]
}
